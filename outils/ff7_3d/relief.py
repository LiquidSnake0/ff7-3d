"""Cuisson du relief d'un écran et paquet .f3d lu par la 3DS.

Le vertex shader de la PICA200 ne lit pas de texture : le relief est donc cuit dans les sommets, hors
ligne. Chaque sommet porte sa position écran PS1 (sx, sy), son z caméra (profondeur d'affichage) et ses
coordonnées de texture ; la 3DS refait la projection et la stéréo (port3ds/).

Format .f3d, petit-boutiste, version 5 :
    en-tête (64 octets)
        char  magie[4]      "F3D1"
        u16   version       1
        u16   pas           écart de la grille en pixels
        char  nom[16]
        u16   tex_l, tex_h  taille de la texture (puissances de deux, 1024 au plus)
        s16   ox, oy        coordonnée écran PS1 du texel (0, 0)
        u16   zoom          H de la caméra
        u16   nb_sommets
        u32   nb_indices
        f32   z_convergence profondeur conseillée pour le plan de l'écran (médiane du sol)
        f32   z_min, z_max
        octets de bourrage jusqu'à 64
    texture  tex_l x tex_h en RGB565, déjà tuilée pour la PICA200 (blocs 8x8 en ordre de Morton, lignes du bas vers le haut)
    sommets  nb_sommets x (f32 sx, f32 sy, f32 z, f32 u, f32 v)
    indices  nb_indices x u16 (triangles)
    occlusion (version 2)
        u16   nb_cartes
        cartes nb_cartes x (s16 x, s16 y, u8 taille, u8 couche, u16 id) : une carte plate par tuile, à z = 4 · id
        masque tex_l x tex_h en A8 tuilé comme la texture : 255 là où le texel visible vient d'une tuile qui
               occulte (couches 2 à 4), 0 ailleurs

    caméra et walkmesh (version 3)
        s16   matrice[9]    axes de la caméra, virgule fixe 4.12
        s32   translation[3]
        s16   zoom
        u16   nb_triangles
        triangles nb_triangles x 3 x (s16 x, s16 y, s16 z) : le sol praticable, coordonnées du monde (z vers le haut)
        acces nb_triangles x 3 x s16 : voisin par arête, -1 = bloqué

    personnage (version 4), pour le joueur (Cloud au début du jeu)
        char  magie[4]      "PERS"
        u16   nb_sommets    0 : pas de personnage
        u16   nb_triangles
        u8    nb_animations 0 debout, 1 marche, 2 course pour les personnages de l'équipe
        u8, u16 bourrage
        f32   hauteur       en unités du monde
        triangles nb_triangles x (u16 i[3], u8 rgb[3][3], u8 bourrage)
        animations nb_animations x (u16 nb_images, u16 bourrage, nb_images x nb_sommets x f32[3]) :
               sommets dans le repère du monde, pieds à l'origine, regard vers -y (direction 0)

    portes (version 5) : les sorties vers d'autres écrans
        char  magie[4]      "PORT"
        u16   nb_portes
        portes nb_portes x (s16 ligne[2][3], s16 arrivee[2], s16 triangle, char cible[9], u8 direction) :
               franchir la ligne charge le paquet <cible>.f3d (en minuscules) s'il est sur la carte SD

La 3DS dessine d'abord le relief (couleur seule, sans écrire la profondeur), puis les cartes d'occlusion
(profondeur seule, test alpha sur le masque), puis les objets du jeu avec le test de profondeur : un
personnage passe derrière une tuile exactement quand il le faisait sur PS1.
"""
import struct

import numpy as np

MAGIE = b"F3D1"
VERSION = 5
ID_FOND = 4095
DISCONTINUITE = 1.15
TAILLE_EN_TETE = 64


def rgb565(rgba):
    r = rgba[..., 0].astype(np.uint16) >> 3
    g = rgba[..., 1].astype(np.uint16) >> 2
    b = rgba[..., 2].astype(np.uint16) >> 3
    return (r << 11) | (g << 5) | b


