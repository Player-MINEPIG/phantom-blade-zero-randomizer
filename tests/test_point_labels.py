import unittest

from pbzmod.point_labels import _dust_quantity, _place


class PointLabelTest(unittest.TestCase):
    def test_uses_only_the_worlds_bells_and_describes_teleport_orientation(self):
        bells = {
            "world_a": [((0, 0, 0), "far", "山脚", "山路", 0)],
            "world_b": [((1000, 0, 0), "near", "营地", "峡谷", 0)],
        }
        place = _place("World_A", (1000, 0, 0), bells)
        self.assertEqual(place, "山路 · 山脚铃铛 · 直线约 10 米 · 传送朝向的前方")
        self.assertIsNone(_place("World_C", (1000, 0, 0), bells))

    def test_labels_only_known_first_cycle_dust_amounts(self):
        known = {0: 220, 1: 220, 2: [1.0, 2.5], 3: 1.0}
        self.assertEqual(_dust_quantity([{1: [known]}]), "220")
        self.assertEqual(_dust_quantity([{1: [known | {1: 224, 2: []}]}]), "220–224")
        self.assertIsNone(_dust_quantity([{1: [known | {2: [1.5]}]}]))
        self.assertIsNone(_dust_quantity([{1: [known | {3: 0.25}]}]))


if __name__ == "__main__":
    unittest.main()
