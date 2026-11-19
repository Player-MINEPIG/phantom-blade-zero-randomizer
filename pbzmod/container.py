"""Build a small IoStore overlay with the original package import dependencies."""

from bisect import bisect_left
import json
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory


def chunk_id(store, index):
    start = 144 + index * 12
    return store.data[start : start + 12]


def subset_header(original, package_ids, container_id, dependencies):
    magic, version, _, count = struct.unpack_from("<IIQI", original)
    if magic != 0x496F436E or version != 5:
        raise ValueError("Unexpected PBZ package store header")
    ids = struct.unpack_from(f"<{count}Q", original, 20)
    size_pos = 20 + count * 8
    (size,) = struct.unpack_from("<I", original, size_pos)
    blob = memoryview(original)[size_pos + 4 : size_pos + 4 + size]
    table = bytearray(16 * len(package_ids))
    for i, pid in enumerate(package_ids):
        old = bisect_left(ids, pid)
        if old == count or ids[old] != pid:
            raise ValueError(f"Missing package entry {pid:x}")
        for offset, stride in ((0, 8), (8, 20)):
            source = old * 16 + offset
            n, relative = struct.unpack_from("<II", blob, source)
            target = i * 16 + offset
            if offset == 0 and pid in dependencies:
                imports = dependencies[pid]
                struct.pack_into(
                    "<II", table, target, len(imports), len(table) - target
                )
                table.extend(struct.pack(f"<{len(imports)}Q", *imports))
                continue
            if n:
                start = source + relative
                end = start + n * stride
                if end > len(blob):
                    raise ValueError("Package dependency outside original store")
                struct.pack_into("<II", table, target, n, len(table) - target)
                table.extend(blob[start:end])
    header = struct.pack("<IIQI", magic, version, container_id, len(package_ids))
    header += struct.pack(f"<{len(package_ids)}Q", *package_ids)
    header += struct.pack("<I", len(table)) + table
    # Empty optional segment, redirect name map, localized packages and redirects.
    header += bytes(5 * 4)
    return header + struct.pack("<qqI", len(header) + 16, 4, 0)


def pack(
    store, patches, utoc, retoc, reader, unrealpak, seed_info, dependency_overrides=None
):
    utoc = Path(utoc).resolve()
    retoc = Path(retoc).resolve()
    unrealpak = Path(unrealpak).resolve()
    if not patches:
        raise ValueError("Selected settings did not produce any gameplay changes")
    source_index = next(i for i in range(store.count) if chunk_id(store, i)[-1] == 6)
    original = store.read_chunk(source_index)
    with TemporaryDirectory(dir=utoc.parent) as tmp:
        root = Path(tmp)
        chunks = root / "chunks"
        chunks.mkdir()
        paths = {}
        ids = []
        dependencies = {}
        for path in sorted(patches):
            cid = chunk_id(store, store.files[path])
            if cid[-1] != 1:
                raise ValueError(f"Not an export bundle: {path}")
            (chunks / cid.hex()).write_bytes(patches[path])
            paths[cid.hex()] = "../../../" + path
            pid = int.from_bytes(cid[:8], "little")
            ids.append(pid)
            if path in (dependency_overrides or {}):
                dependencies[pid] = dependency_overrides[path]
        manifest = {
            "chunk_paths": paths,
            "version": "ReplaceIoChunkHashWithIoHash",
            "mount_point": "../../../",
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf8")

        # The writer derives the container ID from the final archive basename.
        def write():
            subprocess.run([retoc, "pack-raw", root, utoc], check=True)

        write()
        with utoc.open("rb") as f:
            f.seek(56)
            cid = f.read(8)
        name = (cid + bytes.fromhex("00000006")).hex()
        header = subset_header(
            original, sorted(ids), int.from_bytes(cid, "little"), dependencies
        )
        (chunks / name).write_bytes(header)
        write()
        result = reader.IoStore(utoc, store.codec)
        if set(result.files) != set(patches) or any(
            result.read_file(p) != b for p, b in patches.items()
        ):
            raise ValueError("Cooked package readback failed")
        header_index = next(
            i for i in range(result.count) if chunk_id(result, i).hex() == name
        )
        if result.read_chunk(header_index) != header:
            raise ValueError("Package store readback failed")
        subprocess.run([retoc, "info", utoc], check=True)
        seedfile = root / "seed.json"
        seedfile.write_text(json.dumps(seed_info, ensure_ascii=False), encoding="utf8")
        response = root / "files.txt"
        response.write_text(
            f'"{seedfile}" "../../../ProjectPBZ/Content/PBZSeedRandomizer/seed.json"\n',
            encoding="utf-8-sig",
        )
        pak = utoc.with_suffix(".pak")
        subprocess.run(
            [unrealpak, pak, f"-Create={response}", f"-abslog={root/'pak.log'}"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [unrealpak, pak, "-Test", f"-abslog={root/'test.log'}"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
