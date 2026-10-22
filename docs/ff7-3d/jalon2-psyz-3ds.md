# Milestone 2: a PsyZ backend for the New 3DS

Milestone 1 draws a field with the workshop's data and a stand-alone viewer (`port3ds/`). Milestone 2 runs the
game itself: ff7-decomp built for the 3DS through PsyZ, the field engine driving Cloud, and
`AddBackgroundToRender()` drawing the relief instead of the PS1 tiles. This page is the plan. Nothing of it is
coded yet.

## How PsyZ is built (read at `tools/psyz/psyz`, commit `6fe342d`, not modified)

PsyZ replaces the PSY-Q libraries (`libgpu`, `libgte`, `libspu`, `libcd`, `libetc`, `libapi`...) with portable C.
The libraries themselves (`src/psyz/`) never touch a platform: everything goes through a small backend layer.

| Layer | Where | What |
|---|---|---|
| PSY-Q replacement | `src/psyz/*.c` | `DrawOTag`, `LoadImage`, `PutDispEnv`, GTE in software, CD reads, pads, SPU registers |
| Draw backend contract | `src/draw.h` | the GPU of the PS1 as a list of commands (below) |
| Other backends | `src/internal.h`, `include/psyz/*.h` | file I/O, pads, audio output, OS (threads, timers, logs) |
| Backends | `src/platform/` (SDL3: GL, GPU, software), `src/psp/`, `src/web/`, `src/ios/` | one folder per target |

The draw contract (`src/draw.h`) is the whole PS1 GPU seen from the CPU:

| Group | Functions |
|---|---|
| Display | `Draw_Reset`, `Draw_DisplayEnable`, `Draw_DisplayArea`, `Draw_DisplayHorizontalRange`, `Draw_DisplayVerticalRange`, `Draw_SetDisplayMode`, `Draw_PutDispEnv` |
| Drawing state | `Draw_SetTexpageMode`, `Draw_SetTextureWindow`, `Draw_SetAreaStart`, `Draw_SetAreaEnd`, `Draw_SetOffset`, `Draw_SetMask` |
| VRAM transfers | `Draw_ClearImage`, `Draw_LoadImage`, `Draw_StoreImage`, `Draw_MoveImage` |
| Primitives | `Draw_PushPrim` (one GP0 packet of the ordering table), `Draw_ResetBuffer`, `Draw_FlushBuffer`, `Draw_ExequeSync` |

`DrawOTag` (`src/psyz/libgpu.c`) walks the ordering table and hands every packet to `Draw_PushPrim`; a backend
only has to understand GP0 packets, VRAM rectangles and the display registers.

### The PSP backend, the closest model

The PSP is the nearest hardware to the 3DS among PsyZ's targets: a fixed-function GPU, little memory, a vendor
SDK, no fragment shader. Its files (`src/psp/README.md`):

| File | Role | 3DS counterpart |
|---|---|---|
| `psp.cmake` | toolchain shim, `psyz_psp_*` helpers | a `n3ds.cmake` on devkitARM (`$DEVKITPRO/cmake/3DS.cmake`) |
| `psp_startup.c` | module info, HOME exit callback | `aptMainLoop`, `gfxInitDefault`, `romfsInit` |
| `psp_gpu.c` (2 600 lines) | `sceGu` renderer: emulated 1024x512 VRAM, page and CLUT caches, readback for `StoreImage` | citro3d renderer (below), the largest piece |
| `psp_input.c` | `sceCtrl` pad | `hidScanInput`, circle pad as the analog stick |
| `psp_audio.c` | audio thread, PCM to `sceAudio` | `ndsp` on a thread, double buffer |
| `psp_sas.c` | SPU voices on the Media Engine | none on the 3DS: the software SPU (`psyz_spu.c`) on the second ARM11 core of the New 3DS (`APT_SetAppCpuTimeLimit`) |
| `psp_file.c` | `sceIo*` file I/O | stdio on `sdmc:/3ds/ff7-3d/` |
| `psp_os.c`, `psp_misc.c`, `psp_log.c` | threads, timers, no-ops, logs | `svcCreateThread`, `svcGetSystemTick`, stderr through `3dslink` |
| `psp_module_glue.c`, `psp_module_host.c` | overlays as PRX modules | not needed at first: every overlay is linked in (below) |

What the PSP backend teaches, and what will hold on the 3DS too:

- the PS1 VRAM stays a CPU-side shadow (`g_vram`); textures are decoded from it into the GPU's formats on demand,
  in caches keyed by texture page, CLUT and the freshness of the rows they cover;
- `StoreImage` and `MoveImage` on drawn pixels need a framebuffer readback, which stalls the GPU: track what was
  drawn this frame and skip the readback when the rectangle misses it;
- testing on real hardware is mandatory (the emulators are more lenient than the GPU).

## The blocker to solve first: the PS1 addresses

The PC build runs the decompiled code at the PS1's own addresses: `src/pc/main.c` maps `0x80010000` (main RAM,
`0x1F0000` bytes) and `0x1F800000` (scratchpad) with `mmap(MAP_FIXED_NOREPLACE)`, because the game still writes
to fixed addresses (`SysGzipSetDataBlock((u8*)0x801B0000)`, the field buffers, the overlays): about 77 pointer
casts of a `0x80xxxxxx` constant under `src/`.

