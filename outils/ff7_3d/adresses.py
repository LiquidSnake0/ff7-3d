"""Inventaire des adresses PS1 écrites en dur dans les sources de ff7-decomp (lecture seule).

Étape 0 du jalon 2 (docs/ff7-3d/jalon2-psyz-3ds.md) : une 3DS ne peut pas placer de mémoire à 0x80010000.
Avant d'écrire la passe qui réécrit ces constantes à la compilation, il faut savoir lesquelles sont des pointeurs.
Ce module lit les sources sans les modifier et classe chaque littéral :

- « pointeur » : précédé d'un transtypage vers un type pointeur, ex. `(u8*)0x801B0000` ;
- « comparaison » : comparé à quelque chose (`<`, `>`, `==`...), souvent une borne de zone mémoire ;
- « masque » : opérande d'un `&`, `|` ou `^` ;
- « calcul » : opérande d'un `+` ou d'un `-` (adresse calculée, relocation des modèles) ;
- « transtypage » : transtypé vers un type sans `*` (souvent un typedef de pointeur de fonction, ou `u32`) ;
- « autre » : tout le reste (initialiseurs de tables, arguments, `#define`), à lire à la main.
"""
import os
import re
from collections import Counter, namedtuple

from . import chemins

# RAM principale (et son miroir non caché) et scratchpad.
LITTERAL = re.compile(r"\b0[xX](80[0-1][0-9A-Fa-f]{5}|[Aa]0[0-1][0-9A-Fa-f]{5}|1[Ff]800[0-3][0-9A-Fa-f]{2})\b")
TRANSTYPAGE = re.compile(r"\(\s*(?:const\s+)?[A-Za-z_][A-Za-z_0-9]*(?:\s+[A-Za-z_][A-Za-z_0-9]*)*\s*\*+\s*\)\s*\(?\s*$")
COMPARAISON = re.compile(r"(?:[<>]=?|[!=]=)\s*\(?\s*$")
COMPARAISON_APRES = re.compile(r"^\s*\)?\s*(?:[<>]=?|[!=]=)")
MASQUE = re.compile(r"(?:(?<![&|])[&|^](?![&|])=?)\s*\(?\s*$")
MASQUE_APRES = re.compile(r"^\s*\)?\s*[&|^](?![&|])")
CALCUL = re.compile(r"(?<![+-])[+-]\s*\(?\s*$")
CALCUL_APRES = re.compile(r"^\s*\)?\s*[+-](?![+-=])")
TRANSTYPAGE_SIMPLE = re.compile(r"\(\s*[A-Za-z_][A-Za-z_0-9]*\s*\)\s*$")

Occurrence = namedtuple("Occurrence", "fichier ligne valeur genre texte")


def sans_commentaires(source):
    """Remplace les commentaires par des espaces, en gardant les retours à la ligne (numéros de ligne intacts)."""
    def blanc(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    return re.sub(r"//[^\n]*|/\*.*?\*/", blanc, source, flags=re.S)


def zone(valeur):
    if 0x1F800000 <= valeur < 0x1F800400:
        return "scratchpad"
    return "ram"


def classer(avant, apres):
    if TRANSTYPAGE.search(avant):
        return "pointeur"
    nu = TRANSTYPAGE_SIMPLE.sub("", avant)
    if nu != avant and not (COMPARAISON.search(nu) or MASQUE.search(nu) or CALCUL.search(nu)):
        return "transtypage"
    avant = nu
    if COMPARAISON.search(avant) or COMPARAISON_APRES.search(apres):
        return "comparaison"
    if MASQUE.search(avant) or MASQUE_APRES.search(apres):
        return "masque"
    if CALCUL.search(avant) or CALCUL_APRES.search(apres):
        return "calcul"
    return "autre"


def analyser_source(source, fichier="<source>"):
    lignes = sans_commentaires(source).split("\n")
    sortie = []
    for n, ligne in enumerate(lignes, 1):
        for m in LITTERAL.finditer(ligne):
            sortie.append(Occurrence(fichier, n, int(m.group(0), 16),
                                     classer(ligne[:m.start()], ligne[m.end():]), ligne.strip()))
    return sortie


def sources(racine=None, dossiers=("src", "include")):
    racine = racine or chemins.RACINE
    for d in dossiers:
        for base, _sous, fichiers in os.walk(os.path.join(racine, d)):
            for f in sorted(fichiers):
                if f.endswith((".c", ".h")):
                    yield os.path.join(base, f)


def inventaire(racine=None, dossiers=("src", "include")):
    racine = racine or chemins.RACINE
    tout = []
    for chemin in sources(racine, dossiers):
        with open(chemin, encoding="utf-8", errors="replace") as f:
            tout += analyser_source(f.read(), os.path.relpath(chemin, racine))
    return tout


def resume(occurrences):
    """Compte par genre et par dossier de premier niveau sous src/ (field, main, battle...)."""
    par_genre = Counter(o.genre for o in occurrences)
    par_dossier = Counter()
    for o in occurrences:
        morceaux = o.fichier.split(os.sep)
        par_dossier[morceaux[1] if morceaux[0] == "src" and len(morceaux) > 2 else morceaux[0]] += 1
    return par_genre, par_dossier
