import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from integrations.pickup_visuals import align_table, apply
from integrations.pickup_visuals.visuals import (
    ACTOR_LEVELS, WorldCell, encode_properties, inventory_levels, prize_visual,
)
from integrations.weapons.movesets import PackageStore
from integrations.weapons.zen import AssetReader, name_batch
from pbzmod import loot


class PickupVisualTest(unittest.TestCase):
    def test_display_color_comes_from_the_prize(self):
        levels = {"text": 8, "material": 13}
        dust = {0: 218, 1: 218, 2: [1.0], 3: 1.0}
        self.assertEqual(prize_visual([{3: [{0: "BaiYing", 1: 1}], 6: 1}], levels), ("weapon", "BaiYing", 18))
        self.assertEqual(prize_visual([{3: [{0: "CaoOuSiXian"}], 6: 1}], levels), ("weapon", "CaoOuSiXian", 18))
        self.assertEqual(prize_visual([{2: [{0: "material"}], 6: 1}], levels), ("item", "material", 13))
        self.assertEqual(prize_visual([{1: [dust], 2: [{0: "text"}], 6: 7}], levels), ("item", "text", 8))
        self.assertEqual(prize_visual([{1: [dust], 6: 7}], levels), ("dust", loot._dust_id([dust]), 7))

    def test_explicit_zero_overrides_survive_property_reencoding(self):
        encoded = encode_properties({1: b"", 3: b"\x09", 135: b"", 171: b"\x12"})
        reader = AssetReader(encoded, [], {}, 0, len(encoded))
        self.assertEqual(reader._property_slots(), [(1, True), (3, False), (135, True), (171, False)])
        self.assertEqual(encoded[reader.position:], b"\x09\x12")


