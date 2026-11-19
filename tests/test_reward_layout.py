from struct import pack
import unittest

from pbzmod import loot
from pbzmod.reward_layout import bind_plan, resolve_layout


class RewardLayoutTest(unittest.TestCase):
    def test_discards_only_recorded_rewards_and_restores_other_originals(self):
        permutation = {"key": "weapon", "weapon": "key", "scroll": "scroll", "dust": "dust"}
        layout = resolve_layout(
            permutation, enabled=False, vanilla_claimed=["scroll"],
            claims=[{"point": "key", "enabled": True, "source": "weapon"}],
        )
        self.assertEqual(layout.granted, {"scroll": "scroll", "key": "weapon"})
        self.assertEqual(layout.remaining, {"weapon": "key", "dust": "dust"})
        self.assertEqual(layout.origins, permutation)

    def test_replays_a_pristine_claim_and_two_mode_changes_in_order(self):
        permutation = {"a": "b", "b": "c", "c": "d", "d": "a", "e": "e"}
        claims = [
            {"point": "a", "enabled": True, "source": "b"},
            {"point": "b", "enabled": False, "source": "a"},
            {"point": "c", "enabled": True, "source": "c"},
        ]
        for enabled in (False, True):
            current = resolve_layout(permutation, enabled=enabled, vanilla_claimed=["d"], claims=claims)
            self.assertEqual(current.origins, {"a": "b", "b": "a", "c": "c", "d": "d", "e": "e"})
            self.assertEqual(current.remaining, {"e": "e"})
        earlier = resolve_layout(permutation, enabled=True, vanilla_claimed=["d"], claims=claims[:1])
        self.assertEqual(earlier.remaining, {"b": "c", "c": "a", "e": "e"})

    def test_protects_failed_quest_in_a_mixed_cycle_without_recording_a_grant(self):
        permutation = {
            "failed-quest": "document", "document": "weapon", "weapon": "failed-quest",
            "old-dust": "old-dust",
        }
        original = resolve_layout(
            permutation, enabled=True, protected=["failed-quest"], vanilla_claimed=["old-dust"],
        )
        self.assertEqual(original.granted, {"old-dust": "old-dust"})
        self.assertEqual(original.remaining, {
            "failed-quest": "failed-quest", "document": "weapon", "weapon": "document",
        })
        restored = resolve_layout(
            permutation, enabled=False, protected=["failed-quest"], vanilla_claimed=["old-dust"],
            claims=[{"point": "document", "enabled": True, "source": "weapon"}],
        )
        self.assertEqual(restored.remaining, {"failed-quest": "failed-quest", "weapon": "document"})
        self.assertEqual(restored.granted, {"old-dust": "old-dust", "document": "weapon"})
        manually_claimed = resolve_layout(
            permutation, enabled=True, protected=["failed-quest"],
            claims=[{"point": "failed-quest", "enabled": True, "source": "failed-quest"}],
        )
        self.assertEqual(manually_claimed.granted, {"failed-quest": "failed-quest"})
        self.assertNotIn("failed-quest", manually_claimed.remaining)

    def test_rejects_duplicate_points_wrong_sources_and_invalid_matches(self):
        permutation = {"a": "b", "b": "a"}
        claim = {"point": "a", "enabled": True}
        with self.assertRaisesRegex(ValueError, "already recorded"):
            resolve_layout(permutation, enabled=True, claims=[claim, claim])
        with self.assertRaisesRegex(ValueError, "source mismatch"):
            resolve_layout(permutation, enabled=False, claims=[claim | {"source": "a"}])
        with self.assertRaisesRegex(ValueError, "Unknown original"):
            resolve_layout(permutation, enabled=False, vanilla_claimed=["other"])
        with self.assertRaisesRegex(ValueError, "permutation"):
            resolve_layout({"a": "b", "b": "b"}, enabled=False)

    def test_binds_legacy_and_explicit_plans_through_the_boss_row_alias(self):
        aliases = {"boss": "LootItems_C_1001"}
        prizes = {
            "r1": loot.Prize("r1", "material", "collectible", 0, 0),
            "r2": loot.Prize("r2", "material", "collectible", 0, 0),
            "LootItems_C_1001": loot.Prize("LootItems_C_1001", "sword", "main_weapon", 0, 0),
        }
        plan = {"rewards": {"r1": "material", "r2": "sword", "boss": "material"}}
        self.assertEqual(bind_plan(plan, prizes, aliases), {"r1": "r1", "boss": "r2", "r2": "boss"})
        explicit = plan | {"reward_sources": {"r1": "r2", "r2": "boss", "boss": "r1"}}
        self.assertEqual(bind_plan(explicit, prizes, aliases), explicit["reward_sources"])
        with self.assertRaisesRegex(ValueError, "disagrees"):
            bind_plan(plan | {"reward_sources": {"r1": "boss", "boss": "r1"}}, prizes, aliases)

    def test_explicit_same_item_swap_moves_the_full_amount_and_preserves_closed_row(self):
        names = ["World.Material1", "World.Material2", "Iron"]

        def record(row, amount):
            key = pack("<II", row, 0)
            return (
                key + pack("<H", 0x0500) + key + pack("<I", 1)
                + pack("<HIH", 0x0302, 1, 0x0900) + pack("<IIiif", 2, 0, amount, amount, 1.0)
            )

        prefix = pack("<II", 0, 8) + bytes.fromhex("0003fbffffff00000000") + pack("<I", 2)
        data = prefix + record(0, 4) + record(1, 3)
        selected = loot.select(data, names, {"Iron"})
        row_a, row_b = names[:2]
        items = {row_a: "Iron", row_b: "Iron"}
        permutation = {row_a: row_b, row_b: row_a}
        first = resolve_layout(permutation, enabled=True)
        second = resolve_layout(
            permutation, enabled=False, claims=[{"point": row_a, "enabled": True}],
        )

        def build(layout):
            return loot.apply_reviewed(data, names, {"Iron"}, selected, items, origins=layout.origins)

        before = build(first)
        self.assertEqual(build(second), before)
        levels = loot.read_table(before, names)
        self.assertEqual(levels[row_a][1][1][0][2][0][1], 3)
        self.assertEqual(levels[row_b][1][1][0][2][0][1], 4)
        self.assertEqual(build(resolve_layout(permutation, enabled=False)), data)


if __name__ == "__main__":
    unittest.main()
