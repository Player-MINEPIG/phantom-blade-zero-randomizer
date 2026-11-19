"""Fetch the pinned asset-reading tools into the project's .work directory."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


WORK = Path(__file__).resolve().parents[1] / ".work"
PBZ_EDITOR = "https://raw.githubusercontent.com/qry6868/PBZ-Editor/5fdb13483cefde94e6a2f3dba3d258c84e747582/pbz_editor/"
DOWNLOADS = {
    "resources_reader.py": (
        PBZ_EDITOR + "resources_reader.py",
        "76a42b871da05cac9a20c5fed7540a7ac8d39d55f28d4915b1737b57306ba747",
    ),
    "pak_reader.py": (
        PBZ_EDITOR + "pak_reader.py",
        "f455214ef815e1eb1edf2b997e1cb0deab1b0891cdd73a0f9c80ca6c36581ad1",
    ),
    "retoc.zip": (
        "https://github.com/trumank/retoc/releases/download/v0.1.5/retoc_cli-x86_64-pc-windows-msvc.zip",
        "cc036b06ad3bdcf7003690b00d82719980c374e48a95bf0654f9959148d263aa",
    ),
    "pbz.usmap": (
        "https://github.com/KintaroModding/phantombladezero_pbzusmap/releases/download/v1.1/ProjectPBZ-5.7.4-302256-full.usmap",
        "77a983a7f9df632a3e133487b1eafc2483185f9f98548303386b69dbc9701d78",
    ),
}
RETOC_SHA256 = "a145f3557ec60b163ed1b78b2f380232d2753fa30350c8013c98e171db3ae7e7"
DOWNLOAD_LIMIT = 16 * 1024 * 1024


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = NamedTemporaryFile(mode="wb", dir=path.parent, delete=False)
    temp_path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(data)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_matching(path, digest):
    if path.is_file() and path.stat().st_size <= DOWNLOAD_LIMIT:
        data = path.read_bytes()
        if sha256(data).hexdigest() == digest:
            return data
    return None


def _download(path, url, digest):
    data = _read_matching(path, digest)
    if data is None:
        request = Request(url, headers={"User-Agent": "pbz-randomizer-tools/1"})
        with urlopen(request, timeout=30) as response:
            data = response.read(DOWNLOAD_LIMIT + 1)
        if len(data) > DOWNLOAD_LIMIT or sha256(data).hexdigest() != digest:
            raise ValueError(f"SHA-256 mismatch for {path.name}")
        _write(path, data)
    return data


def prepare(work=WORK):
    folder = Path(work)
    for name, (url, digest) in DOWNLOADS.items():
        if name != "retoc.zip":
            _download(folder / name, url, digest)
    archive = _download(folder / "retoc.zip", *DOWNLOADS["retoc.zip"])

    executable = folder / "retoc" / "retoc.exe"
    if _read_matching(executable, RETOC_SHA256) is None:
        with ZipFile(BytesIO(archive)) as release:
            member = release.getinfo("retoc.exe")
            if member.file_size > DOWNLOAD_LIMIT:
                raise ValueError("Unexpected retoc executable size")
            data = release.read(member)
        if sha256(data).hexdigest() != RETOC_SHA256:
            raise ValueError("SHA-256 mismatch for retoc.exe")
        _write(executable, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        prepare()
    except (BadZipFile, KeyError, OSError, ValueError) as error:
        parser.exit(1, f"Tool preparation failed: {error}\n")
    print(f"Verified the pinned asset tools in {WORK}")


if __name__ == "__main__":
    main()
