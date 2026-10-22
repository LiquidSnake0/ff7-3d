"""Modèles 3D des écrans de terrain : squelette, parties, animations, depuis le disque du joueur.

Structures lues dans la décompilation sans la modifier (include/game.h : FieldModel, FieldModelBone,
FieldModelPart, FieldModelAnimation, FieldModelPoly* ; src/field/field_model.c : FieldBsxModel,
FieldModelLoadBcx, FieldModelCreatePktsForPart, FieldModelScale*). Le calcul des matrices reproduit
FieldModelAnimCalcMtrxs (assembleur écrit à la main dans l'original, lu dans asm/us/field/nonmatchings) :

    os i : R_i = R_parent · Ry(ry) · Rx(rx) · Rz(rz),  t_i = R_parent · (tx, ty, longueur + tz) + t_parent

Le personnage se tient dans le repère du GTE (y vers le bas : la hanche est à y = -412 avant l'échelle).
La racine qui le pose dans le monde (z vers le haut, celui du walkmesh et de la caméra) est réglée ici
sur ce que montre le rendu (outils/tests, aperçu) : la lecture de la racine dans l'assembleur
(troisième colonne opposée, rotation de l'entité autour de z) ne suffit pas à elle seule à le redresser,
et l'étape qui le fait dans le moteur n'est pas encore identifiée (voir docs/ff7-3d/cloud.md).

Les angles sont des octets (256 pas par tour), lus dans g_FieldSinCosTable : mot haut = cos, mot bas = sin.
Un canal de rotation non animé porte directement l'angle ; un canal animé porte l'index de la piste
(octets[index · nb_images + image]). Les translations sont des s16, animées ou statiques.

Les personnages de l'équipe (Cloud…) viennent d'un BCX (FIELD/CLOUD.BCX…), les autres du BSX de l'écran.
"""
import math
import struct
from dataclasses import dataclass

import numpy as np

from . import lzs

BASE = 0x80000000

# Personnages de l'équipe : globalModelId -> fichier (même ordre que la table du chargeur).
BCX = {1: "CLOUD", 2: "EARITH", 3: "BALLET", 4: "TIFA", 5: "RED", 6: "CID", 7: "YUFI", 8: "KETCY", 9: "VINCENT"}

# Tailles des polygones dans les données (FieldModelPoly*), dans l'ordre où elles se suivent.
GENRES = (("GT4", 24, 4, True, True), ("GT3", 20, 3, True, True), ("FT4", 12, 4, True, False),
          ("FT3", 12, 3, True, False), ("F3", 8, 3, False, False), ("F4", 8, 4, False, False),
          ("G3", 16, 3, False, True), ("G4", 20, 4, False, True))


@dataclass
class Os:
    longueur: int
    parent: int
    a_partie: bool


@dataclass
class Polygone:
    genre: str
    sommets: tuple          # indices dans les sommets de la partie
    couleurs: tuple         # (r, g, b) par sommet (une seule couleur répétée pour les F/FT)
    uv: tuple = ()          # (u, v) par sommet, dans la page de texture
    texture: int = 0        # mot de texture de la partie (mode, profondeur, page, palette)
    drapeaux: int = 0       # octet de textureFlags (bit 4 : semi-transparence ; bits 5-6 : mode de mélange)


@dataclass
class Partie:
    os: int
    sommets: np.ndarray     # (N, 3) en unités du modèle, avant mise à l'échelle
    polygones: list


@dataclass
class Animation:
    nb_images: int
    os: list                # par os : (drapeaux, (rx, ry, rz), (tx, ty, tz)) bruts
    rotations: bytes
    translations: list      # s16
    statiques: list         # s16

    def angle(self, drapeaux, bit, valeur, image):
        if drapeaux & bit:
            return self.rotations[valeur * self.nb_images + image]
        return valeur

    def translation(self, drapeaux, bit, index, image):
        if drapeaux & bit:
            return self.translations[index * self.nb_images + image]
        if index == 0xFF:
            return 0
        return self.statiques[index]


@dataclass
class Modele:
    nom: str
    echelle: int            # 4.12 : 512 = 1/8
    os: list
    parties: list
    animations: list


def _cos_sin(angle):
    a = (angle & 0xFF) * 2.0 * math.pi / 256.0
    return math.cos(a), math.sin(a)


def rotation_yxz(rx, ry, rz):
    cx, sx = _cos_sin(rx)
    cy, sy = _cos_sin(ry)
    cz, sz = _cos_sin(rz)
    ry_ = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx_ = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    rz_ = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return ry_ @ rx_ @ rz_


def _lire_partie(b, p):
    (drapeaux, os_, nb_s, nb_uv, *nb, nb_tex, nb_texturees, o_poly, o_uv, o_tex, o_drap, _taille,
     data, _paquets) = struct.unpack_from("<14B5HII", b, p)
    nombres = dict(zip(("GT4", "GT3", "FT4", "FT3", "F3", "F4", "G3", "G4"), nb[:8]))
    d = data - BASE
    sommets = np.array([struct.unpack_from("<3h", b, d + 4 + 8 * i) for i in range(nb_s)], dtype=np.float64)
    uvs = [struct.unpack_from("<BB", b, d + o_uv + 2 * i) for i in range(nb_uv)]
    textures = [struct.unpack_from("<I", b, d + o_tex + 4 * i)[0] for i in range(nb_tex)]
    drapeaux_tex = b[d + o_drap:d + o_drap + nb_texturees]
    polys = []
    q = d + o_poly
    k = 0
    for genre, taille, n, texture, gouraud in GENRES:
        for _ in range(nombres[genre]):
            idx = tuple(b[q:q + n])
            nb_coul = n if gouraud else 1
            couleurs = tuple(tuple(b[q + 4 + 4 * c:q + 7 + 4 * c]) for c in range(nb_coul))
            if not gouraud:
                couleurs = couleurs * n
            uv = ()
            mot, drap = 0, 0
            if texture:
                o = q + 4 + 4 * nb_coul
                uv = tuple(uvs[i] for i in b[o:o + n])
                drap = drapeaux_tex[k]
                mot = textures[drap & 0xF]
                k += 1
            polys.append(Polygone(genre, idx, couleurs, uv, mot, drap))
            q += taille
    return Partie(os_, sommets, polys)