A 3DS application cannot do that. Its user address space ends well below `0x80000000` (code from `0x00100000`,
heap from `0x08000000`, linear memory from `0x30000000` on the New 3DS), and `svcControlMemory` only maps inside
those regions. The 32-bit pointers of the 3DS are an advantage (`u_long` holds a pointer, as on the PS1), the
address range is not.

Options, in the order to try them:

1. **Rewrite the constants at build time, without touching `src/`.** The CMake already passes every source
   through a tool (`tools/str.c`, which converts FF7 strings). A second pass of the same kind, in the 3DS build
   only, would turn a `0x80xxxxxx` / `0x1F80xxxx` literal used as a pointer into `(g_PsxRam + offset)` /
   `(g_PsxScratch + offset)`. To check: that every such literal is a pointer (some are masks or packed values),
   and that no address is computed from pieces.
2. **A fixed base the code agrees with.** If upstream ever introduces a `PSX_ADDR()` macro for the PC build
   (other platforms such as the web target have the same problem), use it. Nothing is asked upstream from here.
3. **Catch the faults.** Leave the constants and translate the data aborts in an exception handler. Slow and
   fragile; only as a diagnostic to list the addresses the game really touches.

Step 0 of the milestone measures this before any renderer work: build `ff7` on PC with option 1's rewrite and
check that `MD1STIN` still loads and runs to `AddBackgroundToRender`.

## The renderer on citro3d

The PICA200 has no fragment shader and no indexed texture format, like the PSP's GE. CTR-3D
(`docs/3DS_PORT.md`, GPL-3.0) solved the same contract on the same hardware; ff7-3d takes its design, and its
code where it fits (keeping its GPL-3.0 header):

- **Textures:** PS1 VRAM decoded on the CPU into RGBA textures in sub-page cells, keyed by page, CLUT and VRAM
  freshness; one lookup table per palette.
- **Packets:** the ordering table walked and turned into GPU triangles, opaque primitives binned by GPU state
  (a frame in about twenty draws), semi-transparent ones replayed in order.
- **Depth:** the PS1 sorts by order, the 3DS tests depth. Every primitive gets a depth: the GTE's when the
  geometry has one (Cloud, NPCs), otherwise its ordering-table slot, so the original order survives as depth.
  On a field this is exactly the occlusion depth of milestone 1 (`4 x tile ID` for layer 2).
- **Stereo:** the frame's commands are journaled and the right eye replays them through a second projection.
- **Field backgrounds:** `AddBackgroundToRender` is the one entry point the 3DS build swaps, `src/` untouched:
  it is defined in `src/field/field_bg.c` and called from `src/field/field_loop.c`, another object, so
  `-Wl,--wrap=AddBackgroundToRender` routes the call to a `__wrap_AddBackgroundToRender` of `port3ds/`. It draws the relief package of the current field instead of pushing the
  background tiles, and writes the occlusion cards. Everything else of the field (models, dialogue windows,
  fades) goes through the packet path.

The milestone 1 viewer stays the reference: same package, same shaders (`relief.v.pica`, `modele.v.pica`), same
projection and convergence rules.

## Steps

| # | Step | Done when |
|---|---|---|
| 0 | Address rewrite pass (option 1) on the PC build | `ff7` on PC runs `MD1STIN` with the rewritten sources, nothing mapped at `0x80010000` |
| 1 | `n3ds.cmake`, startup, file I/O on `sdmc:`, logs through `3dslink` | the PsyZ boot logo of the PC build prints its log lines on the console |
| 2 | Draw backend, packet path only (no texture cache: flat colours) | the boot logo and the menus draw, upside right, 400x240 |
| 3 | Texture cache from the shadow VRAM | the field background tiles draw as on the PC build (before any relief) |
| 4 | Pads, then audio (`ndsp`, software SPU on the second core) | Cloud walks on `MD1STIN` with the engine's own walkmesh code; music plays |
| 5 | `AddBackgroundToRender` wrapped: relief package + occlusion cards | `MD1STIN` in stereo, Cloud driven by the field scripts, passing behind the same pillars as in milestone 1 |
| 6 | Measures and budget | 30 fps held on `MD1STIN` and `MD1_1` (the PS1 field runs at 30), memory under the New 3DS application budget |

Not before step 5: battles, the world map, FMVs, saving (`sceUtilitySavedata` is not done on the PSP either).

## Open questions

- Are all `0x80xxxxxx` literals pointers? A list per file, built by the rewrite pass in a dry-run mode, decides it.
- `FieldModelAnimCalcMtrxs` and `FieldModelPrepareRender` are `NOT_IMPLEMENTED` in `src/pc/stubs_field.c`
  (still assembly upstream). Until upstream decompiles them, the 3DS build can draw the field models with
  the workshop's floating-point reading (`outils/ff7_3d/modele.py`, ported to C) behind the same names in
  `port3ds/`, never in `src/`.
- Memory: 2 MB of PS1 RAM, 1 MB of shadow VRAM, the relief package (about 1.5 MB per field with Cloud) and the
  texture cache must fit next to citro3d's command buffers; the New 3DS gives an application about 124 MB, so
  the budget is the linear memory for vertex buffers and textures, not the total.
- How far PsyZ's software GTE costs on the 804 MHz ARM11: measure at step 2 with the boot logo, as the PSP
  README did (12 fps to 172 fps once the SPU moved off the main CPU).
