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
