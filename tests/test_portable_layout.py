import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from integrations.pickup_visuals.visuals import WorldCell
from integrations.weapons.movesets import PackageStore
from integrations.weapons.zen import name_batch
from pbzmod import loot
from pbzmod.portable import KitStore, NAME, compile_layout
from pbzmod.usmap import parse_usmap


@unittest.skipUnless(os.environ.get("PBZ_TEST_PROFILE_RELEASE"), "requires the prepared white/green seed")
class PortableReleaseTest(unittest.TestCase):
    def test_collected_weapon_moves_whole_dust_reward_to_its_original_boss(self):
        root = Path(os.environ["PBZ_TEST_PROFILE_RELEASE"]).resolve()
        seed = root / "Seeds/白绿拾遗-113"
        retoc = root / "Tools/retoc.exe"
        point = "Xigu.006.Dust_Medium"
        with TemporaryDirectory() as tmp, ZipFile(seed / "kit.zip") as kit:
            run = Path(tmp)
            output = run / "Saved/Paks"
            result = compile_layout(seed, output, seed / "kit.zip", retoc, False, (),
                                    [{"point": point, "enabled": True}])
            boss, = result.granted.values()
            self.assertEqual(result.remaining[boss], point)
            subprocess.run([retoc, "unpack-raw", output / (NAME + ".utoc"), run / "readback"], check=True)
            readback = run / "readback"
            chunks = readback / "chunks"
            m = json.loads(kit.read("manifest.json"))
            store = KitStore(kit, m["ids"])
            actor = m["sources"][point]
            package = actor["package"]
            files = json.loads((readback / "manifest.json").read_bytes())["chunk_paths"]
            self.assertEqual(set(files.values()), {"../../../" + p for p in (
                package, loot.PATH, m["bosses"][boss]["path"])})
            table = (chunks / m["ids"][loot.PATH]).read_bytes()
            rows = loot.read_table(table, name_batch(table)[0])
            base = kit.read("loot.bin")
            original = loot.read_table(base, name_batch(base)[0])
            self.assertEqual(rows[m["aliases"][boss]][1][1], original[point][1][1])
            header, = [p for p in chunks.iterdir() if p.name.endswith("00000006")]
            store.header = header.read_bytes()
            cell = WorldCell((chunks / m["ids"][package]).read_bytes(), parse_usmap(kit.read("fields.usmap")),
                             PackageStore(store).imports(package))
            self.assertTrue(cell.pickup(actor["actor"]).effect.endswith("/NS_Item_Technicolor"))
