"""Écran de terrain (field) PS1 : sections du DAT décompressé.

Les structures viennent de la décompilation (src/field/field_private.h, include/game.h,
src/field/field_bg.c), lues sans être modifiées. Numérotation des couches : celle de Makou Reactor,
1 à 4 (dans la décompilation, `layer2Depth` est la profondeur de la couche 3 et `layer3Depth` celle
de la couche 4).
"""
import struct
from dataclasses import dataclass, field as champ

# Le DAT est chargé à FIELD_DAT_HEADER = 0x80115000 - sizeof(FieldDatHeader) : ses pointeurs sont
# des adresses PS1 absolues, qu'on ramène à des décalages dans le fichier.
BASE_DAT = 0x80115000 - 0x1C
SECTIONS = ("scripts", "walkmesh", "tilemap", "camera", "triggers", "encounters", "modeles")

FIN_GROUPE = 0x7FFF
CHANGE_PAGE = 0x7FFE
# Profondeurs de départ des couches 3 et 4 (field_main.c) ; l'opcode BGPDH peut les changer.
PROFONDEUR_COUCHE3 = 4095
PROFONDEUR_COUCHE4 = 1


@dataclass
class Camera:
    axes: list          # matrice 3x3 en virgule fixe 4.12 (ligne par ligne)
    translation: tuple  # t[3] du MATRIX PsyQ
    decalage: tuple     # DVECTOR offset
    zoom: int           # distance de projection du GTE (SetGeomScreen)

    def matrice(self):
        return [[v / 4096.0 for v in ligne] for ligne in self.axes]


@dataclass
class Tuile:
    couche: int        # 1 à 4
    x: int
    y: int
    u: int
    v: int
    clut: int
    tpage: int
    taille: int        # 16 ou 32
    profondeur: int    # ID de l'ordering table (0 = devant, 4095 = fond)
    parametre: int = 0
    etat: int = 0

    @property
    def groupe(self):
        return self.parametre & 0x3F

    @property
    def semi_transparente(self):
        return bool(self.parametre & 0x80)


@dataclass
class Walkmesh:
    triangles: list          # [(x, y, z) * 3] par triangle, coordonnées du monde
    acces: list = champ(default_factory=list)  # voisins par arête, -1 = bloqué


@dataclass
class ChargeurModele:
    """Une entrée de la section « modèles » du DAT (FieldModelLoaderData, include/game.h)."""
    visage: int          # faceId : palette et textures des yeux et de la bouche
    nb_os: int
    nb_parties: int
    nb_animations: int
    pnj: bool            # npcFlag : chargé à l'entrée de l'écran
    global_id: int       # 1 à 9 : personnage de l'équipe, lu dans FIELD/<NOM>.BCX ; 0 : modèle du BSX


@dataclass
class Field:
    nom: str
    sections: dict
    camera: Camera
    walkmesh: Walkmesh
    tuiles: list
    triggers: dict
    modeles: list = champ(default_factory=list)


def _sections(dat):
    pointeurs = struct.unpack_from("<7I", dat, 0)
    decalages = [p - BASE_DAT for p in pointeurs]
    return dict(zip(SECTIONS, decalages))


def lire_camera(dat, debut, fin):
    m = struct.unpack_from("<9h", dat, debut)
    t = struct.unpack_from("<3i", dat, debut + 20)
    ox, oy, zoom = struct.unpack_from("<3h", dat, debut + 32)
    if fin - debut < 0x28:
        raise ValueError("section caméra trop courte")
    return Camera([list(m[0:3]), list(m[3:6]), list(m[6:9])], t, (ox, oy), zoom)


def lire_walkmesh(dat, debut):
    nb = struct.unpack_from("<H", dat, debut)[0]
    p = debut + 4
    triangles = []
    for _ in range(nb):
        sommets = []
        for _ in range(3):
            x, y, z, _res = struct.unpack_from("<4h", dat, p)
            sommets.append((x, y, z))
            p += 8
        triangles.append(sommets)
    acces = [struct.unpack_from("<3h", dat, p + 6 * i) for i in range(nb)]
    return Walkmesh(triangles, acces)


