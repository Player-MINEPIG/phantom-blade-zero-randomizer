import os
import unittest

from integrations.grants.flow_weapons import DOMAIN, Grant, QuestPackage, apply, scan
from randomizer import generate


def catalog_for(grants):
    return {
        "version": "direct-weapon-tests",
        "items": [{"id": grant.item, "category": grant.category} for grant in grants.values()],
        "rewards": [grant.reward() for grant in grants.values()],
        "encounters": [{"id": grant.encounter, "requires": [], "grants": []} for grant in grants.values()],
    }


class GrantModeTest(unittest.TestCase):
    def test_modes_apply_to_the_direct_weapon_pool(self):
        category = {"M1": "main_weapon", "M2": "main_weapon", "S1": "shadow_weapon", "S2": "shadow_weapon"}
        grants = {
            item: Grant(item, f"{item}.uasset", item, kind, f"encounter:{item}")
            for item, kind in category.items()
        }
        catalog = catalog_for(grants)
        catalog["items"].extend([{"id": "outside", "category": "main_weapon"}, {"id": "gem", "category": "collectible"}])
        catalog["rewards"].extend([
            {"id": "outside", "item": "outside", "source": "chest", "compatibility": "level_loot"},
            {"id": "gem", "item": "gem", "source": "chest", "compatibility": "level_loot"},
        ])
        self.assertTrue(all(grant.reward()["compatibility"] == DOMAIN for grant in grants.values()))

        def reward_plans(mode):
            return [generate(catalog, {"seed": seed, "item_mode": mode})["rewards"] for seed in range(8)]

        for mode in ("all", "weapons"):
            plans = reward_plans(mode)
            self.assertTrue(any(category[plan["M1"]] == "shadow_weapon" for plan in plans))
            self.assertTrue(all({plan[item] for item in grants} == set(grants) for plan in plans))
        for mode, anchor, still, movable in (
            ("main_weapons", "M1", "S1", "M2"), ("shadow_weapons", "S1", "M1", "S2"),
        ):
            plans = reward_plans(mode)
            self.assertTrue(any(plan[anchor] == movable for plan in plans))
            self.assertTrue(all(plan[still] == still for plan in plans))
        self.assertTrue(all(all(plan[item] == item for item in grants) for plan in reward_plans("collectibles")))


@unittest.skipUnless(os.environ.get("PBZ_TEST_GRANT_ASSETS") == "1", "requires the original local game assets")
class RealGrantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pbzmod.__main__ import ROOT, readers
        from pbzmod.paths import PAKS_DIR, resolve_paths

        helpers, _ = readers(ROOT / ".work")
        game, _, oodle = resolve_paths()
        cls.store = helpers.IoStore(game / PAKS_DIR / "ProjectPBZ-Windows.utoc", helpers.OodleReader(oodle))
        cls.grants = scan(cls.store)

    def test_cross_category_patch_replaces_id_and_weapon_type(self):
        by_item = {grant.item: grant for grant in self.grants.values()}
        main, shadow = by_item["BaiYing"], by_item["TieGongZhuQuanTao"]
        patches = apply(self.store, self.grants, {main.id: shadow.item, shadow.id: main.item})
        self.assertEqual(set(patches), {main.path, shadow.path})
        actual_main = QuestPackage(patches[main.path]).read_grant()
        actual_shadow = QuestPackage(patches[shadow.path]).read_grant()
        self.assertEqual(actual_main[:3], (shadow.item, False, main.id.removeprefix("grant:")))
        self.assertEqual(actual_shadow[:3], (main.item, True, shadow.id.removeprefix("grant:")))

    def test_scan_excludes_items_already_owned_by_another_catalog(self):
        grants = scan(self.store, exclude_items={"BaiYing"})
        self.assertEqual(len(grants), 6)
        self.assertNotIn("BaiYing", {grant.item for grant in grants.values()})

    def test_apply_rejects_prioritized_item_outside_the_pool(self):
        id_ = next(iter(self.grants))
        with self.assertRaisesRegex(ValueError, "must preserve the reviewed weapon pool"):
            apply(self.store, self.grants, {id_: "BrutalAxe"})
