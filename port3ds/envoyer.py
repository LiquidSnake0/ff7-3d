#!/usr/bin/env python3
"""Envoie le visualiseur et les paquets de relief sur la 3DS par FTP (ftpd, en Wi-Fi).

    python3 port3ds/envoyer.py <ip de la 3DS> [--port 5000] [écran ...]

Sur la 3DS : lancer ftpd, l'écran affiche « ftp://192.168.x.y:5000 ». Le script copie
port3ds/ff7-3d.3dsx et les .f3d de sortie/ (tous, ou seulement les écrans nommés) dans
sdmc:/3ds/ff7-3d/, saute ce qui est déjà là avec la même taille, puis relit les tailles.
"""
import argparse
import ftplib
import glob
import os

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
DISTANT = "/3ds/ff7-3d"


def taille_distante(ftp, chemin):
    try:
        return ftp.size(chemin)
    except ftplib.error_perm:
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ip")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("ecrans", nargs="*", help="noms d'écrans (MD1STIN…) ; tous les .f3d de sortie/ par défaut")
    a = p.parse_args()

    fichiers = [os.path.join(ICI, "ff7-3d.3dsx")]
    if a.ecrans:
        fichiers += [os.path.join(RACINE, "sortie", e.lower(), f"{e.lower()}.f3d") for e in a.ecrans]
    else:
        fichiers += sorted(glob.glob(os.path.join(RACINE, "sortie", "*", "*.f3d")))
    manquants = [f for f in fichiers if not os.path.exists(f)]
    if manquants:
        raise SystemExit("introuvable : " + ", ".join(manquants))

    ftp = ftplib.FTP()
    ftp.connect(a.ip, a.port, timeout=30)
    ftp.login()
    ftp.set_pasv(True)
    for dossier in ("/3ds", DISTANT):
        try:
            ftp.mkd(dossier)
        except ftplib.error_perm:
            pass
    ftp.voidcmd("TYPE I")
    for f in fichiers:
        cible = f"{DISTANT}/{os.path.basename(f)}"
        taille = os.path.getsize(f)
        if taille_distante(ftp, cible) == taille:
            print(f"déjà là : {cible}")
            continue
        with open(f, "rb") as source:
            ftp.storbinary(f"STOR {cible}", source, blocksize=64 * 1024)
        relue = taille_distante(ftp, cible)
        etat = "ok" if relue == taille else f"TAILLE DIFFÉRENTE ({relue} au lieu de {taille})"
        print(f"{cible} : {taille // 1024} Ko, {etat}")
    ftp.quit()


if __name__ == "__main__":
    main()
