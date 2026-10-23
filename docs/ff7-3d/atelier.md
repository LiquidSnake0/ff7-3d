# The workshop (`outils/`)

Everything here runs on the player's PC, from the player's own disc. Nothing it produces is ever committed:
outputs go to `sortie/` (ignored by git).

## What you need

- Your own image of *Final Fantasy VII (USA) (Disc 1)* (`SCUS-94163`), as `.bin`/`.cue` in `disks/`,
  exactly as for ff7-decomp. Any other disc is refused.
- Python 3 with `numpy` and `pillow` for the reader, the composer and the anchors.
- For the depth step only: a separate virtual environment with CPU PyTorch, the official
  [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) code and the **Small** checkpoint, the only
  one under Apache-2.0:

```shell
python3 -m venv ~/opt/ff7-3d/venv
~/opt/ff7-3d/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
~/opt/ff7-3d/venv/bin/pip install numpy pillow opencv-python-headless
git clone https://github.com/DepthAnything/Depth-Anything-V2.git ~/opt/ff7-3d/dav2
curl -L -o ~/opt/ff7-3d/depth_anything_v2_vits.pth \
  https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/03876f8651c73a60fe4c2c48294e09fcb6838fcf/depth_anything_v2_vits.pth
echo "715fade13be8f229f8a70cc02066f656f2423a59effd0579197bbf57860e1378  $HOME/opt/ff7-3d/depth_anything_v2_vits.pth" | sha256sum -c -
```

Other locations: `FF7_3D_DAV2`, `FF7_3D_POIDS`, `FF7_3D_DISQUE`, `FF7_3D_SORTIE`.

## Pipeline for one field

1. `disque.py`: raw `MODE2/2352` sectors, ISO 9660, serial check.
2. `lzs.py`, `field.py`: the DAT sections (camera, walkmesh, the four tile layers), the MIM.
3. `vram.py`, `fond.py`: the MIM uploaded into an emulated PS1 VRAM, the background composed in ordering-table
   order, with the occlusion depth (OT slot) of every pixel.
4. `camera.py`, `reperes.py`: GTE projection; exact anchors: the walkmesh floor rasterised with a
   perspective-correct depth, and layer-2 tiles at `4 x ID`. Tiles with a tiny ID (1 on `MD1STIN`) are
   "always in front" overlays, not depths: they stay in the occlusion, not in the anchors.
5. `profondeur.py`: Depth Anything V2 Small gives a relative disparity `d`; `1/z = a d + b` is fitted on the
   anchors (weighted, robust); the floor is then taken exactly; each layer-2 tile is shifted onto `4 x ID`
   only when that ID agrees with the model within 30 % (IDs are first a sorting key).
   `murs.py`: where the walkmesh stops (an edge without a neighbour), the model is compared with three
   hypotheses sampled along their own lines (a wall rising vertically, the floor going on, a drop); a wall or a
   drop that the model agrees with (within 30 %, at least 24 units high) is extruded from the edge with the
   exact depth of its vertical, up to the height where the model stops agreeing, never over the floor nor over
   what the model places elsewhere (a pillar in front, an open door). The monocular model tends to carry the
   floor on into the wall as a gentle slope: on pixelated backgrounds a wall and the floor looked alike.
   `sortie/<field>/murs.png` shows the verdict per edge (red wall, blue drop, green the floor goes on, yellow
   no opinion) and the height kept, in magenta.

6. `relief.py`: a 4 px grid; a vertex takes the median depth of its cell, or the nearest one across a depth
   break (more than 15 %), so a foreground silhouette stays sharp; the occlusion cards (one per occluding tile,
   at `4 x ID`) and the A8 mask of the texels that occlude. `atelier.py --etats 1=1,2=1` composes a variant
   (doors, lights: `parameter & 0x3F` groups and their `state` bits, listed in each field's `rapport.json`).

First field, `MD1STIN`: the floor fit has a median relative error of 1.5 % over about 35 000 anchor pixels.
42 layer-2 tiles disagree with their ID by more than 30 % and keep the model's depth.
`MD1_1` and `MD1_2` go through the same pipeline unchanged (floor errors 1.6 % and 0.6 %; `MD1_2` has two
animation groups).

7. `modele.py`, `rendu.py`: the player's character (`FIELD/CLOUD.BCX`) baked frame by frame into the package,
   and a painter's-algorithm preview `personnage.png` (`cloud.md`).
8. `field.py` (`Porte`), `ecrans.py`: the field's exits and the names of their targets, written into the package
   for the 3DS. `atelier.py MD1STIN --suivre 2` also builds every field reachable through at most two exits
   (`MD1STIN MD1_1 MD1_2`, about 7 s for the three packages on a laptop CPU).

## Other tools

- `apercu.py`: a PC preview of the relief's parallax.
- `adresses_ps1.py`: the inventory of the PS1 addresses written in `src/` and `include/` (read only), the step 0
  of milestone 2 (`jalon2-psyz-3ds.md`); details in `sortie/adresses_ps1.tsv`.

## Tests

```shell
cd outils && python3 -m unittest discover -s tests -v
```

The tests that read the disc are skipped when it is missing.
