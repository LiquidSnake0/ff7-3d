"""Lecture de l'image disque du joueur : secteurs bruts MODE2/2352 et système de fichiers ISO 9660.

Rien n'est extrait sur le disque dur : les fichiers sont lus à la demande, en mémoire.
"""
import struct

SECTEUR_BRUT = 2352
SECTEUR = 2048
# MODE2 forme 1 : 12 octets de synchro, 4 d'en-tête, 8 de sous-en-tête, puis les 2048 octets utiles.
DEBUT_DONNEES = 24
SERIE_ATTENDUE = "SCUS_941.63"  # Final Fantasy VII (USA) (Disc 1), la seule version de ff7-decomp


class Disque:
    def __init__(self, chemin):
        self.chemin = chemin
        self._f = open(chemin, "rb")
        self._f.seek(0, 2)
        taille = self._f.tell()
        if taille % SECTEUR_BRUT:
            raise ValueError(f"{chemin} : taille {taille} non multiple de {SECTEUR_BRUT}, image MODE2/2352 attendue")
        self.nb_secteurs = taille // SECTEUR_BRUT
        self._racine = self._lire_pvd()

    def fermer(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.fermer()

    def secteur(self, lba):
        self._f.seek(lba * SECTEUR_BRUT + DEBUT_DONNEES)
        return self._f.read(SECTEUR)

    def lire(self, lba, taille):
        morceaux = []
        reste = taille
        while reste > 0:
            bloc = self.secteur(lba)
            morceaux.append(bloc[: min(reste, SECTEUR)])
            reste -= SECTEUR
            lba += 1
        return b"".join(morceaux)

    def _lire_pvd(self):
        pvd = self.secteur(16)
        if pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise ValueError("pas de descripteur de volume ISO 9660 au secteur 16")
        return self._entree(pvd[156:156 + 34])

    @staticmethod
    def _entree(b):
        longueur = b[0]
        lba = struct.unpack_from("<I", b, 2)[0]
        taille = struct.unpack_from("<I", b, 10)[0]
        drapeaux = b[25]
        lnom = b[32]
        nom = b[33:33 + lnom].decode("ascii", "replace")
        return {"lba": lba, "taille": taille, "dossier": bool(drapeaux & 2), "nom": nom, "longueur": longueur}

    def lister(self, entree=None):
        """Entrées d'un dossier (la racine par défaut), sans « . » ni « .. »."""
        entree = entree or self._racine
        donnees = self.lire(entree["lba"], entree["taille"])
        resultat = []
        i = 0
        while i < len(donnees):
            longueur = donnees[i]
            if longueur == 0:
                # fin du secteur courant : on saute au suivant
                i = (i // SECTEUR + 1) * SECTEUR
                continue
            e = self._entree(donnees[i:i + longueur])
            if e["nom"] not in ("\x00", "\x01"):
                e["nom"] = e["nom"].split(";")[0]
                resultat.append(e)
            i += longueur
        return resultat

    def trouver(self, chemin):
        entree = self._racine
        for partie in chemin.strip("/").upper().split("/"):
            suivant = next((e for e in self.lister(entree) if e["nom"].upper() == partie), None)
            if suivant is None:
                raise FileNotFoundError(chemin)
            entree = suivant
        return entree

    def fichier(self, chemin):
        e = self.trouver(chemin)
        return self.lire(e["lba"], e["taille"])

    def numero_de_serie(self):
        cnf = self.fichier("SYSTEM.CNF").decode("ascii", "replace")
        for ligne in cnf.splitlines():
            if ligne.upper().startswith("BOOT"):
                return ligne.split("\\")[-1].split(";")[0].strip()
        return None

    def verifier(self):
        """Refuse tout autre disque que le disque 1 US, le seul que suit ff7-decomp."""
        serie = self.numero_de_serie()
        if serie != SERIE_ATTENDUE:
            raise ValueError(f"disque {serie!r} : ff7-3d demande Final Fantasy VII (USA) (Disc 1), {SERIE_ATTENDUE}")
        return serie
