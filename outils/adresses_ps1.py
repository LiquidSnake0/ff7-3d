#!/usr/bin/env python3
"""Inventaire des adresses PS1 écrites en dur dans src/ et include/ (étape 0 du jalon 2).

    python3 outils/adresses_ps1.py              # résumé par genre et par dossier
    python3 outils/adresses_ps1.py --dossier field --genre autre   # le détail

Lecture seule : les sources de ff7-decomp ne sont jamais modifiées. Le détail complet va dans
sortie/adresses_ps1.tsv (fichier, ligne, valeur, genre, ligne de code).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ff7_3d import adresses, chemins  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dossier", help="ne garder qu'un dossier de src/ (field, main, battle...)")
    p.add_argument("--genre", choices=("pointeur", "transtypage", "calcul", "comparaison", "masque", "autre"))
    a = p.parse_args()
    occ = adresses.inventaire()
    if a.dossier:
        occ = [o for o in occ if o.fichier.startswith(os.path.join("src", a.dossier) + os.sep)]
    par_genre, par_dossier = adresses.resume(occ)
    print("%d littéraux d'adresse PS1" % len(occ))
    print("  par genre   : " + ", ".join("%s %d" % kv for kv in par_genre.most_common()))
    print("  par dossier : " + ", ".join("%s %d" % kv for kv in par_dossier.most_common()))
    if a.genre:
        for o in occ:
            if o.genre == a.genre:
                print("%s:%d  0x%08X  %s" % (o.fichier, o.ligne, o.valeur, o.texte))
    os.makedirs(chemins.SORTIE, exist_ok=True)
    tsv = os.path.join(chemins.SORTIE, "adresses_ps1.tsv")
    with open(tsv, "w", encoding="utf-8") as f:
        f.write("fichier\tligne\tvaleur\tzone\tgenre\tcode\n")
        for o in occ:
            f.write("%s\t%d\t0x%08X\t%s\t%s\t%s\n" % (o.fichier, o.ligne, o.valeur, adresses.zone(o.valeur), o.genre,
                                                     o.texte.replace("\t", " ")))
    print("détail : " + os.path.relpath(tsv, chemins.RACINE))


if __name__ == "__main__":
    main()
