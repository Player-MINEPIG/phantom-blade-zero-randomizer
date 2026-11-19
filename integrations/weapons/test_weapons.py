import os
from struct import pack, pack_into
import unittest

from integrations.weapons.movesets import MAIN_TABLE, Imports, PackageStore, build_patches
from integrations.weapons.stats import MULTIPLIER_MAPS, _read_maps, patch_stats, read_config, read_weapons
from integrations.weapons.zen import AssetReader, Field, SingleExport


class CookedPackageTest(unittest.TestCase):
    def test_growing_one_export_updates_its_size(self):
        # The minimal fields this reader needs from a UE5.7 Zen package.
        header = bytearray(168)
        pack_into("<II", header, 0, 0, len(header))
        pack_into("<II", header, 32, 96, 168)
        pack_into("<II", header, 60, 1, 4)
        header[84:90] = b"\x00\x04None"
        pack_into("<QQ", header, 96, 0, 3)
        asset = SingleExport(bytes(header) + b"abc")
        changed = SingleExport(asset.replace([(Field(None, 169, 170), b"xyz")]))
        self.assertEqual(changed.data[changed.start:], b"axyzc")
        self.assertEqual(changed.names, ["None"])

    def test_unversioned_derived_properties_precede_inherited_properties(self):
        schemas = {
            "Child": ("Parent", 2, {0: ("State", (2,)), 1: ("Count", (2,))}),
            "Parent": (None, 1, {0: ("Weapon", (5,))}),
        }
        data = pack("<HBiII", 0x0780, 1, 23, 0, 0)
        reader = AssetReader(data, ["PoJun"], schemas, 0, len(data))
        fields = reader.properties("Child")
        self.assertEqual({name: field.value for name, field in fields.items()}, {"State": None, "Count": 23, "Weapon": "PoJun"})
        self.assertEqual(reader.position, len(data))


@unittest.skipUnless(os.environ.get("PBZ_TEST_WEAPON_ASSETS") == "1", "requires original local game assets and USMAP")
class RealWeaponTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pbzmod.__main__ import ROOT, readers
        from pbzmod.paths import PAKS_DIR, resolve_paths
        from pbzmod.usmap import load_usmap

        tools = ROOT / ".work"
        helpers, _ = readers(tools)
        game, _, oodle = resolve_paths()
        cls.store = helpers.IoStore(game / PAKS_DIR / "ProjectPBZ-Windows.utoc", helpers.OodleReader(oodle))
        cls.schemas = load_usmap(tools / "pbz.usmap")
        cls.weapons = read_weapons(cls.store, cls.schemas)

    def config(self, path, data=None):
        return SingleExport(self.store.read_file(path) if data is None else data)

    def test_physical_damage_profile_is_swapped_in_the_base_and_tempered_configs(self):
        swaps = {"Long": "PoJun", "PoJun": "Long"}
        patches = patch_stats(self.store, self.schemas, swaps)
        long = self.weapons["Long"]
        po_jun = self.weapons["PoJun"]
        self.assertEqual(set(patches), {long.base, long.tempered, po_jun.base})
        for path in (long.base, long.tempered):
            original = self.config(path)
            result = self.config(path, patches[path])
            fields = _read_maps(result, self.schemas, long.config_schema)
            _, base = fields[MULTIPLIER_MAPS[0]]
            self.assertAlmostEqual(base["Damage.Attack.Target.PhysicalDamage"], 1.44)
            self.assertAlmostEqual(base["Damage.Attack.Target.AngerDamage"], 1.141935)
            before = read_config(original, self.schemas, long.config_schema)
            after = read_config(result, self.schemas, long.config_schema)
            for name in before.keys() - set(MULTIPLIER_MAPS):
                a, b = before[name], after[name]
                self.assertEqual(original.data[a.start:a.end], result.data[b.start:b.end])
        self.assertNotIn("Damage.Attack.Target.PhysicalDamage", _read_maps(
            self.config(po_jun.base, patches[po_jun.base]), self.schemas, po_jun.config_schema,
        )[MULTIPLIER_MAPS[0]][1])

    def test_combo_config_moves_to_the_other_weapon_with_its_original_model(self):
        moves = {"BaiYing": "RenOuYanYueDao", "RenOuYanYueDao": "BaiYing"}
        patched, dependencies = build_patches(self.store, self.schemas, {}, moves)
        self.assertEqual(set(patched), {MAIN_TABLE, *(self.weapons[id_].base for id_ in moves)})
        self.assertEqual(set(dependencies), set(patched) - {MAIN_TABLE})
        table = SingleExport(patched[MAIN_TABLE]).reader(self.schemas)
        table.read("10s")
        table_configs = {}
        for _ in range(table.count()):
            table.name()
            fields = table.properties("WeaponData")
            table_configs[fields["ItemId"].value] = fields["WeaponConfig"].value[1]

        store = PackageStore(self.store)
        for target_id, donor_id in moves.items():
            target = self.weapons[target_id]
            donor = self.weapons[donor_id]
            old_target = self.config(target.base)
            old_donor = self.config(donor.base)
            new_donor = self.config(donor.base, patched[donor.base])
            self.assertEqual(table_configs[target_id], donor.base.rsplit("/", 1)[-1].removesuffix(".uasset"))
            a = read_config(old_target, self.schemas, target.config_schema)["Display Data"].value[0]["WeaponClass"]
            before = read_config(old_donor, self.schemas, donor.config_schema)
            after = read_config(new_donor, self.schemas, donor.config_schema)
            expected_package, expected_hash = Imports(old_target, store.imports(target.base)).resolve(a.value)
            new_actor = after["Display Data"].value[0]["WeaponClass"]
            actual_package, actual_hash = Imports(new_donor, dependencies[donor.base]).resolve(new_actor.value)
            self.assertEqual(dependencies[donor.base][actual_package], store.imports(target.base)[expected_package])
            self.assertEqual(actual_hash, expected_hash)
            for field in ("Equip Abilities", "Weapon Combos"):
                self.assertEqual(after[field].value, before[field].value)
            self.assertEqual("Linked Anim Layers" in after, "Linked Anim Layers" in before)
