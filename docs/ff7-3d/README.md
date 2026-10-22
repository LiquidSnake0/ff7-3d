# ff7-3d: roadmap and architecture

ff7-3d puts *Final Fantasy VII* (PS1, USA, disc 1) on the New Nintendo 3DS with real stereoscopic 3D.
Polygons (characters, battles, world map) already carry a depth. The pre-rendered field backgrounds do not:
the core of this project is giving every background a believable relief, generated on the player's machine.

## Layers

```
A. Workshop (outils/, runs on the player's PC, never ships game data)
   disc image -> field DAT / MIM -> composed background per layer and variant
   -> exact depth anchors (walkmesh projected by the field camera, layer-2 tile depths, layers 3/4)
   -> monocular depth (Depth Anything V2 Small, Apache-2.0) -> fit on the anchors
   -> relief mesh + occlusion depth -> per-field package on the SD card

B. Game = ff7-decomp (unchanged), later built for the 3DS through PsyZ
   one drawing entry point swapped: AddBackgroundToRender() -> the 3DS relief renderer

C. PsyZ 3DS backend (later), modelled on PsyZ's PSP backend and on CTR-3D

D. 3DS renderer (port3ds/, citro3d)
   1. background: relief mesh, colour writes, no depth writes
   2. occlusion: flat cards at the ORIGINAL depths (4 x tile ID), depth writes only
   3. game polygons (Cloud, NPCs): depth test, depth from the GTE
   4. UI: screen plane, no depth test
   stereo: the right eye replays the frame through a second projection; separation = 3D slider
```

### Two depths, never mixed

- The **display depth** (relief) only shifts pixels between the eyes. It comes from the depth model, fitted on the
  game's own anchors.
- The **occlusion depth** reproduces the PS1 ordering table exactly: layer-2 tiles at `4 x ID`, layers 3 and 4 at
  their current depth (the `BGPDH` script opcode can change it), layer 1 at infinity. Cloud walks behind a pillar
  exactly when he did on the PS1.

## What the field data gives (read from ff7-decomp's `src/field/field_bg.c`, not modified)

| Layer | Tiles | Depth |
|---|---|---|
| 1 | 16x16 | none: everything sits in `ot[4095]` |
| 2 | 16x16 | one `u16` per tile (`FieldBgAnimatedTile16.depth`), about camera Z / 4 |
| 3 | 32x32 | one value for the whole layer (`layer2Depth`), may scroll |
| 4 | 32x32 | one value for the whole layer (`layer3Depth`) |

The walkmesh projected by the field camera (`zoom` is the GTE projection distance `H`) gives the exact depth of
the floor. Everything else needs the depth model.

## Milestone 1: one Midgar field in stereo on the New 3DS, Cloud walking in it

Target field: `MD1STIN` (index 116 in `g_FieldFileInfo`), then `MD1_1`.

1. [x] Disc reader: raw `MODE2/2352` image, ISO 9660, serial check of the player's disc (`SCUS-94163`).
2. [x] LZS, field DAT sections, MIM upload into an emulated 1024x512 PS1 VRAM.
3. [x] Background composer: 4 layers, CLUT decode, semi-transparency, variants (`parameter & 0x3F`, `state`).
4. [x] Camera and walkmesh, GTE projection of the floor onto the background.
5. [x] Depth anchors: floor, layer-2 tiles, layers 3/4; occlusion depth map.
6. [x] Depth model on the composed background, fitted on the anchors.
7. [x] Relief mesh (regular 4 px grid; cutting it at depth discontinuities is still to do) and the package format read by the 3DS.
8. [~] 3DS viewer: relief in stereo with the 3D slider, frame counter. Built (`port3ds/`), not yet run on hardware.
9. [~] Occlusion pass and a test object passing behind a layer-2 pillar. Built (package v2, 296 cards on `MD1STIN`), not yet run on hardware.
10. [~] Cloud: model, walk animation, movement on the walkmesh; measurements. Movement on the walkmesh is built with a stand-in character (package v3 carries the camera and the walkmesh); Cloud's model and animation are next.

Milestone 2 joins ff7-decomp: PsyZ 3DS backend, the real field engine driving Cloud, `AddBackgroundToRender`
replaced.

## Where it stands

- `MD1STIN` goes from the player's disc to a 1 MB relief package: background composed in ordering-table order
  (94 % of the 512x512 canvas covered), floor anchors from the walkmesh, depth model fitted with a 1.5 % median
  error on the floor, 16 641 vertices, 32 768 triangles. A PC preview (`outils/apercu.py`) shows the expected
  parallax.
- The 3DS viewer builds to `port3ds/ff7-3d.3dsx`; the first run on a New 3DS is the next step.
- Not yet: Cloud's model and animation (step 10), background variants (`parameter`/`state` groups:
  `MD1STIN` has none), layer 3/4 scrolling.

## Rules

- No decompilation work, no change to the decompiled functions, nothing sent upstream.
- No game data in the repository, ever: outputs go to `sortie/` (ignored).
- AGPL-3.0 for the whole project; reused CTR-3D code keeps its GPL-3.0 header.
