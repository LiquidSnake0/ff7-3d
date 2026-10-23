# Cloud on the 3DS: field models

The player's character comes from the player's disc, like the backgrounds: `FIELD/CLOUD.BCX` (LZS), baked
by the workshop into the field package (section `PERS`, since package version 4; the exits came with version 5),
drawn by the 3DS viewer.

## What the field data says (read in ff7-decomp, not modified)

| Piece | Where | What |
|---|---|---|
| Which characters a field loads | DAT section 7 (`FieldModelLoaderData`, `include/game.h`) | per model: face id, bones, parts, animations, `npcFlag`, `globalModelId` (1 to 9: a party member, read from a BCX) |
| A party member | `FIELD/<NAME>.BCX`, `FieldModelLoadBcx` | `{size, sectionOffset}`, then a whole `FieldModel` whose pointers are PS1 addresses (`0x80000000 + offset`) |
| Skeleton | `FieldModelBone` | `{s16 length, s8 parent, s8 hasPart}`; Cloud: 22 bones |
| Parts | `FieldModelPart` (32 bytes) | bone, vertex count, polygon counts (GT4, GT3, FT4, FT3, F3, F4, G3, G4), offsets; vertices are `SVECTOR`s after a `u32` flag word |
| Polygons | `FieldModelPoly*` | vertex indices, one colour per vertex (G/GT) or per polygon (F/FT), texture coordinate indices, texture word (`FieldModelCreatePktsForPart`) |
| Animations | `FieldModelAnimation` (16 bytes) | frame count, rotation tracks (bytes), translation tracks and static translations (`s16`); Cloud: 0 standing (1 frame), 1 walking (30), 2 running (15) |
| Scale | `FieldModel.scale`, `FieldModelScaleModel` | 4.12 fixed point applied to vertices, bone lengths and translations: Cloud is `512`, so 1/8 |

### The bone matrices

`FieldModelAnimCalcMtrxs` is still hand-written assembly in the decompilation
(`asm/us/field/nonmatchings/field_model/FieldModelAnimCalcMtrxs.s`). Read on the GTE operations:

- per bone, an 8-byte record at `animation->data + 4`: flags (bit 0/1/2: X/Y/Z rotation animated, bit 4/5/6:
  X/Y/Z translation animated), three rotation bytes (an angle, or a track index when animated), three translation
  indices (`0xFF`: none; animated: track, otherwise: static translation);
- angles are bytes (256 steps per turn) through `g_FieldSinCosTable`: high half cos, low half sin
  (angle 0 gives the identity);
- `R_bone = R_parent · Ry · Rx · Rz`, `t_bone = R_parent · (tx, ty, length + tz) + t_parent`.

`outils/ff7_3d/modele.py` reproduces it in floating point and is tested on Cloud: standing, 126 world units
tall, feet on the ground, legs moving between walk frames 0 and 15.

### Open point: standing the model in the world

The skeleton stands in the GTE's frame (y down: the hip is at `y = -412` before scaling). Read literally, the root
of `FieldModelAnimCalcMtrxs` (called with the field camera and the scratch flag `3`, `HandleKawaiDataInModel`)
only turns the model around z by the entity's direction and flips its third column, which would leave Cloud
lying on the floor. The workshop therefore stands him with an explicit model-to-world change of axes
(`MODELE_VERS_MONDE`: x stays, y goes to -z, z goes to y), checked on the rendered pictures
(`sortie/<field>/personnage.png`) and on the tests. Where the engine does the equivalent step is not found yet.

Also to check on the console: handedness (is Cloud mirrored? his pauldron is on his left shoulder).

## What the package carries and what the 3DS does

- The workshop bakes every frame of the three animations: world-space vertices with the feet at the origin,
  looking towards `-y` (direction 0); triangles with their PS1 colours. Cloud: 298 vertices, about 170 KB.
- The 3DS turns the frame around z towards the step, adds the feet position on the walkmesh, projects the
  ~300 vertices with the field camera on the CPU (like `placer_temoin` did) and draws the triangles with
  `source/modele.v.pica`, the same projection, depth substrate and stereo as the relief. The depth test runs
  against the occlusion cards, so he passes behind layer-2 tiles where the PS1 did.
- The PS1 sorting rule, polygon by polygon: the workshop marks the two triangles of a PS1 quad (`moities`, the
  last byte of each triangle record, 1 then 2), and the 3DS gives every polygon one flat depth, its ordering-table
  slot (`FieldModel*AddPrim`: a quad's four depths `>> 4`, a triangle's three through `AVSZ3`), `4 x slot + 2` so
  that a tie goes to the tile, as on the PS1 where the background enters the table first (`port3ds/README.md`).
- Cost: the bottom screen shows the CPU time of the pose ("pose de Cloud"), to compare with the frame time.
- Speed: about 3 world units per frame walking, 6 running (B); half an animation frame per 60 Hz frame (the PS1
  field plays one per 30 Hz frame).

## Not yet

- Face textures (eyes and mouth: texture mode 0 from `FIELD.TDB` and `KawaiLoadEyesMouthTexToVram`): the
  textured face polygons are drawn with their vertex colours for now.
- Lighting (`KawaiLightingApplyToModel` with the field's three lights from the BSX): raw PS1 colours for now.
- The non-party models of the field (BSX: Jessie, Biggs, Wedge, the guards on `MD1STIN`).
- In milestone 2 the engine's own `FieldModelAnimCalcMtrxs` should take over; it is still assembly upstream and
  `NOT_IMPLEMENTED` in the PC build, so the C port of this reading may stand in for it (`jalon2-psyz-3ds.md`).
