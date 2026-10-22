"""Cuisson du relief d'un écran et paquet .f3d lu par la 3DS.

Le vertex shader de la PICA200 ne lit pas de texture : le relief est donc cuit dans les sommets, hors
ligne. Chaque sommet porte sa position écran PS1 (sx, sy), son z caméra (profondeur d'affichage) et ses
coordonnées de texture ; la 3DS refait la projection et la stéréo (port3ds/).

Format .f3d, petit-boutiste, version 1 :
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
"""
import struct

import numpy as np

MAGIE = b"F3D1"
VERSION = 1
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
    yb = h - 1 - ys  # la PICA200 range les lignes du bas vers le haut
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
    # profondeur au sommet : médiane des 4 pixels qui l'entourent (bords pris dans l'image)
    voisins = []
    for dy in (-1, 0):
        for dx in (-1, 0):
            voisins.append(z[np.clip(yy + dy, 0, h - 1), np.clip(xx + dx, 0, l - 1)])
    zs = np.median(np.stack(voisins), axis=0)
    ox, oy = origine
    sommets = np.stack([xx + ox, yy + oy, zs, xx / l, 1.0 - yy / h], axis=-1).reshape(-1, 5).astype(np.float32)
    i = np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)[None, :]
    a, b, c, d = i, i + 1, i + nx, i + nx + 1
    tris = np.stack([a, c, b, b, c, d], axis=-1).reshape(-1).astype(np.uint16)
    return sommets, tris


def ecrire(chemin, nom, image_rgba, z, origine, zoom, z_convergence, pas=4):
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
    return {"sommets": len(sommets), "triangles": len(tris) // 3, "octets": TAILLE_EN_TETE + texture.nbytes
            + sommets.nbytes + tris.nbytes}


def lire_en_tete(chemin):
    with open(chemin, "rb") as f:
        b = f.read(TAILLE_EN_TETE)
    champs = struct.unpack_from("<4sHH16sHHhhHHIfff", b)
    cles = ("magie", "version", "pas", "nom", "tex_l", "tex_h", "ox", "oy", "zoom", "nb_sommets", "nb_indices",
            "z_convergence", "z_min", "z_max")
    d = dict(zip(cles, champs))
    d["nom"] = d["nom"].rstrip(b"\0").decode("ascii")
    return d
