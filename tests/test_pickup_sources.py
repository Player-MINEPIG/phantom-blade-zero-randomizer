import os
import unittest

from pbzmod import pickup_sources


@unittest.skipUnless(
    os.environ.get("PBZ_TEST_PICKUP_ASSETS") == "1",
    "requires the local game assets for Steam build 26367565",
)
class NativePickupSourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pbzmod.__main__ import ROOT, readers
        from pbzmod.paths import PAKS_DIR, resolve_paths
        from pbzmod.usmap import load_usmap

        helpers, _ = readers(ROOT / ".work")
        game, _, oodle = resolve_paths()
        cls.store = helpers.IoStore(
            game / PAKS_DIR / "ProjectPBZ-Windows.utoc",
            helpers.OodleReader(oodle),
        )
        cls.names = staticmethod(helpers.name_batch)
        cls.safe = pickup_sources.scan(
            cls.store,
            load_usmap(ROOT / ".work" / "pbz.usmap"),
            {
                "Xigu.Extra.001",
                "DengDingShanDao.AC_LowHealth",
                "DengDingShanDao.I_10001",
                "DengDingShanDao.R_040018",
                "LuJiaCun.006.Dust_Small",
                "DuanHunYa.Dust_G.001",
                "DengDingShanDao.wmA.007",
                "Xigu.001.Long",
                "XiMeng.001.AC_MagicWeapon",
            },
        )

    def test_matches_native_classes_and_numbered_row_reference(self):
        pickup = self.safe["Xigu.Extra.001"]
        self.assertEqual(pickup["source"], "map_pickup")
        self.assertEqual(pickup["cell"], "6NWKZNOL6IVE40JZ5JRTGEHRR")
        self.assertEqual(
            pickup["actor"], "BP_Rubbish_C_UAID_60CF8480990999F202_2034092033"
        )
        self.assertEqual(self.safe["DengDingShanDao.AC_LowHealth"]["source"], "chest")
        self.assertEqual(self.safe["DengDingShanDao.R_040018"]["source"], "map_pickup")
        numbered = "DengDingShanDao.I_10001"
        package = self.store.read_file(self.safe[numbered]["package"])
        names, _ = self.names(package)
        self.assertNotIn(numbered, names)

    def test_excludes_shared_or_conditioned_placement(self):
        protected = {
            "LuJiaCun.006.Dust_Small",
            "DuanHunYa.Dust_G.001",
            "DengDingShanDao.wmA.007",
            "Xigu.001.Long",
            "XiMeng.001.AC_MagicWeapon",
        }
        self.assertEqual(protected.intersection(self.safe), set())
