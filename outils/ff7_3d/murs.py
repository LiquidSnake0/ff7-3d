"""Murs et à-pics tirés du walkmesh : des cassures franches entre le sol et ce qui s'en élève.

Le sol praticable est connu exactement (walkmesh). Là où il s'arrête (arête sans voisin, `acces = -1`), trois
choses sont possibles : un mur s'élève, le sol continue (zone décorative non praticable, bord de l'image), ou
le sol tombe (à-pic, bord d'une passerelle). Pour chaque arête bloquée, on compare le modèle de profondeur aux
trois hypothèses géométriques, le long de la verticale montante (mur), de la verticale descendante (à-pic) et
de la normale sortante dans le plan du sol (le sol continue), et on garde celle qui s'en rapproche le plus.

Un mur retenu est extrudé : le quadrilatère vertical dressé sur l'arête, jusqu'à la hauteur où le modèle cesse
d'être d'accord, reçoit la profondeur exacte de la verticale (perspective correcte). Le modèle monoculaire,
lui, prolonge souvent le sol dans le mur en pente douce : on confondait un mur et le sol.
"""
import math

import numpy as np

from . import camera as cam
from . import reperes

PAS = 8                   # unités du monde entre deux échantillons le long d'une hypothèse
NB_PAS = 50               # jusqu'à 400 unités de haut (Cloud fait 126)
SEUIL = math.log(1.3)     # écart relatif toléré entre le modèle et l'hypothèse
HAUTEUR_MIN = 24          # en dessous, ce n'est pas un mur
TOLERANCE_ECRITURE = math.log(1.5)  # on n'écrase le modèle que là où il n'est pas franchement ailleurs


def aretes_bloquees(champ):
    """(A, B, C) par arête sans voisin : A, B ses sommets, C le troisième sommet du triangle (monde)."""
    tri = np.asarray(champ.walkmesh.triangles, dtype=np.float64)
    for i, voisins in enumerate(champ.walkmesh.acces):
        for k in range(3):
            if voisins[k] < 0:
                yield tri[i][k], tri[i][(k + 1) % 3], tri[i][(k + 2) % 3]


def _profil(camera, z, z_sol, origine, depart, direction):
    """Le long de `depart + s · direction` : z prédit, z du modèle, « c'est du sol » (NaN hors image)."""
    h, l = z.shape
    ox, oy = origine
    pts = depart[None, :] + direction[None, :] * (PAS * np.arange(1, NB_PAS + 1))[:, None]
    ecran, zp = cam.projeter(camera, pts)
    px = np.round(ecran[:, 0] - ox).astype(int)
    py = np.round(ecran[:, 1] - oy).astype(int)
    dedans = (px >= 0) & (px < l) & (py >= 0) & (py < h) & (zp > 0)
    zm = np.full(NB_PAS, np.nan)
    sol = np.zeros(NB_PAS, dtype=bool)
    zm[dedans] = z[py[dedans], px[dedans]]
    sol[dedans] = np.isfinite(z_sol[py[dedans], px[dedans]])
    return zp, zm, sol


def _ecart(zp, zm, sol):
    """Écart relatif médian entre le modèle et l'hypothèse, hors sol ; NaN sans échantillon."""
    garde = np.isfinite(zm) & ~sol & (zp > 0)
    if not garde.any():
        return np.nan
    return float(np.median(np.abs(np.log(zm[garde] / zp[garde]))))


def _hauteur(zp, zm, sol):
    """Jusqu'où l'hypothèse tient, en unités du monde : premier échantillon en désaccord (ou sol, ou hors image)."""
    n = 0
    for k in range(NB_PAS):
        if not np.isfinite(zm[k]) or sol[k] or zp[k] <= 0 or abs(math.log(zm[k] / zp[k])) > SEUIL:
            break
        n = k + 1
    return n * PAS


