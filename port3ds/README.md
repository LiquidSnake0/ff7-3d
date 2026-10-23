# port3ds: the New 3DS viewer

Milestone 1, step 8: one field background drawn as a relief mesh, in stereoscopic 3D with the 3D slider.
The game itself (ff7-decomp through a PsyZ 3DS backend) comes later; this viewer becomes its background renderer.

## What it does

- Lists the `.f3d` packages of `sdmc:/3ds/ff7-3d/` on the bottom screen at start-up (pad and A to choose; Y
  brings the list back), or loads the path given as the first argument.
  A package is generated on your PC from your own disc by `outils/atelier.py`; it is never distributed.
- Draws the relief with citro3d. The vertex shader (`source/relief.v.pica`) is adapted from CTR-3D's model shader:
  `w = z / H`, perspective-correct depth, and the stereo parallax `p = k - kC/z` with `k` set by the 3D slider
  (6 PS1 pixels of total disparity at infinity at full slider; CTR-3D's 12, then 8, were too strong on a still
  background). The near side is softened instead of clamped: `u = 1 - C/z`, `u' = u / (1 + max(-u, 0))`,
  `p = k u'`, so what pops out never exceeds what recedes and there is no hard clamp edge to catch the eye
  (the floor at the bottom of the screen used to flicker at full slider).
- Left eye always, right eye only when the slider is up, like CTR-3D.
- Occlusion of the original game (milestone 1, step 9): after the relief (colour only), one flat card per
  occluding tile is drawn at `z = 4 x ID`, depth only, alpha-tested against the mask of the texels that occlude;
  a red test character then goes through the depth test. Walking it behind the train must hide it exactly where
  the PS1 would.
- The PS1 sorting rule (`src/field/field_kawai_char_model.c`, read, not modified): every polygon of a model goes
  into one ordering-table slot, the average camera depth of its vertices / 4 (a quad: `sum >> 4`; a triangle:
  the GTE's `AVSZ3`, `sum x 341 >> 12`), and the background is added to the table before the models, so at an
  equal slot the tile is drawn on top. The viewer gives every polygon one flat depth, `4 x slot + 2`, tested
  `LEQUAL` against the cards at `4 x ID`: no polygon is ever cut by a card, and a tie goes to the tile.
  A blended texel (STP bit of a semi-transparent tile, `parameter & 0x80`) is not in the mask: it never
  occludes (MD1_1: the lamp glows on the floor, layer 2 at ID 0, used to hide Cloud when he arrived).
- Cloud (package version 4, `docs/ff7-3d/cloud.md`): his model and his standing, walking and running animations,
  baked by the workshop from the player's `CLOUD.BCX`, stand on the field's real walkmesh. The circle pad walks
  him along the screen's right and forward axes projected on the ground (B held: he runs), he turns towards the
  step, a step off the walkmesh is refused, his ~300 vertices are projected by the field camera on the CPU and
  drawn with `source/modele.v.pica` (same projection and stereo as the relief) through the depth test, and the
  view follows him like the field scroll. A package without a character falls back to the red test quad.

- Walking through a field exit (package version 5) loads the target field if its package is on the SD card, and
  stands Cloud where the game puts him; without it, the step is undone and the bottom screen names the field to
  generate (`outils/atelier.py MD1_2`…).
- The convergence follows Cloud: he sits on the screen plane, the background recedes behind him. L / R move that
  plane relative to him; the choice is saved in `sdmc:/3ds/ff7-3d/reglages.txt`.

Controls: the circle pad walks Cloud on the walkmesh (B held: he runs; the view follows him), the D-pad shifts the
view, L / R move the convergence plane relative to Cloud (saved), Y opens the field list, ZR hides the character (the circle pad
then scrolls the view), SELECT toggles the stats on the bottom screen, START quits.

## Build

The build runs in the devkitARM Docker image of the regta port (`regta-r55`), with libctru and citro3d built once
from the sources vendored by regta:

```shell
mkdir -p ~/opt/ff7-3d/3ds && cd ~/opt/ff7-3d/3ds
cp -r ~/Documents/regta/common/libctru ~/Documents/regta/common/citro3d .
docker run --rm -v ~/opt/ff7-3d/3ds:/w regta-r55 bash -lc '
  export DEVKITPRO=/opt/devkitpro DEVKITARM=/opt/devkitpro/devkitARM
  export PATH=$DEVKITARM/bin:/opt/devkitpro/tools/bin:$PATH
  cd /w/libctru && make lib/libctru.a && mkdir -p /w/prefix/libctru && cp -r include lib /w/prefix/libctru/
  cd /w/citro3d && make lib/libcitro3d.a CTRULIB=/w/prefix/libctru
  cp lib/libcitro3d.a /w/prefix/libctru/lib/ && cp -r include/* /w/prefix/libctru/include/'

cd ~/Documents/ff7-3d && port3ds/construire.sh      # -> port3ds/ff7-3d.3dsx
```

## On the console

1. Generate the packages: `~/opt/ff7-3d/venv/bin/python outils/atelier.py MD1STIN --suivre 2` (the station and
   the two platforms it leads to, see `docs/ff7-3d/atelier.md`).
2. Start ftpd on the 3DS, then from the PC: `python3 port3ds/envoyer.py 192.168.x.y MD1STIN MD1_1 MD1_2`
   (copies `ff7-3d.3dsx` and `md1stin.f3d` into `sdmc:/3ds/ff7-3d/`, checks the sizes).
3. Homebrew Launcher, `ff7-3d`.

What to look at, on the real console (an emulator hides the PICA200's traps, CTR-3D docs/3DS_PORT.md):

- the image appears at all (a blank top screen means a shader output was not fully written);
- with the slider down: the station looks exactly like the flat background, no seams between grid cells;
- with the slider up: the platform floor recedes, the train on the right stands in front of the back wall,
  nothing tears at the edge of the train; L / R move the plane that stays sharp on the screen;
- the test character: it walks along the platform and gets smaller as it goes; walking near the train, it is cut
  by the train's tiles where the PS1 would hide Cloud (layer-2 tiles at z 608 to 2176 on `MD1STIN`), along the
  tile shapes, not 16x16 squares; it never leaves the platform;
- the frame time on the bottom screen (the mesh is 32 768 triangles per eye, plus the cards).

Cloud, once the packages carry him (version 5), in this order:

1. he stands on his feet, not lying on the floor, and is about as tall as on the PS1 next to the train;
2. his pauldron is on his left shoulder (on his right: the model is mirrored, `docs/ff7-3d/cloud.md`);
3. pushing the circle pad, he faces the step, his legs move, B makes him run;
4. walking near the train, he passes behind its tiles along their shapes;
5. at the end of the platform he goes through to `MD1_1`, arrives on the floor facing away from the exit and does
   not bounce straight back; the "sorties" line lists where each field leads;
6. the slider up, he stays sharp on the screen plane while the background recedes; L / R, then a restart: the
   setting is kept;
7. the stats: "pose de Cloud" (CPU time of his ~300 vertices) and the frame time, to note for the measures.
