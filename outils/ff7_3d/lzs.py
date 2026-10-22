"""Décompression LZS des fichiers de FF7 (fenêtre de 4096 octets, longueurs de 3 à 18).

Même algorithme que SystemLzsDecompress de la décompilation (src/main/cd.c), réécrit en Python :
un octet d'indicateurs (bit à 1 : octet littéral, bit à 0 : référence sur deux octets).
"""
import struct

N = 4096
F = 18
SEUIL = 2


def decompresser(src):
    taille = struct.unpack_from("<I", src, 0)[0]
    fin = 4 + taille
    i = 4
    dst = bytearray()
    while i < fin:
        drapeaux = src[i]
        i += 1
        for _ in range(8):
            if i >= fin:
                break
            if drapeaux & 1:
                dst.append(src[i])
                i += 1
            else:
                b1, b2 = src[i], src[i + 1]
                i += 2
                pos = b1 | ((b2 & 0xF0) << 4)
                longueur = (b2 & 0x0F) + SEUIL + 1
                n = len(dst)
                debut = n - ((n - (pos - (N - F))) & (N - 1))
                for k in range(longueur):
                    j = debut + k
                    dst.append(dst[j] if j >= 0 else 0)
            drapeaux >>= 1
    return bytes(dst)
