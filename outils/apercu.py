#!/usr/bin/env python3
"""Aperçu stéréo d'un paquet .f3d sur PC, pour contrôler un relief avant de l'envoyer sur la 3DS.

    python3 outils/apercu.py sortie/md1stin/md1stin.f3d [--ecart 12] [--anaglyphe]
    -> sortie/<écran>/apercu_cote_a_cote.png (vision parallèle) ou apercu_anaglyphe.png (rouge-cyan)

Même modèle de parallaxe que le shader 3DS (port3ds/source/relief.v.pica, repris de CTR-3D) :
décalage horizontal p = k · (1 - C / z), en pixels, de signe opposé pour chaque œil ; C = z de convergence.
"""
import argparse
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ff7_3d import relief  # noqa: E402


def lire(chemin):
    e = relief.lire_en_tete(chemin)
    l, h = e["tex_l"], e["tex_h"]
    with open(chemin, "rb") as f:
        f.seek(relief.TAILLE_EN_TETE)
        tex = np.frombuffer(f.read(l * h * 2), dtype="<u2")
        sommets = np.frombuffer(f.read(e["nb_sommets"] * 20), dtype="<f4").reshape(-1, 5)
    # détuilage : on refait l'index du tuilage et on inverse la permutation
    ys, xs = np.mgrid[0:h, 0:l]
    yb = h - 1 - ys
    index = ((yb // 8) * (l // 8) + xs // 8) * 64 + relief.morton8(xs % 8, yb % 8)
    image565 = tex[index]
    rgb = np.stack([((image565 >> 11) & 31) * 255 // 31, ((image565 >> 5) & 63) * 255 // 63,
                    (image565 & 31) * 255 // 31], axis=-1).astype(np.uint8)
    pas = e["pas"]
    nx, ny = l // pas + 1, h // pas + 1
    zg = sommets[:, 2].reshape(ny, nx)
    # z par pixel : interpolation bilinéaire de la grille des sommets
    gx = (np.arange(l) + 0.5) / pas
    gy = (np.arange(h) + 0.5) / pas
    x0 = np.clip(np.floor(gx).astype(int), 0, nx - 2)
    y0 = np.clip(np.floor(gy).astype(int), 0, ny - 2)
    fx = (gx - x0)[None, :]
    fy = (gy - y0)[:, None]
    z00 = zg[y0[:, None], x0[None, :]]
    z01 = zg[y0[:, None], x0[None, :] + 1]
    z10 = zg[y0[:, None] + 1, x0[None, :]]
    z11 = zg[y0[:, None] + 1, x0[None, :] + 1]
    z = (z00 * (1 - fx) + z01 * fx) * (1 - fy) + (z10 * (1 - fx) + z11 * fx) * fy
    return e, rgb, z


def oeil(rgb, z, k, convergence):
    """Déplace chaque pixel de p = k · (1 - C/z) ; les plus proches gagnent (tampon de profondeur)."""
    h, l = z.shape
    p = k * (1.0 - convergence / z)
    sortie = np.zeros_like(rgb)
    tampon = np.full((h, l), np.inf)
    xs = np.arange(l)[None, :] + p
    for decalage in (0.0, 0.5):  # deux passes à un demi-pixel pour boucher les fissures
        xi = np.clip(np.round(xs + decalage).astype(int), 0, l - 1)
        ys = np.broadcast_to(np.arange(h)[:, None], (h, l))
        ordre = np.argsort(-z, axis=None)  # du plus loin au plus proche : le dernier écrit gagne
        yy, xx = ys.ravel()[ordre], xi.ravel()[ordre]
        zz = z.ravel()[ordre]
        devant = zz <= tampon[yy, xx]
        sortie[yy[devant], xx[devant]] = rgb.reshape(-1, 3)[ordre][devant]
        tampon[yy[devant], xx[devant]] = zz[devant]
    return sortie


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paquet")
    p.add_argument("--ecart", type=float, default=12.0, help="disparité totale à l'infini, en pixels PS1 (12 comme CTR-3D)")
    p.add_argument("--anaglyphe", action="store_true")
    a = p.parse_args()
    from PIL import Image
    e, rgb, z = lire(a.paquet)
    k = a.ecart / 2
    gauche = oeil(rgb, z, -k, e["z_convergence"])
    droite = oeil(rgb, z, k, e["z_convergence"])
    dossier = os.path.dirname(os.path.abspath(a.paquet))
    if a.anaglyphe:
        img = np.dstack([gauche[..., 0], droite[..., 1], droite[..., 2]])
        chemin = os.path.join(dossier, "apercu_anaglyphe.png")
    else:
        img = np.concatenate([gauche, droite], axis=1)
        chemin = os.path.join(dossier, "apercu_cote_a_cote.png")
    Image.fromarray(img).save(chemin)
    print(chemin)


if __name__ == "__main__":
    main()
