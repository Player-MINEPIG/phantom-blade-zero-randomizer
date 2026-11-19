import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from pbzmod import paths
from tools import prepare_tools


class LocalPathTests(unittest.TestCase):
    def test_detects_steam_library_and_nonstandard_oodle_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            steam = root / "Steam"
            (steam / "steamapps").mkdir(parents=True)
            library = root / "Separate Steam Library"
            vdf_path = str(library).replace("\\", "\\\\")
            (steam / "steamapps/libraryfolders.vdf").write_text(f'"libraryfolders" {{ "1" {{ "path" "{vdf_path}" }} }}', encoding="utf-8")
            game = library / "steamapps/common/Local game folder"
            paks = game / paths.PAKS_DIR
            paks.mkdir(parents=True)
            for filename in paths.CONTAINERS:
                (paks / filename).touch()
            (library / "steamapps" / paths.APP_MANIFEST).write_text('"AppState" { "installdir" "Local game folder" }', encoding="utf-8")

            ue = root / "UE_5.7"
            unrealpak = ue / "Engine/Binaries/Win64/UnrealPak.exe"
            unrealpak.parent.mkdir(parents=True)
            unrealpak.touch()
            oodle = ue / "Engine/Source/Programs/UnrealBuildTool/bin/Development" / paths.OODLE
            oodle.parent.mkdir(parents=True)
            oodle.touch()
            expected = (game.resolve(), unrealpak.resolve(), oodle.resolve())

            with patch.object(paths, "_steam_candidates", return_value=iter([steam])), patch.object(paths, "_ue_candidates", return_value=iter([ue])):
                self.assertEqual(paths.resolve_paths(), expected)
            self.assertEqual(paths.resolve_paths(game, ue), expected)
            with self.assertRaisesRegex(FileNotFoundError, "containers were not found"):
                paths.resolve_paths(root / "wrong-game", ue)
            with self.assertRaisesRegex(FileNotFoundError, "UnrealPak.exe"):
                paths.resolve_paths(game, root / "wrong-ue")


class PrepareToolsTests(unittest.TestCase):
    def test_downloads_then_reuses_verified_assets_and_selects_one_zip_entry(self):
        executable = b"retoc-test"
        archive = BytesIO()
        with ZipFile(archive, "w") as zip_file:
            zip_file.writestr("retoc.exe", executable)
            zip_file.writestr("LICENSE", b"other archive member")
        artifacts = {"resources_reader.py": b"reader", "pak_reader.py": b"pak", "pbz.usmap": b"usmap", "retoc.zip": archive.getvalue()}
        urls = {f"https://example.invalid/{name}": data for name, data in artifacts.items()}
        manifest = {name: (f"https://example.invalid/{name}", hashlib.sha256(data).hexdigest()) for name, data in artifacts.items()}
        exe_hash = hashlib.sha256(executable).hexdigest()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(prepare_tools, "DOWNLOADS", manifest), patch.object(prepare_tools, "RETOC_SHA256", exe_hash), patch.object(
                prepare_tools, "urlopen", side_effect=lambda request, *, timeout: BytesIO(urls[request.full_url]),
            ) as download:
                prepare_tools.prepare(root)
                prepare_tools.prepare(root)
                self.assertEqual(download.call_count, len(artifacts))
            for name, data in artifacts.items():
                self.assertEqual((root / name).read_bytes(), data)
            self.assertEqual((root / "retoc/retoc.exe").read_bytes(), executable)
            self.assertFalse((root / "retoc/LICENSE").exists())

    def test_download_hash_mismatch_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tool.py"
            path.write_bytes(b"existing data")
            expected = hashlib.sha256(b"trusted replacement").hexdigest()
            with patch.object(prepare_tools, "urlopen", return_value=BytesIO(b"incorrect bytes")):
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    prepare_tools._download(path, "https://example.invalid/tool.py", expected)
            self.assertEqual(path.read_bytes(), b"existing data")


if __name__ == "__main__":
    unittest.main()
