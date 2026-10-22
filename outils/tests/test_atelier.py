"""Tests de l'atelier. Ceux qui lisent le disque du joueur sont sautés s'il est absent.

    cd outils && python3 -m unittest discover -s tests -v
"""
import os
import struct
import unittest

import numpy as np

import tempfile

from ff7_3d import camera, chemins, field, fond, lzs, profondeur, relief, reperes
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


class TestRecalage(unittest.TestCase):
    def test_ajuste_une_disparite_affine_en_1_sur_z(self):
        rng = np.random.default_rng(7)
        z = rng.uniform(300, 2400, (40, 40))
        d = (1.0 / z - 0.0003) / 0.0011
        poids = np.ones_like(z)
        aberrants = rng.random(z.shape) < 0.05
        z_reperes = np.where(aberrants, z * 3, z)
        a, b, ecart = profondeur.ajuster(d, z_reperes, poids)
        self.assertAlmostEqual(a, 0.0011, places=6)
        self.assertAlmostEqual(b, 0.0003, places=6)
        self.assertLess(ecart, 0.01)


class TestVariantes(unittest.TestCase):
    @unittest.skipUnless(DISQUE_PRESENT, "disque du joueur absent")
    def test_md1_2_a_des_groupes_et_ils_s_affichent_sur_demande(self):
        with Disque(chemins.DISQUE) as d:
            champ, mim = field.charger(d, "MD1_2")
        g = fond.groupes(champ)
        self.assertEqual(g, {1: [1, 2, 4, 8], 2: [1]})
        base = fond.composer(champ, mim)
        allume = fond.composer(champ, mim, {1: 1, 2: 1})
        self.assertFalse(np.array_equal(base.image, allume.image))


class TestRelief(unittest.TestCase):
    def test_tuilage_pica200(self):
        img = np.arange(16 * 16, dtype=np.uint16).reshape(16, 16)
        t = relief.tuiler(img)
        # le premier texel en mémoire est le coin en bas à gauche, le second son voisin de droite,
        # le troisième celui du dessus (ordre de Morton), et le bloc suivant commence 8 colonnes plus loin
        self.assertEqual(t[0], img[15, 0])
        self.assertEqual(t[1], img[15, 1])
        self.assertEqual(t[2], img[14, 0])
        self.assertEqual(t[64], img[15, 8])
        self.assertEqual(sorted(t.tolist()), sorted(img.ravel().tolist()))

    def test_grille_et_paquet(self):
        z = np.full((64, 64), 1000.0, dtype=np.float32)
        z[:, 32:] = 2000.0
        sommets, tris = relief.grille(z, (-32, -32), pas=8)
        self.assertEqual(len(sommets), 9 * 9)
        self.assertEqual(len(tris), 8 * 8 * 6)
        self.assertEqual(sommets[0, :2].tolist(), [-32.0, -32.0])
        # sur la rupture (colonne 32 : 1000 à gauche, 2000 à droite), le sommet prend le plus proche
        self.assertEqual(float(sommets[4, 2]), 1000.0)
        self.assertEqual(float(sommets[5, 2]), 2000.0)
        self.assertAlmostEqual(float(sommets[0, 4]), 1.0)  # v = 1 en haut (texture rangée du bas vers le haut)
        image = np.zeros((64, 64, 4), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as d:
            chemin = os.path.join(d, "t.f3d")
            stats = relief.ecrire(chemin, "TEST", image, z, (-32, -32), 386, 1200.0, pas=8,
                                  cartes=[(0, 0, 16, 2, 300)], masque=np.full((64, 64), 255, np.uint8))
            e = relief.lire_en_tete(chemin)
            self.assertEqual(os.path.getsize(chemin), stats["octets"])
            attendu = 64 + 64 * 64 * 2 + 81 * 20 + 8 * 8 * 6 * 2 + 2 + 8 + 64 * 64 + 18 + 12 + 2 + 2 + 16
            self.assertEqual(stats["octets"], attendu)
        self.assertEqual((e["magie"], e["nom"], e["tex_l"], e["nb_sommets"], e["zoom"]), (b"F3D1", "TEST", 64, 81, 386))
        self.assertEqual(e["version"], 4)
        self.assertEqual(e["nb_indices"], 8 * 8 * 6)


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

    def test_walkmesh_devant_la_camera_et_dans_le_decor(self):
        pts = np.array([v for tri in self.champ.walkmesh.triangles for v in tri])
        ecran, z = camera.projeter(self.champ.camera, pts)
        self.assertTrue((z > 0).all())
        # le sol tombe dans l'image du décor (512 x 512, origine -256, -256) ; un bout dépasse à gauche
        # (x = -275), hors de la zone où la caméra peut défiler
        self.assertTrue((ecran > -300).all() and (ecran < 300).all())
        self.assertTrue((ecran[:, 1] > -60).all() and (ecran[:, 1] < 100).all())

    def test_reperes(self):
        r = fond.composer(self.champ, self.mim)
        rp = reperes.calculer(self.champ, r)
        sol = rp.z_sol[np.isfinite(rp.z_sol)]
        self.assertGreater(sol.size, 10000)
        # le sol du walkmesh est dans la même plage que les profondeurs des tuiles de couche 2 (4 x ID)
        self.assertTrue(250 < sol.min() < sol.max() < 2400)
        self.assertEqual(set(np.unique(rp.z_tuiles[np.isfinite(rp.z_tuiles)])), {608.0, 1176.0, 2176.0})
        self.assertTrue(np.isinf(rp.z_occlusion[r.couche == 1]).all())

    def test_paquet_porte_camera_et_walkmesh(self):
        r = fond.composer(self.champ, self.mim)
        z = np.full(r.profondeur_id.shape, 1000.0, dtype=np.float32)
        with tempfile.TemporaryDirectory() as d:
            chemin = os.path.join(d, "m.f3d")
            relief.ecrire(chemin, "MD1STIN", r.image, z, r.origine, 386, 1000.0, 8, [], None, self.champ)
            with open(chemin, "rb") as f:
                donnees = f.read()
        fin_tri = 39 * 9 * 2 + 39 * 3 * 2 + 16  # + section personnage vide
        debut = len(donnees) - fin_tri - 2 - 2 - 12 - 18
        m = struct.unpack_from("<9h", donnees, debut)
        zoom, n = struct.unpack_from("<hH", donnees, debut + 30)
        self.assertEqual(list(m[:3]), self.champ.camera.axes[0])
        self.assertEqual((zoom, n), (386, 39))
        premier = struct.unpack_from("<3h", donnees, debut + 34)
        self.assertEqual(premier, self.champ.walkmesh.triangles[0][0])

    def test_cartes_d_occlusion(self):
        cartes = relief.cartes_occlusion(self.champ)
        ids = sorted({c[4] for c in cartes})
        # couche 2 seulement sur MD1STIN : les tuiles « toujours devant » (ID 1) et le train (152 à 544) ;
        # celles d'ID 4087-4088 sont au fond et n'occultent rien
        self.assertEqual(ids, [1, 152, 294, 544])
        self.assertTrue(all(c[3] == 2 and c[2] == 16 for c in cartes))


if __name__ == "__main__":
    unittest.main()