def _lire_animation(b, p):
    nb_images, nb_os, nb_tr, nb_st, nb_rot, o_tr, o_st, o_rot, data = struct.unpack_from("<HBBBBHHHI", b, p)
    d = data - BASE
    os_ = []
    for i in range(nb_os):
        mot0, mot1 = struct.unpack_from("<II", b, d + 4 + 8 * i)
        os_.append((mot0 & 0xFF, ((mot0 >> 8) & 0xFF, (mot0 >> 16) & 0xFF, mot0 >> 24),
                    (mot1 & 0xFF, (mot1 >> 8) & 0xFF, (mot1 >> 16) & 0xFF)))
    rotations = b[d + o_rot:d + o_rot + nb_rot * nb_images]
    translations = list(struct.unpack_from(f"<{nb_tr * nb_images}h", b, d + o_tr))
    statiques = list(struct.unpack_from(f"<{nb_st}h", b, d + o_st))
    return Animation(nb_images, os_, rotations, translations, statiques)


def lire_bcx(octets, nom=""):
    """Personnage de l'équipe : un FieldModel complet après l'en-tête {taille, décalage de section}."""
    _taille, section = struct.unpack_from("<II", octets, 0)
    (_dr, _kawai, nb_os, nb_parties, nb_anims, _rx, _ry, _rz, _tx, _ty, _tz, _gid, _face, echelle, o_parties,
     o_anims, donnees, _mat) = struct.unpack_from("<BbBBBBBBiiiBBhHHII", octets, section)
    md = donnees - BASE
    os_ = []
    for i in range(nb_os):
        longueur, parent, a_partie = struct.unpack_from("<hbb", octets, md + 4 * i)
        os_.append(Os(longueur, parent, bool(a_partie)))
    parties = [_lire_partie(octets, md + o_parties + 32 * i) for i in range(nb_parties)]
    anims = [_lire_animation(octets, md + o_anims + 16 * i) for i in range(nb_anims)]
    return Modele(nom, echelle, os_, parties, anims)


def charger_bcx(disque, nom):
    return lire_bcx(lzs.decompresser(disque.fichier(f"FIELD/{nom}.BCX")), nom)


def chargeurs(dat, section_modeles):
    """Section « modèles » du DAT : (faceId, os, parties, anims, entrée, npc, chargé, globalModelId) par modèle."""
    nb = struct.unpack_from("<BBH", dat, section_modeles)[2]
    return [struct.unpack_from("<8B", dat, section_modeles + 4 + 8 * i) for i in range(nb)]


# Repère du modèle (y vers le bas, comme le GTE) vers le monde du terrain (z vers le haut) : la tête,
# en -y dans le modèle, monte en +z ; l'avant du modèle (+z) passe en +y.
MODELE_VERS_MONDE = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])


def racine(camera_r, camera_t, position, direction=0):
    """Matrice de la racine d'un personnage : caméra · rotation de l'entité autour de z · passage au monde.

    camera_r : matrice de la caméra en flottant (axes / 4096), camera_t : sa translation ; position : la
    position de l'entité dans le monde ; direction : l'octet Dir de l'entité (256 pas par tour).
    """
    camera_r = np.asarray(camera_r, float)
    r = camera_r @ rotation_yxz(0, 0, direction) @ MODELE_VERS_MONDE
    t = camera_r @ np.asarray(position, float) + np.asarray(camera_t, float)
    return r, t


def matrices(modele, anim, image, racine_r, racine_t):
    """Matrices des os (R 3x3, t 3) pour une image d'animation, sous la racine (racine_r, racine_t)."""
    k = modele.echelle / 4096.0
    a = modele.animations[anim]
    image = image % max(a.nb_images, 1)
    base = (np.asarray(racine_r, float), np.asarray(racine_t, float))
    resultat = []
    for i, os_ in enumerate(modele.os):
        pr, pt = base if os_.parent < 0 else resultat[os_.parent]
        drap, (rx, ry, rz), (ix, iy, iz) = a.os[i]
        ax = a.angle(drap, 1, rx, image)
        ay = a.angle(drap, 2, ry, image)
        az = a.angle(drap, 4, rz, image)
        tx = float(a.translation(drap, 0x10, ix, image))
        ty = float(a.translation(drap, 0x20, iy, image))
        tz = float(os_.longueur) + float(a.translation(drap, 0x40, iz, image))
        r = pr @ rotation_yxz(ax, ay, az)
        t = pr @ (np.array([tx, ty, tz]) * k) + pt
        resultat.append((r, t))
    return resultat


def sommets_monde(modele, mats):
    """-> liste par partie de (N, 3) points dans le repère des matrices."""
    k = modele.echelle / 4096.0
    sortie = []
    for p in modele.parties:
        r, t = mats[p.os]
        sortie.append(p.sommets * k @ r.T + t)
    return sortie


def triangles(polygone):
    """Indices locaux des triangles d'un polygone PS1 (quad en ordre 0 1 2 3 : triangles 0 1 2 et 1 3 2)."""
    if len(polygone.sommets) == 3:
        return [(0, 1, 2)]
    return [(0, 1, 2), (1, 3, 2)]
