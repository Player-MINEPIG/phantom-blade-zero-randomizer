import copy
import json
import unittest
from collections import Counter

from randomizer import RandomizerError, generate


def item(id_, category):
    return {"id": id_, "category": category, "stats": f"stats:{id_}", "moveset": f"moves:{id_}"}


def reward(id_, item_id, source="chest", **fields):
    return {"id": id_, "item": item_id, "source": source, **fields}


def catalog_fixture():
    items = [
        item("main-a", "main_weapon"),
        item("main-b", "main_weapon"),
        item("shadow-a", "shadow_weapon"),
        item("shadow-b", "shadow_weapon"),
        item("collect-a", "collectible"),
        item("collect-b", "collectible"),
        item("collect-c", "collectible"),
        item("collect-d", "collectible"),
        item("boss-collectible", "collectible"),
        item("fixed-token", "other"),
    ]
    return {
        "version": "fixture-v1",
        "items": items,
        "rewards": [
            reward("slot-main-a", "main-a"),
            reward("slot-main-b", "main-b", "quest"),
            reward("slot-shadow-a", "shadow-a", "boss", encounter="boss-a"),
            reward("slot-shadow-b", "shadow-b"),
            reward("slot-collect-a", "collect-a"),
            reward("slot-collect-b", "collect-b", "enemy_drop"),
            reward("slot-collect-c", "collect-c", "map_pickup"),
            reward("slot-collect-d", "collect-d", "quest"),
            reward("slot-boss-collectible", "boss-collectible", "boss", encounter="boss-a"),
            reward("slot-fixed-token", "fixed-token", "quest"),
        ],
        "encounters": [{"id": "boss-a", "grants": ["ability:dash"]}],
        "monsters": [
            {"id": "a-leader", "actor": "actor:a-leader", "group": "a", "compatibility": "leader"},
            {"id": "a-support", "actor": "actor:a-support", "group": "a", "compatibility": "support"},
            {"id": "b-leader", "actor": "actor:b-leader", "group": "b", "compatibility": "leader"},
            {"id": "b-support", "actor": "actor:b-support", "group": "b", "compatibility": "support"},
            {"id": "c-support", "actor": "actor:c-support", "group": "c", "compatibility": "support"},
            {"id": "loose-support", "actor": "actor:loose-support", "compatibility": "support"},
        ],
        "voices": [
            {"id": "ambient-a", "kind": "ambient", "audio": "audio:ambient-a", "subtitle": "站桩甲"},
            {"id": "ambient-b", "kind": "ambient", "audio": "audio:ambient-b", "subtitle": "站桩乙"},
            {"id": "ambient-c", "kind": "ambient", "audio": "audio:ambient-c", "subtitle": "站桩丙"},
            {"id": "combat-a", "kind": "combat", "audio": "audio:combat-a", "subtitle": "战斗甲"},
            {"id": "combat-b", "kind": "combat", "audio": "audio:combat-b", "subtitle": None},
            {"id": "cutscene-a", "kind": "cutscene", "audio": "audio:cutscene-a", "subtitle": "播片甲"},
        ],
    }


