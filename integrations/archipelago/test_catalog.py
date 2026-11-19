import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from integrations.archipelago.import_catalog import convert
from randomizer.engine import generate


DIRECTORY = Path(__file__).parent


def load_data(basename):
    return json.loads((DIRECTORY / f"{basename}.upstream-v0.9.2.json").read_text(encoding="utf-8"))


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = load_data("catalog")
        self.bridge_map = load_data("bridge-map")

    def test_bridge_ids_cover_the_catalog(self):
        self.assertEqual(self.catalog["version"], self.bridge_map["version"])
        rewards = self.catalog["rewards"]
        checks = self.bridge_map["checks"]
        self.assertEqual(len({*checks.values()}), len(rewards))
        self.assertEqual(set(checks), {reward["id"] for reward in rewards})
        self.assertEqual(Counter(reward["source"] for reward in rewards), {"chest": 19, "map_pickup": 629})
        items = self.bridge_map["items"]
        self.assertEqual(len(items), 48)
        self.assertEqual(set(items), {item["id"] for item in self.catalog["items"]})
        self.assertEqual(set(items), {reward["item"] for reward in rewards})
        self.assertTrue(all(item["grant"] == "prop" for item in items.values()))

    def test_seed_works_with_real_rewards(self):
        config = {"seed": "登顶山道", "item_mode": "collectibles"}
        plan = generate(self.catalog, config)
        self.assertEqual(plan, generate(self.catalog, config))
        original = {reward["id"]: reward["item"] for reward in self.catalog["rewards"]}
        self.assertEqual(set(original), set(plan["rewards"]))
        self.assertEqual(Counter(original.values()), Counter(plan["rewards"].values()))
        self.assertNotEqual(original, plan["rewards"])

    def test_import_rejects_unrecognized_release(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "phantom_blade_zero.apworld"
            file.write_bytes(b"not the pinned release")
            with self.assertRaisesRegex(ValueError, "does not match PBZArchipelago v0.9.2"):
                convert(file, Path(directory) / "PBZArchipelago.zip")