@unittest.skipUnless(os.environ.get("PBZ_TEST_PICKUP_ASSETS") == "1", "requires local PBZ cook and USMAP")
class NativePickupTest(unittest.TestCase):
    ROWS = {
        "Xigu.019.Dust_Small": {
            "source": "map_pickup", "cell": "8IEBCL9KIVTGE7436EXLJ3ECE",
            "actor": "BP_Rubbish_C_UAID_60CF84809909BB9202_1881844662",
        },
        "Xigu.003.Dust_Small": {
            "source": "map_pickup", "cell": "5G43WQTM6331MFR98OIDKR5N3",
            "actor": "BP_Rubbish_C_UAID_60CF84809909BB9202_1473550658",
        },
        "Xigu.001.Dust_Small": {
            "source": "map_pickup", "cell": "BG9VIM4G81OHEG3N9Z5GVO1O4",
            "actor": "BP_Rubbish_C_UAID_CC28AACAD5F9FC4502_2030180263",
        },
        "Xigu.R_01001": {
            "source": "map_pickup", "cell": "BFI1A3JLDZFC68N7MJGD1XI3A",
            "actor": "BP_Rubbish_C_UAID_CC28AACAD5F9625702_1770448387",
        },
        "FuJiZhiLin.004.K_02006": {
            "source": "map_pickup", "cell": "BYC5XC7YZXVINFQBOZURNLZSD",
            "actor": "BP_Rubbish_C_UAID_60CF848217CAD4F902_2037423808",
        },
        "FuJiZhiLin.002.K_02002": {
            "source": "map_pickup", "cell": "12PJQC5PSVFGA45CE6OGHFMNV",
            "actor": "BP_Rubbish_C_UAID_BCFCE704F725EBAA02_1606985006",
        },
        "MeiGuHu.WmB011": {
            "source": "map_pickup", "cell": "10JIT0G6W7D1JQLTS3GUYVOZ6",
            "actor": "BP_Rubbish_b_C_UAID_E89C25A750C706DB02_1203223024",
        },
    }

    @classmethod
    def setUpClass(cls):
        from pbzmod.__main__ import ROOT, readers
        from pbzmod.paths import PAKS_DIR, resolve_paths
        from pbzmod.usmap import load_usmap

        cls.tools = ROOT / ".work"
        cls.helpers, _ = readers(cls.tools)
        game, cls.unrealpak, oodle = resolve_paths()
        cls.store = cls.helpers.IoStore(game / PAKS_DIR / "ProjectPBZ-Windows.utoc", cls.helpers.OodleReader(oodle))
        cls.schemas = load_usmap(cls.tools / "pbz.usmap")
        cls.original = cls.store.read_file(loot.PATH)

    def swap_envelopes(self, target, source, base=None):
        data = bytearray(self.original if base is None else base)
        rows = loot.read_table(data, name_batch(data)[0])
        target_at, source_at = rows[target][0], rows[source][0]
        a, b = bytes(data[target_at:target_at + 8]), bytes(data[source_at:source_at + 8])
        for offset in (0, 10):
            data[target_at + offset:target_at + offset + 8] = b
            data[source_at + offset:source_at + offset + 8] = a
        return bytes(data)

    def test_material_identity_selects_purple_over_the_loot_tier(self):
        row = "Xigu.019.Dust_Small"
        loot_bytes = self.swap_envelopes(row, "Xigu.005.Weapon_Material_04")
        patches, _, report = apply(self.store, self.schemas, loot_bytes, self.ROWS, {}, [row])
        self.assertEqual(len(patches), 1)
        self.assertEqual(report[0]["item"], "Ac_Material_1")
        self.assertEqual(report[0]["before_color"], "blue")
        self.assertEqual(report[0]["after_color"], "purple")
        self.assertEqual(report[0]["after_level"], 9)

    def test_weapon_reuses_native_key_niagara_without_changing_other_exports(self):
        row = "Xigu.003.Dust_Small"
        loot_bytes = self.swap_envelopes(row, "Xigu.001.Long")
        patches, dependencies, report = apply(self.store, self.schemas, loot_bytes, self.ROWS, {}, [row])
        visual = report[0]
        self.assertEqual(visual["item"], "Long")
        self.assertEqual(visual["before_effect"], "/XMVFX/VFXs/Scene/NS_BlueLight_Small")
        self.assertTrue(visual["after_effect"].endswith("/NS_Item_Technicolor"))
        self.assertEqual(visual["after_color"], "orange_red")

        path = visual["package"]
        base_ids = PackageStore(self.store).imports(path)
        original = WorldCell(self.store.read_file(path), self.schemas, base_ids)
        patched = WorldCell(patches[path], self.schemas, dependencies.get(path, base_ids))
        old_pickup, new_pickup = (cell.pickup(visual["actor"]) for cell in (original, patched))
        self.assertEqual(new_pickup.override_end - new_pickup.override_start, 2)
        self.assertEqual(new_pickup.level, 18)
        touched = {new_pickup.actor.index, new_pickup.component.index}
        for first, second in zip(original.exports, patched.exports, strict=True):
            if first.index not in touched:
                self.assertEqual(original.data[first.start:first.end], patched.data[second.start:second.end])
        for cell, pickup in ((original, old_pickup), (patched, new_pickup)):
            fields = cell.reader(pickup.actor).properties(cell.actor_class(pickup.actor))
            values = {name: cell.data[field.start:field.end] for name, field in fields.items() if name not in ACTOR_LEVELS}
            if cell is original:
                untouched = values
            else:
                self.assertEqual(untouched, values)

    def test_native_material_levels(self):
        levels = inventory_levels(self.store, self.schemas)
        self.assertEqual([levels[k] for k in ("Ac_Material_1", "Weapon_Material_26", "K_02006")], [9, 13, 18])

    def test_same_niagara_asset_with_different_override_is_normalized(self):
        row = "MeiGuHu.WmB011"
        patches, deps, report = apply(self.store, self.schemas, self.original, self.ROWS, {}, [row])
        visual = report[0]
        self.assertEqual(visual["before_effect"], visual["after_effect"])
        self.assertEqual(visual["before_level"], visual["after_level"])
        self.assertTrue(visual["effect_changed"])
        path = visual["package"]
        base_ids = PackageStore(self.store).imports(path)
        cell = WorldCell(patches[path], self.schemas, deps.get(path, base_ids))
        target = cell.pickup(visual["actor"])
        self.assertEqual(target.levels, (13, 13, 13))
        stores = cell.reader(target.component).properties("PBZNiagaraComponent")
        override = stores["OverrideParameters"].value
        self.assertEqual(override["ParameterData"].value, [1, 0, 0, 0])
        self.assertEqual(override["SortedParameterOffsets"].value[0][0], "User.UE_Level")

    def test_red_white_and_green_transitions_survive_iostore_packing(self):
        from pbzmod.container import pack

        examples = {
            "Xigu.001.Dust_Small": ("Xigu.001.Long", "white", "orange_red"),
            "Xigu.R_01001": ("Xigu.001.Double", "green", "orange_red"),
            "FuJiZhiLin.004.K_02006": ("Xigu.002.Dust_Small", "orange_red", "white"),
            "FuJiZhiLin.002.K_02002": ("Xigu.R_01004", "orange_red", "green"),
        }
        generated = self.original
        for row, (donor, _, _) in examples.items():
            generated = self.swap_envelopes(row, donor, generated)
        patches, deps, report = apply(self.store, self.schemas, generated, self.ROWS, {}, examples)
        self.assertEqual(len(patches), len(examples))
        self.assertEqual(
            {visual["row"]: (visual["before_color"], visual["after_color"]) for visual in report},
            {row: pair[1:] for row, pair in examples.items()},
        )
        patches[loot.PATH] = align_table(generated, report)
        self.assertEqual(align_table(patches[loot.PATH], report), patches[loot.PATH])
        self.assertEqual(align_table(self.original, [{"row": "Xigu.002.Dust_Small", "after_level": 7}]), self.original)

        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as output:
            utoc = Path(output) / "z_PickupTest_P.utoc"
            pack(self.store, patches, utoc, self.tools / "retoc/retoc.exe", self.helpers,
                 self.unrealpak, {"seed": "native pickup test"}, deps)
            overlay = self.helpers.IoStore(utoc, self.store.codec)
            packed_store = PackageStore(overlay)
            names = name_batch(generated)[0]
            table_readback = loot.read_table(overlay.read_file(loot.PATH), names)
            rewards_before = loot.read_table(generated, names)
            for visual in report:
                path = visual["package"]
                self.assertEqual(overlay.read_file(path), patches[path])
                self.assertEqual(packed_store.imports(path), deps.get(path, PackageStore(self.store).imports(path)))
                cell = WorldCell(overlay.read_file(path), self.schemas, packed_store.imports(path))
                target = cell.pickup(visual["actor"])
                self.assertEqual(target.effect, visual["after_effect"])
                cell.effect_dependency(target)
                envelope = table_readback[visual["row"]][1][1][0]
                original = rewards_before[visual["row"]][1][1][0]
                self.assertEqual(envelope.pop(6), visual["after_level"])
                self.assertEqual(envelope, {index: value for index, value in original.items() if index != 6})
                self.assertEqual(target.levels, (visual["after_level"],) * 3)
                for _, identity in cell.signature(target)[3]:
                    self.assertIsInstance(identity, int)
                    self.assertEqual(identity >> 62, 1)
