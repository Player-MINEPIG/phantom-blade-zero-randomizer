import os
from struct import pack, unpack_from
import unittest

from integrations.weapons.movesets import PackageStore, _chunk_package_id
from pbzmod.pickup_sources import DEVICE_ROOT, _package, _read_fields


@unittest.skipUnless(os.environ.get("PBZ_TEST_GRANT_ASSETS") == "1", "requires the original local game assets")
class NativeChestSequenceTest(unittest.TestCase):
    def test_default_sequence_calls_pickup_items_and_collects_before_granting(self):
        from pbzmod.__main__ import ROOT, readers
        from pbzmod.paths import PAKS_DIR, resolve_paths
        from pbzmod.usmap import load_usmap

        helpers, _ = readers(ROOT / ".work")
        game, _, oodle = resolve_paths()
        store = helpers.IoStore(game / PAKS_DIR / "ProjectPBZ-Windows.utoc", helpers.OodleReader(oodle))
        schemas = load_usmap(ROOT / ".work" / "pbz.usmap")
        chest_path = DEVICE_ROOT + "BP_Chest.uasset"
        sequence_path = "ProjectPBZ/Content/PBZContent/Sequencer/Switch/LS_Interact_Chest.uasset"
        chest = store.read_file(chest_path)
        names, hashes, exports = _package(chest)
        default = next(export for export in exports if export.name == "Default__BP_Chest_C")
        fields = dict(_read_fields(chest, names, schemas, default, "BP_Chest_C", {"LevelSequenceAsset"}))
        sequence_ref = fields["LevelSequenceAsset"]
        self.assertLess(sequence_ref, 0)
        imports_offset = unpack_from("<I", chest, 7 * 4)[0]
        pointer = unpack_from("<Q", chest, imports_offset + 8 * (-sequence_ref - 1))[0]
        self.assertEqual(pointer >> 62, 2)
        package_index = (pointer >> 32) & 0x3FFFFFFF
        self.assertEqual(
            PackageStore(store).imports(chest_path)[package_index],
            _chunk_package_id(store, sequence_path),
        )

        sequence = store.read_file(sequence_path)
        seq_names, _, seq_exports = _package(sequence)
        sequence_asset = next(export for export in seq_exports if export.name == "LS_Interact_Chest")
        self.assertEqual(sequence_asset.public_hash, hashes[pointer & 0xFFFFFFFF])
        director = next(
            export for export in seq_exports if export.name == "ExecuteUbergraph_LS_Interact_Chest_DirectorBP"
        )
        pickup = next(export for export in exports if export.name == "Pickup Items")

        # These cooked UE 5.7 offsets identify the calls in Steam build 26367565.
        # EX_LocalVirtualFunction, function FName, EX_EndFunctionParms.
        pickup_call = pack("<BIIB", 0x45, seq_names.index("Pickup Items"), 0, 0x16)
        collect_call = pack("<BIIB", 0x45, names.index("Collect Items"), 0, 0x16)
        self.assertTrue(sequence.startswith(pickup_call, director.start + 2686, director.end))
        self.assertTrue(chest.startswith(collect_call, pickup.start + 1630, pickup.end))
