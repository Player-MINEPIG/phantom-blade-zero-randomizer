import struct
import unittest
from dataclasses import replace
from unittest.mock import patch

from integrations.monsters.zen_spawners import Spawner, _properties, catalog_monsters, patch_monsters


class MonsterPatchTests(unittest.TestCase):
    def setUp(self):
        self.path = "fixture.umap"
        self.slots = {
            "melee-a": Spawner("melee-a", "BP_Monster_HuaShan_Normal_White_C", 1, "a"),
            "ranged-a": Spawner("ranged-a", "BP_Monster_ArrowMan_Bow_C", 22, "a"),
            "melee-b": Spawner("melee-b", "BP_Monster_MaleThug_TwinAxe_C", 43, "b"),
            "ranged-b": Spawner("ranged-b", "BP_Monster_FemaleThug_Dart_C", 64, "b"),
        }
        self.records = {id_: struct.pack("<5I", *range(index, index + 5)) for index, id_ in enumerate(self.slots)}
        self.before = b"." + b".".join(self.records.values()) + b"."
        self.read_file = {self.path: self.before}.__getitem__
        self.identity = {self.slot_id(id_): self.slot_id(id_) for id_ in self.slots}
        reader = patch("integrations.monsters.zen_spawners.inspect_map", side_effect=self.read_fixture)
        reader.start()
        self.addCleanup(reader.stop)

    def read_fixture(self, data):
        actors = {self.records[id_]: slot.actor for id_, slot in self.slots.items()}
        return {
            id_: replace(slot, actor=actors[data[slot.class_offset:slot.class_offset + 20]])
            for id_, slot in self.slots.items()
        }

    def slot_id(self, id_):
        return f"{self.path}#{id_}"

    def assignments(self, *pairs):
        mapping = self.identity.copy()
        for left, right in pairs:
            mapping[self.slot_id(left)] = self.slot_id(right)
            mapping[self.slot_id(right)] = self.slot_id(left)
        return mapping

    def test_class_only_patch_preserves_group_and_surrounding_bytes(self):
        with patch("integrations.monsters.zen_spawners._load_maps", return_value={self.path: (self.before, self.slots)}):
            rows = {row["id"]: row for row in catalog_monsters(self.read_file)}
            self.assertEqual(rows[self.slot_id("melee-a")]["group"], self.slot_id("a"))
            self.assertEqual(rows[self.slot_id("ranged-a")]["compatibility"], self.slot_id("ranged"))
            swapped = self.assignments(("melee-a", "melee-b"), ("ranged-a", "ranged-b"))
            changed = patch_monsters(self.read_file, swapped, "group")[self.path]
            self.assertEqual(len(changed), len(self.before))
            self.assertEqual(changed, b"." + b".".join(self.records[id_] for id_ in ("melee-b", "ranged-b", "melee-a", "ranged-a")) + b".")
            self.assertEqual(patch_monsters(self.read_file, self.identity, "unit"), {})

    def test_patch_rejects_wrong_input_for_mode(self):
        with patch("integrations.monsters.zen_spawners._load_maps", return_value={self.path: (self.before, self.slots)}):
            split = self.assignments(("melee-a", "melee-b"))
            self.assertIn(self.path, patch_monsters(self.read_file, split, "unit"))
            with self.assertRaisesRegex(ValueError, "splits a group"):
                patch_monsters(self.read_file, split, "group")
            cross_role = self.assignments(("melee-a", "ranged-a"))
            with self.assertRaisesRegex(ValueError, "combat-role compatibility"):
                patch_monsters(self.read_file, cross_role, "unit")
            with self.assertRaisesRegex(ValueError, "must permute all supported spawn slots"):
                patch_monsters(self.read_file, {}, "unit")

    def test_reads_zero_mask_in_real_spawner_property_header(self):
        header = bytes.fromhex("0112940803023d020302110304")
        offset, active = _properties(header, 0, len(header))
        self.assertEqual(offset, len(header))
        self.assertEqual(active, list(range(1, 10)) + [30, 31, 33, 37, 99, 103, 121])

    def test_rejects_missing_or_different_base_asset(self):
        with self.assertRaisesRegex(ValueError, "Required base asset missing"):
            catalog_monsters({}.__getitem__)
        with self.assertRaisesRegex(ValueError, "Unsupported base asset hash"):
            catalog_monsters(lambda _: b"")


if __name__ == "__main__":
    unittest.main()
