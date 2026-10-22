"""Tests de l'inventaire des adresses PS1 (outils/ff7_3d/adresses.py)."""
import unittest

from ff7_3d import adresses


def genres(source):
    return [(o.valeur, o.genre) for o in adresses.analyser_source(source)]


class TestClassement(unittest.TestCase):
    def test_pointeur(self):
        self.assertEqual(genres("SysGzipSetDataBlock((u8*)0x801B0000);"), [(0x801B0000, "pointeur")])
        self.assertEqual(genres("p = (const FieldModel *) 0x80100000;"), [(0x80100000, "pointeur")])

    def test_calcul_de_relocation(self):
        self.assertEqual(genres("relocation = (u32)file - 0x80000000;"), [(0x80000000, "calcul")])

    def test_comparaison_meme_transtypee(self):
        self.assertEqual(genres("if ((u32)p > (u32)0x80184000) {"), [(0x80184000, "comparaison")])

    def test_masque(self):
        self.assertEqual(genres("x = y & 0x80008000;"), [(0x80008000, "masque")])
        self.assertEqual(genres("if (a && 0x80000000) {}"), [(0x80000000, "autre")])

    def test_transtypage_vers_un_typedef(self):
        self.assertEqual(genres("(MagicEntry)0x801B08D4,"), [(0x801B08D4, "transtypage")])

    def test_entier_nu(self):
        self.assertEqual(genres("AkaoStart(0x800F0000, 0x801BC800);"), [(0x800F0000, "autre"), (0x801BC800, "autre")])

    def test_scratchpad_et_hors_zone(self):
        self.assertEqual(genres("s = (u8*)0x1F800010; t = 0x80200000; u = 0x1F800400;"), [(0x1F800010, "pointeur")])
        self.assertEqual(adresses.zone(0x1F800010), "scratchpad")
        self.assertEqual(adresses.zone(0x801FFFFF), "ram")

    def test_commentaires_ignores_numeros_gardes(self):
        o = adresses.analyser_source("/* 0x80010000\n */ // 0x80020000\nint* p = (int*)0x80030000;")
        self.assertEqual([(x.ligne, x.valeur) for x in o], [(3, 0x80030000)])


class TestInventaire(unittest.TestCase):
    def test_le_terrain_et_la_relocation_des_modeles(self):
        occ = adresses.inventaire()
        terrain = [o for o in occ if o.fichier.startswith("src/field/")]
        self.assertTrue(terrain)
        self.assertIn("calcul", {o.genre for o in terrain if o.fichier.endswith("field_model.c")})


if __name__ == "__main__":
    unittest.main()
