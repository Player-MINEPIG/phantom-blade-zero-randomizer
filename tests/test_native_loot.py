import os
from struct import pack
import unittest

from pbzmod import loot, reward_rows
from randomizer import generate


class ExtendedLootTest(unittest.TestCase):
    def test_reviewed_extensions_use_pinned_aliases_and_preserve_stock_hash_guard(self):
        names = ["LootItems_C", "BaiYing", "TanLang", "Axe"]

        def record(alias, weapon):
            row_name = pack("<II", 0, alias + 1)
            return (
                row_name + pack("<H", 0x0500) + row_name + pack("<I", 1)
                + pack("<HIH", 0x0303, 1, 0x0700) + pack("<IIBf", weapon, 0, 1, 1.0)
            )

        header = pack("<II", 0, 8) + bytes.fromhex("0003fbffffff00000000") + pack("<I", 3)
        original = header + record(1001, 1) + record(1002, 2) + record(1008, 3)
        selected = loot.select(original, names, set())
        self.assertEqual(set(selected), {"LootItems_C_1001", "LootItems_C_1002"})
        assignments = {"LootItems_C_1001": "TanLang", "LootItems_C_1002": "BaiYing"}

        with self.assertRaisesRegex(ValueError, "source hash"):
            loot.apply(original, names, set(), selected, assignments)
        patched = loot.apply_reviewed(original, names, set(), selected, assignments)
        self.assertEqual({row: prize.item for row, prize in loot.select(patched, names, set()).items()}, assignments)
        self.assertEqual(loot.read_table(patched, names)["LootItems_C_1008"], loot.read_table(original, names)["LootItems_C_1008"])


@unittest.skipUnless(os.environ.get("PBZ_TEST_LOOT_ASSETS") == "1", "requires the original local game assets")
class NativeLootTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pbzmod.__main__ import ROOT, read_json, readers
        from pbzmod.paths import PAKS_DIR, resolve_paths
        from pbzmod.usmap import load_usmap

        helpers, _ = readers(ROOT / ".work")
        game, _, oodle = resolve_paths()
        store = helpers.IoStore(game / PAKS_DIR / "ProjectPBZ-Windows.utoc", helpers.OodleReader(oodle))
        cls.original = store.read_file(loot.PATH)
        cls.names = helpers.name_batch(cls.original)[0]
        cls.allowed = {
            item["id"]
            for item in read_json(ROOT / "integrations/archipelago/catalog.upstream-v0.9.2.json")["items"]
        }
        cls.prizes = loot.select(cls.original, cls.names, cls.allowed)
        cls.sources = read_json(ROOT / "pbzmod/world_sources.json")
        cls.text_items = reward_rows.read_text_items(store, load_usmap(ROOT / ".work/pbz.usmap"))

    def test_quest_black_blade_stays_in_the_weeping_valley(self):
        self.assertIn("Xigu.001.Long", loot.read_table(self.original, self.names))
        self.assertNotIn("Xigu.001.Long", self.prizes)

    def test_swapping_one_duplicate_preserves_other_quantity_and_whitelist(self):
        retained, moved, donor, excluded = (
            "Xigu.HongFangZi.Wm001", "Xigu.HongFangZi.Wm002", "Xigu.Extra.001", "Xigu.Extra.002",
        )
        selected = {row: self.prizes[row] for row in (retained, moved, donor, excluded)}
        original_rows = loot.read_table(self.original, self.names)
        material = selected[retained].item
        other = selected[donor].item
        outside = selected[excluded].item
        self.assertEqual(selected[moved].item, material)
        self.assertEqual(len({material, other, outside}), 3)

        def quantity(table, row):
            item = table[row][1][1][0][2][0]
            return item[0], item[1], item[2]

        self.assertEqual(quantity(original_rows, retained), (material, 4, 4))
        self.assertEqual(quantity(original_rows, moved), (material, 3, 3))
        self.assertEqual(quantity(original_rows, donor), (other, 16, 16))

        catalog = {
            "version": "stock-loot-regression",
            "items": [{"id": item, "category": "collectible"} for item in (material, other, outside)],
            "rewards": [
                {"id": row, "item": prize.item, "source": self.sources[row]["source"], "compatibility": "level_loot"}
                for row, prize in selected.items()
            ],
        }
        plan = generate(catalog, {"seed": 0, "item_mode": "collectibles", "whitelist": [material, other]})
        assignments = plan["rewards"]
        self.assertEqual(assignments, {retained: material, moved: other, donor: material, excluded: outside})

        patched = loot.apply(self.original, self.names, self.allowed, selected, assignments)
        readback = loot.read_table(patched, self.names)
        self.assertEqual(readback.keys(), original_rows.keys())
        self.assertEqual(quantity(readback, donor), (material, 3, 3))
        self.assertEqual(quantity(readback, moved), (other, 16, 16))
        self.assertEqual(readback[retained], original_rows[retained])
        self.assertEqual(readback[excluded], original_rows[excluded])
        self.assertEqual(len(patched), len(self.original))

        authorized_changes = {
            index
            for prize in (selected[moved], selected[donor])
            for offset in (prize.outer, prize.inner)
            for index in range(offset, offset + 8)
        }
        changed = {i for i, (before, after) in enumerate(zip(self.original, patched)) if before != after}
        self.assertTrue(changed)
        self.assertLessEqual(changed, authorized_changes)

    def test_dust_and_lore_move_as_complete_native_records(self):
        dust_a, dust_b = "Xigu.Dust.Ma.002", "Xigu.Dust.Ma.003"
        page = "Xigu.Page_CS_02"
        quest_page = "Xigu.R_01007"
        prizes = loot.select(self.original, self.names, self.allowed, text_items=self.text_items)
        self.assertEqual(prizes[page].item, "Page_CS_02")
        self.assertEqual(prizes["Xigu.R_01001"].item, "R_01001")
        self.assertNotIn(quest_page, prizes)
        self.assertTrue(prizes[dust_a].item.startswith("dust:224:224:"))
        self.assertTrue(prizes[dust_b].item.startswith("dust:220:220:"))
        selected = {row: prizes[row] for row in (dust_a, dust_b, page)}
        donors = {dust_a: page, dust_b: dust_a, page: dust_b}
        assignments = {row: prizes[source].item for row, source in donors.items()}

        patched = loot.apply(self.original, self.names, self.allowed, selected, assignments, text_items=self.text_items)
        original_rows = loot.read_table(self.original, self.names)
        readback = loot.read_table(patched, self.names)
        for target, source in donors.items():
            self.assertEqual(readback[target][1][1], original_rows[source][1][1])
        self.assertEqual(readback[quest_page], original_rows[quest_page])
        self.assertEqual(len(patched), len(self.original))


if __name__ == "__main__":
    unittest.main()
