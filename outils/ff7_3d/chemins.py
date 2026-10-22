"""Où trouver le disque du joueur et où écrire ce que l'atelier génère (jamais dans git)."""
import os

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DISQUE = os.environ.get("FF7_3D_DISQUE", os.path.join(RACINE, "disks", "Final Fantasy VII (USA) (Disc 1).bin"))
SORTIE = os.environ.get("FF7_3D_SORTIE", os.path.join(RACINE, "sortie"))


def sortie(*parties):
    chemin = os.path.join(SORTIE, *parties)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    return chemin
