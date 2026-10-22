"""Noms des écrans de terrain par index (fieldMapId), lus dans la table de la décompilation.

src/field/field_fileInfo.c (g_FieldFileInfo) range les 787 écrans dans l'ordre des index du jeu, avec leur nom
en commentaire (« // 116, FIELD/MD1STIN »). On lit ce fichier sans le modifier ; il fait partie du dépôt.
"""
import os
import re

TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "field", "field_fileInfo.c")
_LIGNE = re.compile(r"//\s*(\d+),\s*FIELD/(\w+)")
_cache = None


def noms():
    """-> {index: nom} pour les 787 écrans."""
    global _cache
    if _cache is None:
        with open(TABLE, encoding="utf-8") as f:
            _cache = {int(m.group(1)): m.group(2) for m in map(_LIGNE.search, f) if m}
    return _cache


def nom(index):
    return noms().get(index)
