"""Tests des sorties d'écran (portes) et de la table des noms."""
import os
import unittest

from ff7_3d import chemins, ecrans, field
from ff7_3d.disque import Disque

DISQUE_PRESENT = os.path.exists(chemins.DISQUE)


class TestNoms(unittest.TestCase):
    def test_table_de_la_decompilation(self):
        n = ecrans.noms()
        self.assertEqual(len(n), 787)
        self.assertEqual((n[116], n[117], n[118]), ("MD1STIN", "MD1_1", "MD1_2"))


@unittest.skipUnless(DISQUE_PRESENT, "disque du joueur absent")
class TestPortes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Disque(chemins.DISQUE) as d:
            cls.champs = {n: field.charger(d, n)[0] for n in ("MD1STIN", "MD1_1", "MD1_2")}

    def test_la_gare_mene_au_quai_suivant(self):
        portes = self.champs["MD1STIN"].portes
        self.assertEqual([ecrans.nom(p.index_cible) for p in portes], ["MD1_1"])

    def test_aller_retour(self):
        self.assertEqual(sorted(ecrans.nom(p.index_cible) for p in self.champs["MD1_1"].portes), ["MD1STIN", "MD1_2"])

    def test_arrivee_sur_le_walkmesh_cible(self):
        for nom, champ in self.champs.items():
            for p in champ.portes:
                cible = self.champs.get(ecrans.nom(p.index_cible))
                if cible is None:
                    continue
                self.assertLess(p.triangle, len(cible.walkmesh.triangles), nom)
                tri = cible.walkmesh.triangles[p.triangle]
                xs = [v[0] for v in tri]
                ys = [v[1] for v in tri]
                # l'arrivée est près du triangle annoncé (à quelques mailles près)
                self.assertLess(abs(p.arrivee[0] - sum(xs) / 3), 400, nom)
                self.assertLess(abs(p.arrivee[1] - sum(ys) / 3), 400, nom)


@unittest.skipUnless(DISQUE_PRESENT, "disque du joueur absent")
class TestSectionPortes(unittest.TestCase):
    def test_section_du_paquet(self):
        import io
        import struct
        from ff7_3d import relief
        with Disque(chemins.DISQUE) as d:
            champ = field.charger(d, "MD1_1")[0]
        f = io.BytesIO()
        relief.ecrire_portes(f, champ)
        b = f.getvalue()
        magie, n = struct.unpack_from("<4sH", b, 0)
        self.assertEqual((magie, n, len(b)), (b"PORT", 2, 6 + 2 * 28))
        cibles = sorted(struct.unpack_from("<6h2hh9sB", b, 6 + 28 * i)[9].rstrip(b"\0") for i in range(n))
        self.assertEqual(cibles, [b"MD1STIN", b"MD1_2"])


if __name__ == "__main__":
    unittest.main()
