"""Verify boss-to-map swaps against cooked reward and quest data."""

import os
from struct import unpack_from
import unittest

from integrations.grants import pooled, flow_weapons
from integrations.weapons.zen import name_batch
from pbzmod import loot


@unittest.skipUnless(
    os.environ.get("PBZ_TEST_GRANT_ASSETS") == "1", "requires retail data"
)
class PooledAwardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pbzmod.__main__ import ROOT, readers
        from pbzmod.paths import PAKS_DIR, resolve_paths
        from pbzmod.reward_rows import read_text_items
        from pbzmod.usmap import load_usmap

        game, _, oodle = resolve_paths()
        helpers, _ = readers(ROOT / ".work")
        cls.store = helpers.IoStore(
            game / PAKS_DIR / "ProjectPBZ-Windows.utoc", helpers.OodleReader(oodle)
        )
        cls.grants = flow_weapons.scan(cls.store)
        cls.text = read_text_items(cls.store, load_usmap(ROOT / ".work/pbz.usmap"))

    def test_white_and_green_rows_receive_weapons_and_bosses_receive_their_whole_rewards(
        self,
    ):
        grants = self.grants
        aliases = pooled.physical_rows(grants)
        stock = self.store.read_file(loot.PATH)
        table = pooled.extend_table(self.store, stock, grants)
        names = name_batch(table)[0]
        prizes = loot.select(table, names, set(), text_items=self.text)
        assignments = {id_: g.item for id_, g in grants.items()}
        ids = {g.item: id_ for id_, g in grants.items()}
        rows = {}
        examples = {
            "Xigu.006.Dust_Medium": "JadeDualChakram",
            "Xigu.R_01030": "CaoOuSiXian",
        }
        for row, weapon in examples.items():
            id_ = ids[weapon]
            assignments[id_] = prizes[row].item
            rows[row] = weapon
            rows[aliases[id_]] = prizes[row].item
        patches, deps = pooled.rewrite_changed(self.store, grants, assignments)
        final = loot.apply_reviewed(
            table,
            names,
            set(),
            {r: prizes[r] for r in rows},
            rows,
            text_items=self.text,
        )
        before, after = [loot.read_table(b, names) for b in (table, final)]
        for row, weapon in examples.items():
            id_ = ids[weapon]
            g = grants[id_]
            original = flow_weapons.QuestPackage(self.store.read_file(g.path))
            graph = patches[g.path]
            header = unpack_from("<15I", graph)
            start = header[1] + original.grant.offset
            self.assertEqual(graph[start : start + 4], pooled.LOOT_PREFIX)
            name, num = unpack_from("<II", graph, start + 8)
            key = f"{name_batch(graph)[0][name]}_{num - 1}"
            self.assertEqual(key, aliases[id_])
            self.assertEqual(after[key][1][1], before[row][1][1])
            self.assertEqual(after[row][1][1][0][3][0][0], weapon)
            self.assertEqual(
                bool(after[row][1][1][0][3][0].get(1)), g.category == "main_weapon"
            )
            self.assertEqual(graph[start + 20 : start + 36].hex(), id_.split(":")[1])
            self.assertIn(g.path, deps)
        self.assertEqual(len(patches), len(examples))
        self.assertEqual(len(table), len(final))


if __name__ == "__main__":
    unittest.main()