class EngineTests(unittest.TestCase):
    def test_seed_round_trip_and_input_order_do_not_change_plan(self):
        catalog = catalog_fixture()
        config = {"seed": "种子 2026", "weapon_mode": "independent", "monster_mode": "group", "combat_voices": True}
        original_catalog = copy.deepcopy(catalog)
        original_config = copy.deepcopy(config)
        plan = generate(catalog, config)
        self.assertEqual(catalog, original_catalog)
        self.assertEqual(config, original_config)
        self.assertEqual(json.loads(json.dumps(plan)), plan)
        self.assertEqual(generate(catalog, plan["config"]), plan)

        for value in catalog.values():
            if isinstance(value, list):
                value.reverse()
        reordered_config = dict(reversed(list(config.items())))
        self.assertEqual(json.dumps(generate(catalog, reordered_config)), json.dumps(plan))

    def test_item_modes_permute_only_their_selected_reward_slots(self):
        catalog = catalog_fixture()
        original = {row["id"]: row["item"] for row in catalog["rewards"]}
        main = {"slot-main-a", "slot-main-b"}
        shadow = {"slot-shadow-a", "slot-shadow-b"}
        collectible = {"slot-collect-a", "slot-collect-b", "slot-collect-c", "slot-collect-d"}
        modes = {
            "all": main | shadow | collectible,
            "weapons": main | shadow,
            "main_weapons": main,
            "shadow_weapons": shadow,
            "collectibles": collectible,
        }
        for mode, eligible in modes.items():
            with self.subTest(mode=mode):
                outcomes = []
                for seed in range(20):
                    result = generate(catalog, {"seed": seed, "item_mode": mode})["rewards"]
                    self.assertEqual(set(result), set(original))
                    self.assertEqual(Counter(result.values()), Counter(original.values()))
                    for slot in original.keys() - eligible:
                        self.assertEqual(result[slot], original[slot])
                    outcomes.append(result)
                self.assertTrue(any(result != original for result in outcomes))
                if mode == "all":
                    self.assertTrue(any(result["slot-shadow-a"].startswith("collect-") for result in outcomes))
                if mode == "weapons":
                    self.assertTrue(any(result["slot-main-a"].startswith("shadow-") for result in outcomes))

    def test_whitelist_keeps_excluded_items_and_weapon_data(self):
        catalog = catalog_fixture()
        original = {row["id"]: row["item"] for row in catalog["rewards"]}
        selected = {"main-a", "shadow-b", "collect-a"}
        for seed in range(12):
            plan = generate(catalog, {"seed": seed, "whitelist": sorted(selected), "weapon_mode": "linked"})
            for slot, item_id in original.items():
                if item_id not in selected:
                    self.assertEqual(plan["rewards"][slot], item_id)
            self.assertEqual(plan["weapon_stats"], plan["weapon_movesets"])
            self.assertEqual(plan["weapon_stats"]["main-b"], "main-b")
            self.assertEqual(plan["weapon_stats"]["shadow-a"], "shadow-a")
            self.assertEqual(set(plan["weapon_stats"].values()), {"main-a", "main-b", "shadow-a", "shadow-b"})
        self.assertEqual(generate(catalog, {"seed": 0, "whitelist": []})["rewards"], original)

    def test_reward_compatibility_keeps_items_within_their_writable_route(self):
        catalog = catalog_fixture()
        legacy = generate(catalog, {"seed": "legacy-reward-fixture"})["rewards"]
        self.assertEqual(legacy, {
            "slot-boss-collectible": "boss-collectible", "slot-collect-a": "collect-d", "slot-collect-b": "collect-c",
            "slot-collect-c": "collect-b", "slot-collect-d": "collect-a", "slot-fixed-token": "fixed-token",
            "slot-main-a": "main-a", "slot-main-b": "shadow-a", "slot-shadow-a": "main-b", "slot-shadow-b": "shadow-b",
        })
        routes = {
            "first": {"slot-main-a", "slot-collect-a"},
            "second": {"slot-shadow-a", "slot-collect-b", "slot-collect-c"},
            "single": {"slot-main-b"},
        }
        for row in catalog["rewards"]:
            for name, slots in routes.items():
                if row["id"] in slots:
                    row["compatibility"] = name
        original = {row["id"]: row["item"] for row in catalog["rewards"]}
        untagged = set(original) - set().union(*routes.values())
        saw_swap = False
        for seed in range(20):
            result = generate(catalog, {"seed": seed})["rewards"]
            for slots in (*routes.values(), untagged):
                self.assertEqual({result[id_] for id_ in slots}, {original[id_] for id_ in slots})
            saw_swap |= result["slot-main-a"] == "collect-a"
        self.assertTrue(saw_swap)

    def test_weapon_data_can_be_linked_independent_or_enabled_one_at_a_time(self):
        catalog = catalog_fixture()
        identity = {row["id"]: row["id"] for row in catalog["items"] if row["category"].endswith("_weapon")}
        independent_differs = False
        for seed in range(12):
            linked = generate(catalog, {"seed": seed, "weapon_mode": "linked", "item_mode": "collectibles"})
            self.assertEqual(linked["weapon_stats"], linked["weapon_movesets"])
            independent = generate(catalog, {"seed": seed, "weapon_mode": "independent"})
            independent_differs |= independent["weapon_stats"] != independent["weapon_movesets"]
            self.assertEqual(set(independent["weapon_stats"].values()), identity.keys())
            self.assertEqual(set(independent["weapon_movesets"].values()), identity.keys())
        self.assertTrue(independent_differs)
        for disabled, enabled in (("weapon_stats", "weapon_movesets"), ("weapon_movesets", "weapon_stats")):
            plan = generate(catalog, {"seed": 3, "weapon_mode": "linked", disabled: False})
            both_enabled = generate(catalog, {"seed": 3, "weapon_mode": "linked"})
            self.assertEqual(plan[disabled], identity)
            self.assertEqual(plan[enabled], both_enabled[enabled])

    def test_boss_access_is_independent_of_its_original_shadow_weapon(self):
        catalog = {
            "version": "progression-fixture",
            "items": [item("key", "collectible"), item("shadow", "shadow_weapon"), item("stone", "collectible"), item("feather", "collectible")],
            "start": ["quest:accepted"],
            "required": ["quest:complete"],
            "encounters": [
                {"id": "boss-a", "requires": ["key", "quest:accepted"], "grants": ["ability:dash"]},
                {"id": "boss-b", "requires": ["ability:dash"], "grants": ["quest:complete"]},
            ],
            "rewards": [
                reward("entry-a", "key"),
                reward("entry-b", "feather"),
                reward("boss-reward", "shadow", "boss", encounter="boss-a"),
                reward("post-dash", "stone", requires=["ability:dash"]),
            ],
        }
        shadow_moves_behind_its_ability = False
        for seed in range(30):
            plan = generate(catalog, {"seed": seed})
            self.assertIn("key", [plan["rewards"]["entry-a"], plan["rewards"]["entry-b"]])
            self.assertEqual(plan["abilities"]["boss-a"], ["ability:dash"])
            shadow_moves_behind_its_ability |= plan["rewards"]["post-dash"] == "shadow"
        self.assertTrue(shadow_moves_behind_its_ability)

    def test_weapon_compatibility_partitions_data_without_changing_reward_pools(self):
        catalog = catalog_fixture()
        legacy = generate(catalog, {"seed": "legacy-compatibility-fixture", "weapon_mode": "independent"})
        self.assertEqual(legacy["weapon_stats"], {
            "main-a": "main-b", "main-b": "shadow-a", "shadow-a": "main-a", "shadow-b": "shadow-b",
        })
        self.assertEqual(legacy["weapon_movesets"], {
            "main-a": "shadow-a", "main-b": "main-a", "shadow-a": "shadow-b", "shadow-b": "main-b",
        })
        for row in catalog["items"]:
            if row["id"] in {"main-a", "shadow-a"}:
                row["weapon_compatibility"] = "shared-rig"
            if row["id"] == "shadow-b":
                row["weapon_compatibility"] = "shadow-rig"

        changed = False
        for seed in range(12):
            for mode in ("linked", "independent"):
                plan = generate(catalog, {"seed": seed, "weapon_mode": mode})
                self.assertEqual(plan["rewards"], generate(catalog_fixture(), {"seed": seed, "weapon_mode": mode})["rewards"])
                if mode == "linked":
                    self.assertEqual(plan["weapon_stats"], plan["weapon_movesets"])
                for field in ("weapon_stats", "weapon_movesets"):
                    mapping = plan[field]
                    self.assertEqual({mapping["main-a"], mapping["shadow-a"]}, {"main-a", "shadow-a"})
                    self.assertEqual(mapping["main-b"], "main-b")
                    self.assertEqual(mapping["shadow-b"], "shadow-b")
                    changed |= mapping["main-a"] == "shadow-a"
        self.assertTrue(changed)

    def test_weapon_support_flags_limit_each_feature_to_writable_data(self):
        catalog = catalog_fixture()
        by_id = {row["id"]: row for row in catalog["items"]}
        by_id["main-b"]["stats_supported"] = False
        by_id["main-b"].pop("stats")
        by_id["shadow-b"]["moveset_supported"] = False
        by_id["shadow-b"].pop("moveset")
        independent_stats_move = independent_moves_move = linked_move = False
        for seed in range(12):
            linked = generate(catalog, {"seed": seed, "weapon_mode": "linked"})
            self.assertEqual(linked["weapon_stats"], linked["weapon_movesets"])
            self.assertEqual(linked["weapon_stats"]["main-b"], "main-b")
            self.assertEqual(linked["weapon_stats"]["shadow-b"], "shadow-b")
            linked_move |= linked["weapon_stats"]["main-a"] == "shadow-a"

            independent = generate(catalog, {"seed": seed, "weapon_mode": "independent"})
            self.assertEqual(independent["weapon_stats"]["main-b"], "main-b")
            self.assertEqual(independent["weapon_movesets"]["shadow-b"], "shadow-b")
            independent_stats_move |= independent["weapon_stats"]["shadow-b"] != "shadow-b"
            independent_moves_move |= independent["weapon_movesets"]["main-b"] != "main-b"

            stats_only = generate(catalog, {"seed": seed, "weapon_mode": "linked", "weapon_movesets": False})
            self.assertEqual(stats_only["weapon_stats"]["main-b"], "main-b")
            self.assertEqual(stats_only["weapon_movesets"], {id_: id_ for id_ in stats_only["weapon_stats"]})
        self.assertTrue(linked_move and independent_stats_move and independent_moves_move)

        by_id["shadow-b"].pop("moveset_supported")
        with self.assertRaisesRegex(RandomizerError, "shadow-b.*moveset"):
            generate(catalog, {"seed": 0, "weapon_mode": "independent"})
        by_id["shadow-b"]["moveset_supported"] = "false"
        with self.assertRaisesRegex(RandomizerError, "moveset_supported must be a boolean"):
            generate(catalog, {"seed": 0})

    def test_progression_remains_safe_when_random_permutations_cannot_pass(self):
        keys = [f"key-{index:02}" for index in range(12)]
        catalog = {
            "version": "chain-fixture",
            "items": [item(id_, "collectible") for id_ in [*keys, "filler-a", "filler-b"]],
            "rewards": [reward("start", keys[0])]
            + [reward(key, key, requires=[previous]) for previous, key in zip(keys, keys[1:])]
            + [reward("end-a", "filler-a", requires=keys), reward("end-b", "filler-b", requires=keys)],
        }
        ends_swapped = False
        for seed in range(16):
            mappings = generate(catalog, {"seed": seed})["rewards"]
            self.assertEqual(mappings["start"], keys[0])
            self.assertTrue(all(mappings[key] == key for key in keys[1:]))
            ends_swapped |= mappings["end-a"] == "filler-b"
        self.assertTrue(ends_swapped)

    def test_monster_group_mode_moves_compatible_groups_as_wholes(self):
        catalog = catalog_fixture()
        monsters = {row["id"]: row for row in catalog["monsters"]}
        unit_group_breaks = group_swaps = False
        for seed in range(20):
            unit = generate(catalog, {"seed": seed, "monster_mode": "unit"})["monsters"]
            group = generate(catalog, {"seed": seed, "monster_mode": "group"})["monsters"]
            for mode in (unit, group):
                self.assertEqual(Counter(mode.values()), Counter(monsters.keys()))
                for destination, source in mode.items():
                    self.assertEqual(monsters[destination]["compatibility"], monsters[source]["compatibility"])
            for id_ in ("a", "b"):
                leader, support = f"{id_}-leader", f"{id_}-support"
                self.assertEqual(monsters[group[leader]]["group"], monsters[group[support]]["group"])
                unit_group_breaks |= monsters[unit[leader]]["group"] != monsters[unit[support]].get("group")
            self.assertEqual(group["c-support"], "c-support")
            self.assertEqual(group["loose-support"], "loose-support")
            group_swaps |= group["a-leader"] == "b-leader"
        self.assertTrue(unit_group_breaks)
        self.assertTrue(group_swaps)

    def test_voice_slots_keep_audio_and_subtitle_together_and_cutscenes_fixed(self):
        catalog = catalog_fixture()
        voices = {row["id"]: row for row in catalog["voices"]}
        pairs = {(voice["audio"], voice["subtitle"]) for voice in voices.values()}
        ambient_changes = combat_changes = False
        for seed in range(20):
            default = generate(catalog, {"seed": seed})["voices"]
            combat = generate(catalog, {"seed": seed, "ambient_voices": False, "combat_voices": True})["voices"]
            for assignments in (default, combat):
                realized = [(voices[id_]["audio"], voices[id_]["subtitle"]) for id_ in assignments.values()]
                self.assertEqual(set(realized), pairs)
                self.assertEqual(len(realized), len(pairs))
                for destination, source in assignments.items():
                    self.assertEqual(voices[destination]["kind"], voices[source]["kind"])
                self.assertEqual(assignments["cutscene-a"], "cutscene-a")
            self.assertEqual(default["combat-a"], "combat-a")
            self.assertEqual(combat["ambient-a"], "ambient-a")
            ambient_changes |= default["ambient-a"] != "ambient-a"
            combat_changes |= combat["combat-a"] != "combat-a"
        self.assertTrue(ambient_changes)
        self.assertTrue(combat_changes)

    def test_rejects_invalid_catalogs_and_configuration(self):
        original = catalog_fixture()
        for settings, message in (
            ({"seed": True}, "config.seed"),
            ({"seed": 0, "item_mode": []}, "config.item_mode"),
            ({"seed": 0, "whitelist": ["none"]}, "unknown IDs"),
            ({"seed": 0, "whitelist": ["main-a", "main-a"]}, "duplicate entries"),
            ({"seed": 0, "weapon_stats": True}, "config.weapon_mode"),
            ({"seed": 0, "combat_voice": True}, "combat_voice"),
        ):
            with self.subTest(settings=settings), self.assertRaisesRegex(RandomizerError, message):
                generate(original, settings)

        catalog = copy.deepcopy(original)
        catalog["rewards"][2].pop("encounter")
        with self.assertRaisesRegex(RandomizerError, "encounter"):
            generate(catalog, {"seed": 0})
        catalog["rewards"][2]["encounter"] = "boss-a"
        catalog["encounters"][0]["requires"] = ["shadow-a"]
        catalog["required"] = ["ability:dash"]
        with self.assertRaisesRegex(RandomizerError, "original progression cannot reach: ability:dash"):
            generate(catalog, {"seed": 0})

        catalog = copy.deepcopy(original)
        catalog["items"][0].pop("moveset")
        with self.assertRaisesRegex(RandomizerError, "moveset"):
            generate(catalog, {"seed": 0, "weapon_mode": "linked"})
        catalog.pop("monsters")
        with self.assertRaisesRegex(RandomizerError, "requires catalog monster groups"):
            generate(catalog, {"seed": 0, "monster_mode": "group"})


if __name__ == "__main__":
    unittest.main()
