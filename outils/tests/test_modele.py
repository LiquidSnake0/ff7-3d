"""Tests des modèles de terrain (Cloud). Sautés si le disque du joueur est absent."""
import os
import unittest

import numpy as np

from ff7_3d import chemins, modele
from ff7_3d.disque import Disque

DISQUE_PRESENT = os.path.exists(chemins.DISQUE)


class TestRotation(unittest.TestCase):
    def test_angle_nul_identite(self):
        np.testing.assert_allclose(modele.rotation_yxz(0, 0, 0), np.eye(3), atol=1e-12)

    def test_quart_de_tour_autour_de_z(self):
        r = modele.rotation_yxz(0, 0, 64)
        np.testing.assert_allclose(r @ [1, 0, 0], [0, 1, 0], atol=1e-12)

    def test_ordre_yxz(self):
        a, b, c = 17, 200, 90
        attendu = modele.rotation_yxz(0, b, 0) @ modele.rotation_yxz(a, 0, 0) @ modele.rotation_yxz(0, 0, c)
        np.testing.assert_allclose(modele.rotation_yxz(a, b, c), attendu, atol=1e-12)


@unittest.skipUnless(DISQUE_PRESENT, "disque du joueur absent")
class TestCloud(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Disque(chemins.DISQUE) as d:
            cls.cloud = modele.charger_bcx(d, "CLOUD")

    def test_structure(self):
        c = self.cloud
        self.assertEqual((len(c.os), len(c.parties), len(c.animations)), (22, 15, 3))
        self.assertEqual(c.echelle, 512)
        self.assertEqual(sum(len(p.sommets) for p in c.parties), 298)
        self.assertEqual([a.nb_images for a in c.animations], [1, 30, 15])  # debout, marche, course
        self.assertEqual(c.os[0].parent, -1)
        for i, os_ in enumerate(c.os[1:], 1):
            self.assertLess(os_.parent, i)

    def test_indices_dans_les_parties(self):
        for p in self.cloud.parties:
            for pg in p.polygones:
                self.assertTrue(all(i < len(p.sommets) for i in pg.sommets))

    def test_debout_sur_ses_pieds(self):
        r, t = modele.racine(np.eye(3), np.zeros(3), np.zeros(3), 0)
        pts = np.concatenate(modele.sommets_monde(self.cloud, modele.matrices(self.cloud, 0, 0, r, t)))
        self.assertAlmostEqual(pts[:, 2].min(), 0.0, delta=4.0)      # les pieds au sol
        self.assertTrue(115 < pts[:, 2].max() < 140)                # environ 126 unités de haut
        self.assertLess(np.ptp(pts[:, 0]), 90)                       # bras le long du corps

    def test_regarde_vers_moins_y_a_la_direction_zero(self):
        r, t = modele.racine(np.eye(3), np.zeros(3), np.zeros(3), 0)
        pts = modele.sommets_monde(self.cloud, modele.matrices(self.cloud, 0, 0, r, t))
        tete = self.cloud.parties[2]
        peau = [pts[2][list(pg.sommets)].mean(0) for pg in tete.polygones
                if pg.couleurs[0][0] > 180 and pg.couleurs[0][2] > 100]
        self.assertLess(np.mean(peau, 0)[1], pts[2].mean(0)[1])  # le visage est du côté -y

    def test_md1stin_charge_cloud_en_premier(self):
        from ff7_3d import field
        with Disque(chemins.DISQUE) as d:
            champ, _mim = field.charger(d, "MD1STIN")
        self.assertEqual(len(champ.modeles), 10)
        c = champ.modeles[0]
        self.assertEqual((c.global_id, c.nb_os, c.nb_parties), (1, 22, 15))
        self.assertEqual(modele.personnage_du_joueur(champ), "CLOUD")

    def test_cuisson(self):
        c = modele.cuire(self.cloud)
        self.assertEqual(c.nb_sommets, 298)
        self.assertEqual([a.shape for a in c.animations], [(1, 298, 3), (30, 298, 3), (15, 298, 3)])
        self.assertTrue(all(max(t[:3]) < c.nb_sommets for t in c.triangles))
        self.assertTrue(115 < c.hauteur < 140)

    def test_la_marche_bouge_les_jambes(self):
        r, t = modele.racine(np.eye(3), np.zeros(3), np.zeros(3), 0)
        a = np.concatenate(modele.sommets_monde(self.cloud, modele.matrices(self.cloud, 1, 0, r, t)))
        b = np.concatenate(modele.sommets_monde(self.cloud, modele.matrices(self.cloud, 1, 15, r, t)))
        self.assertGreater(np.abs(a - b).max(), 10)


if __name__ == "__main__":
    unittest.main()