def classer(camera, z, z_sol, origine, A, B, C):
    """Une arête bloquée -> ("mur" | "apic" | "sol" | "aucun", hauteur en unités du monde)."""
    M = (A + B) / 2.0
    e = B - A
    e /= np.linalg.norm(e) + 1e-9
    vers_c = C - M
    sortante = -(vers_c - np.dot(vers_c, e) * e)
    sortante /= np.linalg.norm(sortante) + 1e-9
    haut = np.array([0.0, 0.0, 1.0])
    profils = {"mur": _profil(camera, z, z_sol, origine, M, haut),
               "apic": _profil(camera, z, z_sol, origine, M, -haut),
               "sol": _profil(camera, z, z_sol, origine, M, sortante)}
    ecarts = {nom: _ecart(*p) for nom, p in profils.items()}
    ecarts = {nom: v for nom, v in ecarts.items() if np.isfinite(v)}
    if not ecarts:
        return "aucun", 0
    meilleur = min(ecarts, key=ecarts.get)
    if ecarts[meilleur] > SEUIL:
        return "aucun", 0
    if meilleur in ("mur", "apic"):
        hauteur = _hauteur(*profils[meilleur])
        if hauteur < HAUTEUR_MIN:
            return "aucun", 0
        return meilleur, hauteur
    return "sol", 0


def appliquer(z, champ, compose, rp):
    """Écrit les murs et à-pics dans la profondeur d'affichage ; renvoie (z, bilan, arêtes classées)."""
    z = z.copy()
    h, l = z.shape
    origine = compose.origine
    aretes = []
    bilan = {"murs": 0, "apics": 0, "sol_continue": 0, "aretes_sans_avis": 0, "pixels_murs": 0}
    sol = np.isfinite(rp.z_sol)
    for A, B, C in aretes_bloquees(champ):
        classe, hauteur = classer(champ.camera, z, rp.z_sol, origine, A, B, C)
        aretes.append((A, B, classe, hauteur))
        if classe == "sol":
            bilan["sol_continue"] += 1
            continue
        if classe == "aucun":
            bilan["aretes_sans_avis"] += 1
            continue
        bilan["murs" if classe == "mur" else "apics"] += 1
        signe = 1.0 if classe == "mur" else -1.0
        d = np.array([0.0, 0.0, signe * hauteur])
        quad = [(A, B, B + d), (A, B + d, A + d)]
        zq = reperes.rasteriser(champ.camera, (h, l), origine, quad)
        # on n'écrase pas le sol, ni ce que le modèle place franchement ailleurs (un pilier devant, une porte
        # ouverte sur le fond) ; entre deux murs qui se recouvrent, le plus proche gagne
        with np.errstate(invalid="ignore", divide="ignore"):
            accord = np.isfinite(zq) & ~sol & (np.abs(np.log(z / zq)) < TOLERANCE_ECRITURE)
        bilan["pixels_murs"] += int(accord.sum())
        z[accord] = np.minimum(z[accord], zq[accord]) if classe == "mur" else zq[accord]
    return z, bilan, aretes


def dessiner_controle(compose, camera, aretes):
    """Image de contrôle : le décor avec les arêtes bloquées colorées (rouge mur, bleu à-pic, vert le sol
    continue, jaune sans avis) et, pour un mur ou un à-pic, sa hauteur retenue en magenta."""
    from PIL import Image, ImageDraw
    img = Image.fromarray(compose.image).convert("RGB")
    dr = ImageDraw.Draw(img)
    ox, oy = compose.origine
    couleurs = {"mur": (255, 0, 0), "apic": (0, 128, 255), "sol": (0, 255, 0), "aucun": (255, 255, 0)}
    for A, B, classe, hauteur in aretes:
        e, zc = cam.projeter(camera, np.array([A, B]))
        if (zc <= 0).any():
            continue
        dr.line([(e[0][0] - ox, e[0][1] - oy), (e[1][0] - ox, e[1][1] - oy)], fill=couleurs[classe], width=2)
        if classe in ("mur", "apic"):
            M = (A + B) / 2.0
            d = np.array([0.0, 0.0, hauteur if classe == "mur" else -hauteur])
            e2, _ = cam.projeter(camera, np.array([M, M + d]))
            dr.line([(e2[0][0] - ox, e2[0][1] - oy), (e2[1][0] - ox, e2[1][1] - oy)], fill=(255, 0, 255), width=1)
    return img
