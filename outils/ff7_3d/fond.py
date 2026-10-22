"""Composition du décor d'un écran, dans l'ordre exact de l'ordering table de la PS1.

L'OT est parcourue de la case 4095 (le fond) vers la case 0 (le premier plan) ; dans une même case,
addPrim insère en tête, donc la dernière primitive ajoutée est dessinée la première. On garde, pour
chaque pixel, l'ID de la tuile visible : c'est la profondeur d'occlusion du jeu original.
"""
from dataclasses import dataclass
import numpy as np

from .vram import Vram


@dataclass
class Fond:
    image: np.ndarray       # H x W x 4, RGBA (alpha 0 = aucun texel)
    profondeur_id: np.ndarray  # H x W, uint16 : case de l'OT du texel visible (4095 = fond, 65535 = vide)
    couche: np.ndarray      # H x W, uint8 : couche du texel visible (0 = vide)
    origine: tuple          # coordonnées écran (x, y) du pixel (0, 0)


def bornes(tuiles):
    x0 = min(t.x for t in tuiles)
    y0 = min(t.y for t in tuiles)
    x1 = max(t.x + t.taille for t in tuiles)
    y1 = max(t.y + t.taille for t in tuiles)
    return x0, y0, x1, y1


def visible(tuile, visibilite):
    if tuile.groupe == 0:
        return True
    return bool(visibilite.get(tuile.groupe, 0) & tuile.etat)


def _melanger(dst, src, abr):
    d = dst.astype(np.int32)
    s = src.astype(np.int32)
    if abr == 0:
        r = (d + s) // 2
    elif abr == 1:
        r = d + s
    elif abr == 2:
        r = d - s
    else:
        r = d + s // 4
    return np.clip(r, 0, 255).astype(np.uint8)


def composer(champ, mim, visibilite=None, couches=(1, 2, 3, 4)):
    visibilite = visibilite or {}
    vram = Vram()
    vram.charger_mim(mim)
    tuiles = [t for t in champ.tuiles if t.couche in couches and visible(t, visibilite)]
    x0, y0, x1, y1 = bornes(champ.tuiles)
    l, h = x1 - x0, y1 - y0
    image = np.zeros((h, l, 4), dtype=np.uint8)
    prof = np.full((h, l), 65535, dtype=np.uint16)
    couche = np.zeros((h, l), dtype=np.uint8)

    # ordre de dessin : profondeur décroissante ; à profondeur égale, ordre d'insertion inversé
    ordre = sorted(enumerate(tuiles), key=lambda it: (-it[1].profondeur, -it[0]))
    for _i, t in ordre:
        rgba, stp = vram.tuile(t.tpage, t.clut, t.u, t.v, t.taille)
        px, py = t.x - x0, t.y - y0
        zone = image[py:py + t.taille, px:px + t.taille]
        opaque = rgba[..., 3] > 0
        if t.semi_transparente:
            abr = (t.tpage >> 5) & 3
            melange = opaque & stp
            plein = opaque & ~stp
            zone[melange, :3] = _melanger(zone[melange, :3], rgba[melange, :3], abr)
            zone[melange, 3] = 255
            zone[plein] = rgba[plein]
        else:
            zone[opaque] = rgba[opaque]
        prof[py:py + t.taille, px:px + t.taille][opaque] = t.profondeur
        couche[py:py + t.taille, px:px + t.taille][opaque] = t.couche
    return Fond(image, prof, couche, (x0, y0))


def groupes(champ):
    """Groupes d'animation (portes, lumières…) et leurs bits d'état : chaque variante est une autre image."""
    resultat = {}
    for t in champ.tuiles:
        if t.groupe:
            resultat.setdefault(t.groupe, set()).add(t.etat)
    return {g: sorted(e) for g, e in sorted(resultat.items())}
