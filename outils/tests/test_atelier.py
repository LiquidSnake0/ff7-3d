"""Tests de l'atelier. Ceux qui lisent le disque du joueur sont sautés s'il est absent.

    cd outils && python3 -m unittest discover -s tests -v
"""
import os
import struct
import unittest

import numpy as np

from ff7_3d import chemins, field, fond, lzs
from ff7_3d.disque import Disque
from ff7_3d.vram import Vram

DISQUE_PRESENT = os.path.exists(chemins.DISQUE)


class TestLzs(unittest.TestCase):
    def test_litteraux_et_reference(self):
        # « ABC » en littéraux, puis une référence qui recopie 6 octets depuis le début de la sortie.
        # Position dans la fenêtre : 0xFEE (N - F) correspond à l'octet 0 de la sortie.
        pos = 0xFEE
        b1 = pos & 0xFF
        b2 = ((pos >> 4) & 0xF0) | (6 - 3)
        corps = bytes([0b00000111]) + b"ABC" + bytes([b1, b2])
        donnees = struct.pack("<I", len(corps)) + corps
        self.assertEqual(lzs.decompresser(donnees), b"ABCABCABC")

    def test_reference_avant_le_debut_donne_des_zeros(self):
        pos = 0xFEE - 4  # 4 octets avant le début : la fenêtre est initialisée à zéro
        corps = bytes([0b00000000, pos & 0xFF, ((pos >> 4) & 0xF0) | 0])
        donnees = struct.pack("<I", len(corps)) + corps
        self.assertEqual(lzs.decompresser(donnees), b"\0\0\0")


class TestVram(unittest.TestCase):
    def test_texel_8_bits_avec_palette(self):
        v = Vram()
        v.mots[480, 3] = 0x7C1F  # couleur 3 de la palette (0, 480)
        v.mots[0, 512] = 0x0300  # texels (0,0)=0 et (1,0)=3 de la page 8 bits x=512
        tpage = (1 << 7) | 8
        clut = (480 << 6) | 0
        self.assertIsNone(v.texel(tpage, clut, 0, 0))
        self.assertEqual(v.texel(tpage, clut, 1, 0), 0x7C1F)
        rgba, _stp = v.tuile(tpage, clut, 0, 0, 2)
        self.assertEqual(rgba[0, 1].tolist(), [255, 0, 255, 255])
        self.assertEqual(rgba[0, 0, 3], 0)


@unittest.skipUnless(DISQUE_PRESENT, "disque du joueur absent")
class TestMd1stin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Disque(chemins.DISQUE) as d:
            cls.serie = d.verifier()
            cls.entree = d.trouver("FIELD/MD1STIN.DAT")
            cls.champ, cls.mim = field.charger(d, "MD1STIN")

    def test_disque_us(self):
        self.assertEqual(self.serie, "SCUS_941.63")

    def test_meme_secteur_que_la_table_de_la_decompilation(self):
        # g_FieldFileInfo[116] (src/field/field_fileInfo.c) : DAT au secteur 58890, 17330 octets
        self.assertEqual((self.entree["lba"], self.entree["taille"]), (58890, 17330))

    def test_sections(self):
        self.assertEqual(self.champ.nom, "MD1STIN")
        self.assertEqual(self.champ.triggers["nom"], "md1stin")
        self.assertEqual(len(self.champ.walkmesh.triangles), 39)
        self.assertEqual(self.champ.camera.zoom, 386)

    def test_camera_orthonormee(self):
        m = np.array(self.champ.camera.matrice())
        self.assertTrue(np.allclose(m @ m.T, np.eye(3), atol=0.01))

    def test_tuiles(self):
        couches = [t.couche for t in self.champ.tuiles]
        self.assertEqual(couches.count(1), 795)
        self.assertEqual(couches.count(2), 320)
        self.assertTrue(all(t.tpage != 0 for t in self.champ.tuiles if t.couche == 1))

    def test_composition_couvre_le_decor(self):
        r = fond.composer(self.champ, self.mim)
        self.assertEqual(r.image.shape, (512, 512, 4))
        self.assertGreater((r.image[..., 3] > 0).mean(), 0.9)
        self.assertTrue(set(np.unique(r.couche)) <= {0, 1, 2})


if __name__ == "__main__":
    unittest.main()
