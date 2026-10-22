"""VRAM PS1 émulée (1024x512 mots de 16 bits) et échantillonnage des textures comme le GPU.

Le MIM d'un écran est une suite de blocs (taille, x, y, largeur, hauteur) copiés tels quels en VRAM :
d'abord les palettes, puis les pages d'image. Le décor se décode ensuite tuile par tuile avec la
page de texture (tpage) et la palette (clut) de chaque tuile, exactement comme le GPU de la PS1.
"""
import struct
import numpy as np

LARGEUR = 1024
HAUTEUR = 512


class Vram:
    def __init__(self):
        self.mots = np.zeros((HAUTEUR, LARGEUR), dtype=np.uint16)

    def charger_mim(self, mim):
        p = 0
        blocs = []
        while p + 12 <= len(mim):
            taille, x, y, l, h = struct.unpack_from("<IHHHH", mim, p)
            if taille == 0:
                break
            donnees = np.frombuffer(mim, dtype="<u2", count=l * h, offset=p + 12).reshape(h, l)
            self.mots[y:y + h, x:x + l] = donnees
            blocs.append((x, y, l, h))
            p += taille
        return blocs

    def texel(self, tpage, clut, u, v):
        """Couleur 15 bits (avec le bit STP) d'un texel, ou None si transparent (0x0000)."""
        base_x = (tpage & 0xF) * 64
        base_y = ((tpage >> 4) & 1) * 256
        mode = (tpage >> 7) & 3
        y = (base_y + v) & 511
        if mode == 0:  # 4 bits
            mot = int(self.mots[y, (base_x + u // 4) & 1023])
            index = (mot >> ((u & 3) * 4)) & 0xF
        elif mode == 1:  # 8 bits
            mot = int(self.mots[y, (base_x + u // 2) & 1023])
            index = (mot >> ((u & 1) * 8)) & 0xFF
        else:  # 15 bits direct
            c = int(self.mots[y, (base_x + u) & 1023])
            return None if c == 0 else c
        cx = (clut & 0x3F) * 16
        cy = (clut >> 6) & 0x1FF
        c = int(self.mots[cy, (cx + index) & 1023])
        return None if c == 0 else c

    def tuile(self, tpage, clut, u0, v0, taille):
        """Bloc RGBA (taille x taille x 4) d'une tuile, alpha 0 là où le texel est transparent,
        et le masque STP (bit 15) pour la semi-transparence."""
        base_x = (tpage & 0xF) * 64
        base_y = ((tpage >> 4) & 1) * 256
        mode = (tpage >> 7) & 3
        us = (u0 + np.arange(taille)) & 255
        vs = ((base_y + v0 + np.arange(taille)) & 511)[:, None]
        if mode == 0:
            mots = self.mots[vs, (base_x + us // 4) & 1023].astype(np.uint32)
            index = (mots >> ((us & 3) * 4)) & 0xF
        elif mode == 1:
            mots = self.mots[vs, (base_x + us // 2) & 1023].astype(np.uint32)
            index = (mots >> ((us & 1) * 8)) & 0xFF
        if mode in (0, 1):
            cx = (clut & 0x3F) * 16
            cy = (clut >> 6) & 0x1FF
            couleurs = self.mots[cy, (cx + index) & 1023].astype(np.uint32)
        else:
            couleurs = self.mots[vs, (base_x + us) & 1023].astype(np.uint32)
        return couleurs_vers_rgba(couleurs)


def couleurs_vers_rgba(c):
    """Couleurs 15 bits PS1 (tableau) -> RGBA uint8 ; alpha 0 pour 0x0000, et le bit STP à part."""
    r = (c & 31) * 255 // 31
    g = ((c >> 5) & 31) * 255 // 31
    b = ((c >> 10) & 31) * 255 // 31
    a = np.where(c == 0, 0, 255)
    rgba = np.stack([r, g, b, a], axis=-1).astype(np.uint8)
    stp = (c >> 15).astype(bool)
    return rgba, stp