def morton8(x, y):
    """Position d'un texel (x, y) dans un bloc 8x8 de la PICA200 (bits entrelacés x0 y0 x1 y1 x2 y2)."""
    return ((x & 1) | ((y & 1) << 1) | ((x & 2) << 1) | ((y & 2) << 2) | ((x & 4) << 2) | ((y & 4) << 3))


def tuiler(image):
    """Image H x W (ligne 0 en haut) -> tableau 1D dans l'ordre mémoire de la PICA200."""
    h, l = image.shape[:2]
    if h % 8 or l % 8:
        raise ValueError("la texture doit être un multiple de 8")
    ys, xs = np.mgrid[0:h, 0:l]
    yb = ys  # avec t = 1 - y/h côté sommets, la ligne 0 de l'image va en tête de la mémoire (essai console du 23.10.2026)
    index = ((yb // 8) * (l // 8) + xs // 8) * 64 + morton8(xs % 8, yb % 8)
    sortie = np.empty(h * l, dtype=image.dtype)
    sortie[index.ravel()] = image.reshape(h * l, *image.shape[2:]) if image.ndim > 2 else image.ravel()
    return sortie


def grille(z, origine, pas=4):
    """Sommets et triangles d'une grille régulière posée sur la profondeur d'affichage."""
    h, l = z.shape
    gy = np.arange(0, h + 1, pas)
    gx = np.arange(0, l + 1, pas)
    nx, ny = len(gx), len(gy)
    if nx * ny > 65535:
        raise ValueError("trop de sommets pour des indices sur 16 bits : augmenter le pas")
    yy, xx = np.meshgrid(gy, gx, indexing="ij")
    # profondeur au sommet : médiane des pixels de la maille qui l'entoure ; sur une discontinuité (écart de
    # plus de 15 %), on prend le plus proche, pour que la silhouette d'un objet au premier plan reste nette
    # au lieu de s'étirer vers le fond (le « rideau » est alors porté par le fond, moins visible)
    voisins = []
    demi = max(pas // 2, 1)
    for dy in range(-demi, demi):
        for dx in range(-demi, demi):
            voisins.append(z[np.clip(yy + dy, 0, h - 1), np.clip(xx + dx, 0, l - 1)])
    voisins = np.stack(voisins)
    zs = np.median(voisins, axis=0)
    zmin, zmax = voisins.min(axis=0), voisins.max(axis=0)
    rupture = zmax > zmin * DISCONTINUITE
    zs = np.where(rupture, zmin, zs)
    ox, oy = origine
    sommets = np.stack([xx + ox, yy + oy, zs, xx / l, 1.0 - yy / h], axis=-1).reshape(-1, 5).astype(np.float32)
    i = np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)[None, :]
    a, b, c, d = i, i + 1, i + nx, i + nx + 1
    tris = np.stack([a, c, b, b, c, d], axis=-1).reshape(-1).astype(np.uint16)
    return sommets, tris


def cartes_occlusion(champ):
    """Tuiles qui occultent : couche 2 (ID par tuile), couches 3 et 4 quand elles ne sont pas au fond."""
    cartes = []
    for t in champ.tuiles:
        if t.couche == 1 or t.profondeur >= ID_FOND - 15:
            continue
        cartes.append((t.x, t.y, t.taille, t.couche, max(t.profondeur, 1)))
    return cartes


def masque_occlusion(fond_compose):
    m = (fond_compose.couche >= 2) & (fond_compose.profondeur_id < ID_FOND - 15)
    return np.where(m, 255, 0).astype(np.uint8)


def ecrire_personnage(f, cuisson):
    if cuisson is None:
        f.write(struct.pack("<4sHHBBHf", b"PERS", 0, 0, 0, 0, 0, 0.0))
        return
    f.write(struct.pack("<4sHHBBHf", b"PERS", cuisson.nb_sommets, len(cuisson.triangles), len(cuisson.animations),
                        0, 0, cuisson.hauteur))
    for i0, i1, i2, c0, c1, c2 in cuisson.triangles:
        f.write(struct.pack("<3H9Bx", i0, i1, i2, *c0, *c1, *c2))
    for images in cuisson.animations:
        f.write(struct.pack("<HH", len(images), 0))
        f.write(np.ascontiguousarray(images, dtype="<f4").tobytes())


def ecrire_portes(f, champ):
    from . import ecrans
    portes = []
    for p in (champ.portes if champ is not None else []):
        cible = ecrans.nom(p.index_cible)
        if cible:
            portes.append((p, cible))
    f.write(struct.pack("<4sH", b"PORT", len(portes)))
    for p, cible in portes:
        (x1, y1, z1), (x2, y2, z2) = p.ligne
        f.write(struct.pack("<6h2hh9sB", x1, y1, z1, x2, y2, z2, p.arrivee[0], p.arrivee[1], p.triangle,
                            cible.encode("ascii")[:8], p.direction))


def ecrire(chemin, nom, image_rgba, z, origine, zoom, z_convergence, pas=4, cartes=(), masque=None, champ=None,
           personnage=None):
    h, l = z.shape
    for n in (h, l):
        if n & (n - 1) or n > 1024 or n < 8:
            raise ValueError(f"taille de texture {l}x{h} : puissances de deux de 8 à 1024 attendues")
    sommets, tris = grille(z, origine, pas)
    texture = tuiler(rgb565(image_rgba))
    en_tete = struct.pack("<4sHH16sHHhhHHIfff", MAGIE, VERSION, pas, nom.encode("ascii")[:16],
                          l, h, origine[0], origine[1], zoom, len(sommets), len(tris),
                          float(z_convergence), float(z.min()), float(z.max()))
    en_tete = en_tete.ljust(TAILLE_EN_TETE, b"\0")
    with open(chemin, "wb") as f:
        f.write(en_tete)
        f.write(texture.astype("<u2").tobytes())
        f.write(sommets.astype("<f4").tobytes())
        f.write(tris.astype("<u2").tobytes())
        f.write(struct.pack("<H", len(cartes)))
        for x, y, taille, couche, ident in cartes:
            f.write(struct.pack("<hhBBH", x, y, taille, couche, ident))
        if masque is None:
            masque = np.zeros((h, l), dtype=np.uint8)
        f.write(tuiler(masque).tobytes())
        if champ is None:
            f.write(struct.pack("<9h3ihH", *([0] * 9), 0, 0, 0, zoom, 0))
        else:
            cam = champ.camera
            m = [v for ligne in cam.axes for v in ligne]
            f.write(struct.pack("<9h3ihH", *m, *cam.translation, cam.zoom, len(champ.walkmesh.triangles)))
            for tri in champ.walkmesh.triangles:
                for x, y, zz in tri:
                    f.write(struct.pack("<3h", x, y, zz))
            for acces in champ.walkmesh.acces:
                f.write(struct.pack("<3h", *acces))
        ecrire_personnage(f, personnage)
        ecrire_portes(f, champ)
        octets = f.tell()
    return {"sommets": len(sommets), "triangles": len(tris) // 3, "cartes": len(cartes), "octets": octets}


def lire_en_tete(chemin):
    with open(chemin, "rb") as f:
        b = f.read(TAILLE_EN_TETE)
    champs = struct.unpack_from("<4sHH16sHHhhHHIfff", b)
    cles = ("magie", "version", "pas", "nom", "tex_l", "tex_h", "ox", "oy", "zoom", "nb_sommets", "nb_indices",
            "z_convergence", "z_min", "z_max")
    d = dict(zip(cles, champs))
    d["nom"] = d["nom"].rstrip(b"\0").decode("ascii")
    return d
