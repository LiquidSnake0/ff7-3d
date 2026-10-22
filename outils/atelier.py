#!/usr/bin/env python3
"""Atelier ff7-3d : du disque du joueur au paquet .f3d d'un écran, prêt pour la carte SD.

    ~/opt/ff7-3d/venv/bin/python outils/atelier.py MD1STIN
    -> sortie/md1stin/md1stin.f3d (+ fond.png, profondeur.png et rapport.json pour contrôle)

L'étape de profondeur demande l'environnement du modèle (docs/ff7-3d/atelier.md). Rien de ce qui est
produit ne doit entrer dans git : tout va dans sortie/.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ff7_3d import chemins, field, fond, profondeur, relief, reperes  # noqa: E402
from ff7_3d.disque import Disque  # noqa: E402


def lire_etats(texte):
    """« 1=2,2=1 » -> {1: 2, 2: 1} : groupe d'animation -> masque des états visibles (portes, lumières…)."""
    etats = {}
    for morceau in filter(None, (texte or "").split(",")):
        groupe, masque = morceau.split("=")
        etats[int(groupe)] = int(masque, 0)
    return etats


def traiter(nom, pas=4, etats=None):
    nom = nom.upper()
    with Disque(chemins.DISQUE) as d:
        d.verifier()
        champ, mim = field.charger(d, nom)
    compose = fond.composer(champ, mim, etats)
    rp = reperes.calculer(champ, compose)
    rgb = compose.image[..., :3].copy()
    rgb[compose.image[..., 3] == 0] = 0
    disp = profondeur.disparite(rgb)
    z, rapport = profondeur.recaler(disp, rp, champ, compose)
    sol = rp.z_sol[np.isfinite(rp.z_sol)]
    z_conv = float(np.median(sol)) if sol.size else float(np.median(z))
    dossier = nom.lower()
    chemin = chemins.sortie(dossier, f"{dossier}.f3d")
    stats = relief.ecrire(chemin, nom, compose.image, z, compose.origine, champ.camera.zoom, z_conv, pas,
                          relief.cartes_occlusion(champ), relief.masque_occlusion(compose), champ)
    rapport.update(stats)
    rapport.update({"nom": nom, "z_convergence": z_conv, "origine": compose.origine, "zoom": champ.camera.zoom,
                    "groupes": {str(g): e for g, e in fond.groupes(champ).items()}, "etats": etats or {}})
    try:
        from PIL import Image
        Image.fromarray(compose.image).save(chemins.sortie(dossier, "fond.png"))
        lz = np.log(z)
        gris = (255 * (1 - (lz - lz.min()) / max(np.ptp(lz), 1e-9))).astype(np.uint8)
        Image.fromarray(gris).save(chemins.sortie(dossier, "profondeur.png"))
    except ImportError:
        pass
    with open(chemins.sortie(dossier, "rapport.json"), "w") as f:
        json.dump(rapport, f, indent=2)
    return chemin, rapport


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ecrans", nargs="+", help="noms des écrans (FIELD/<NOM>.DAT), par exemple MD1STIN")
    p.add_argument("--pas", type=int, default=4, help="écart de la grille du relief, en pixels (4 par défaut)")
    p.add_argument("--etats", default="", help="variantes visibles : « groupe=masque,… » (aucune par défaut, "
                   "comme le décor de base) ; la liste des groupes d'un écran est dans son rapport.json")
    a = p.parse_args()
    etats = lire_etats(a.etats)
    for nom in a.ecrans:
        chemin, rapport = traiter(nom, a.pas, etats)
        print(f"{nom} -> {chemin} ({rapport['sommets']} sommets, {rapport['triangles']} triangles, "
              f"{rapport['cartes']} cartes d'occlusion, {rapport['octets'] // 1024} Ko, écart médian du sol {100 * rapport['ecart_median_relatif']:.1f} %)")


if __name__ == "__main__":
    main()