def lire_tuiles(dat, debut):
    """Reproduit le parcours de FieldBackgroundInitPackets : 4 groupes d'enregistrements (type, index, nombre)."""
    l1, pages, l2, l3 = struct.unpack_from("<4I", dat, debut)
    p_rec = debut + 16
    p_l1, p_pages, p_l2, p_l3 = debut + l1, debut + pages, debut + l2, debut + l3

    def enregistrements():
        nonlocal p_rec
        while True:
            typ, index, nombre = struct.unpack_from("<3h", dat, p_rec)
            if typ == FIN_GROUPE:
                p_rec += 2
                return
            yield typ, index, nombre
            p_rec += 6

    def page_suivante():
        nonlocal p_pages
        page = struct.unpack_from("<H", dat, p_pages)[0]
        p_pages += 2
        return page

    # Les enregistrements CHANGE_PAGE sont ajoutés à la même case de l'ordering table que les tuiles
    # qui les précèdent ; addPrim insère en tête, donc le DR_MODE est dessiné AVANT elles : la page
    # s'applique aux tuiles déjà lues, pas aux suivantes.
    tuiles = []
    en_attente = []
    for typ, _index, nombre in enregistrements():
        if typ == CHANGE_PAGE:
            page = page_suivante()
            for t in en_attente:
                t.tpage = page
            en_attente = []
            continue
        for _ in range(nombre):
            x, y, u, v, clut = struct.unpack_from("<hhBBH", dat, p_l1)
            t = Tuile(1, x, y, u, v, clut, 0, 16, 4095)
            tuiles.append(t)
            en_attente.append(t)
            p_l1 += 8

    for typ, _index, nombre in enregistrements():
        for _ in range(nombre):
            x, y, u, v, clut, tpage, prof, param, etat = struct.unpack_from("<hhBBHHHBB", dat, p_l2)
            tuiles.append(Tuile(2, x, y, u, v, clut, tpage, 16, prof, param, etat))
            p_l2 += 14

    for couche, profondeur in ((3, PROFONDEUR_COUCHE3), (4, PROFONDEUR_COUCHE4)):
        en_attente = []
        for typ, _index, nombre in enregistrements():
            if typ == CHANGE_PAGE:
                page = page_suivante()
                for t in en_attente:
                    t.tpage = page
                en_attente = []
                continue
            for _ in range(nombre):
                x, y, u, v, clut, param, etat = struct.unpack_from("<hhBBHBB", dat, p_l3)
                t = Tuile(couche, x, y, u, v, clut, 0, 32, profondeur, param, etat)
                tuiles.append(t)
                en_attente.append(t)
                p_l3 += 10
    return tuiles


def lire_triggers(dat, debut):
    nom = dat[debut:debut + 9].split(b"\0")[0].decode("ascii", "replace")
    (largeur2, hauteur2, largeur3, hauteur3) = struct.unpack_from("<4h", dat, debut + 0x18)
    gauche, haut, droite, bas = struct.unpack_from("<4h", dat, debut + 0x0C)
    return {
        "nom": nom,
        "camera_range": (gauche, haut, droite, bas),
        "anim_couche3": (largeur2, hauteur2),
        "anim_couche4": (largeur3, hauteur3),
    }


def lire_modeles(dat, debut):
    nb = struct.unpack_from("<BBH", dat, debut)[2]
    sortie = []
    for i in range(nb):
        visage, nb_os, nb_parties, nb_anims, _entree, pnj, _charge, gid = struct.unpack_from("<8B", dat, debut + 4 + 8 * i)
        sortie.append(ChargeurModele(visage, nb_os, nb_parties, nb_anims, bool(pnj), gid if gid < 128 else gid - 256))
    return sortie


def lire(dat, nom=""):
    s = _sections(dat)
    camera = lire_camera(dat, s["camera"], s["triggers"])
    walkmesh = lire_walkmesh(dat, s["walkmesh"])
    tuiles = lire_tuiles(dat, s["tilemap"])
    triggers = lire_triggers(dat, s["triggers"])
    return Field(nom or triggers["nom"], s, camera, walkmesh, tuiles, triggers, lire_modeles(dat, s["modeles"]))


def charger(disque, nom):
    """Lit DAT et MIM d'un écran depuis le disque du joueur, décompressés, en mémoire."""
    from . import lzs
    dat = lzs.decompresser(disque.fichier(f"FIELD/{nom}.DAT"))
    mim = lzs.decompresser(disque.fichier(f"FIELD/{nom}.MIM"))
    return lire(dat, nom), mim
