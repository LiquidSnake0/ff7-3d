"""Repères de profondeur exacts tirés des données du jeu, et carte de profondeur d'occlusion.

- Sol : chaque triangle du walkmesh projeté par la caméra, rastérisé avec un z correct en perspective
  (1/z est linéaire dans l'écran).
- Couche 2 : chaque texel visible d'une tuile de couche 2 est à z = 4 · ID (une carte plate par tuile).
- Couches 3 et 4 : une seule profondeur par couche.
- Couche 1 : aucune information, c'est le fond (ID 4095).
"""
from dataclasses import dataclass
import numpy as np

from . import camera as cam

ID_FOND = 4095


@dataclass
class Reperes:
    z_sol: np.ndarray        # H x W, z caméra du sol (NaN hors walkmesh)
    z_tuiles: np.ndarray     # H x W, z des texels de couche 2 (NaN ailleurs)
    z_occlusion: np.ndarray  # H x W, z de l'ordering table (inf pour le fond)
    poids: np.ndarray        # H x W, confiance du repère (0 = aucun)


def rasteriser_sol(champ, forme, origine):
    h, l = forme
    ox, oy = origine
    z_sol = np.full((h, l), np.nan)
    pts = np.array([v for tri in champ.walkmesh.triangles for v in tri], dtype=np.float64)
    ecran, z = cam.projeter(champ.camera, pts)
    ys, xs = np.mgrid[0:h, 0:l]
    px = xs + ox + 0.5
    py = ys + oy + 0.5
    for i in range(0, len(pts), 3):
        a, b, c = ecran[i], ecran[i + 1], ecran[i + 2]
        za, zb, zc = z[i], z[i + 1], z[i + 2]
        if min(za, zb, zc) <= 0:
            continue
        x0 = int(max(np.floor(min(a[0], b[0], c[0]) - ox), 0))
        x1 = int(min(np.ceil(max(a[0], b[0], c[0]) - ox) + 1, l))
        y0 = int(max(np.floor(min(a[1], b[1], c[1]) - oy), 0))
        y1 = int(min(np.ceil(max(a[1], b[1], c[1]) - oy) + 1, h))
        if x0 >= x1 or y0 >= y1:
            continue
        qx = px[y0:y1, x0:x1]
        qy = py[y0:y1, x0:x1]
        aire = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(aire) < 1e-9:
            continue
        w0 = ((b[0] - qx) * (c[1] - qy) - (b[1] - qy) * (c[0] - qx)) / aire
        w1 = ((c[0] - qx) * (a[1] - qy) - (c[1] - qy) * (a[0] - qx)) / aire
        w2 = 1.0 - w0 - w1
        dedans = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        inv_z = w0 / za + w1 / zb + w2 / zc
        zone = z_sol[y0:y1, x0:x1]
        valeur = 1.0 / inv_z
        # en cas de recouvrement, le plus proche gagne
        remplacer = dedans & (np.isnan(zone) | (valeur < zone))
        zone[remplacer] = valeur[remplacer]
    return z_sol


def calculer(champ, fond_compose):
    h, l = fond_compose.profondeur_id.shape
    z_sol = rasteriser_sol(champ, (h, l), fond_compose.origine)

    ids = fond_compose.profondeur_id.astype(np.float64)
    z_occ = np.where(ids >= ID_FOND, np.inf, cam.id_vers_z(ids))
    z_occ[fond_compose.couche == 0] = np.inf

    couche2 = (fond_compose.couche == 2) & (fond_compose.profondeur_id < ID_FOND - 16)
    z_tuiles = np.where(couche2, cam.id_vers_z(ids), np.nan)

    # Le sol n'est un repère que là où il est visible : pas derrière une tuile de couche 2 plus proche.
    sol_visible = ~np.isnan(z_sol) & ~(couche2 & (z_tuiles < z_sol))
    poids = np.zeros((h, l))
    poids[sol_visible] = 1.0
    poids[couche2] = np.maximum(poids[couche2], 0.5)  # une carte plate par tuile 16x16 : moins précis
    z_sol = np.where(sol_visible, z_sol, np.nan)
    return Reperes(z_sol, z_tuiles, z_occ, poids)
