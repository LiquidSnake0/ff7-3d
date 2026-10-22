#!/usr/bin/env bash
# Compile le visualiseur 3DS (port3ds/ff7-3d.3dsx) dans l'image Docker devkitARM du portage regta.
#   FF7_3D_CTRULIB : préfixe libctru + citro3d (include/, lib/), par défaut ~/opt/ff7-3d/3ds/prefix/libctru
#   FF7_3D_IMAGE   : image Docker avec devkitARM, picasso et 3dsxtool (regta-r55 par défaut)
set -euo pipefail
ICI=$(cd "$(dirname "$0")" && pwd)
LIBS=${FF7_3D_CTRULIB:-$HOME/opt/ff7-3d/3ds/prefix/libctru}
IMAGE=${FF7_3D_IMAGE:-regta-r55}
[ -f "$LIBS/lib/libctru.a" ] && [ -f "$LIBS/lib/libcitro3d.a" ] || {
	echo "libctru et citro3d introuvables dans $LIBS (voir port3ds/README.md)" >&2
	exit 1
}
docker run --rm -u "$(id -u):$(id -g)" -v "$ICI":/port3ds -v "$LIBS":/libctru:ro "$IMAGE" bash -lc \
	'export DEVKITPRO=/opt/devkitpro DEVKITARM=/opt/devkitpro/devkitARM PATH=/opt/devkitpro/devkitARM/bin:/opt/devkitpro/tools/bin:$PATH; cd /port3ds && make CTRULIB=/libctru "$@"' -- "$@"
ls -la "$ICI/ff7-3d.3dsx"
