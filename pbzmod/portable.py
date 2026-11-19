"""Rebuild one campaign's loot, colours and optional modules from its offline seed kit."""

import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from integrations.pickup_visuals import align_table, apply as apply_visuals
from integrations.pickup_visuals.visuals import INVENTORY, MAP_ROOT, TEMPLATES
from integrations.weapons.zen import name_batch
from . import loot
from .container import chunk_id, subset_header
from .reward_layout import resolve_layout
from .usmap import parse_usmap


NAME = "z_PBZSeedRandomizer_P"
HEADER_CHUNK = bytes(11) + b"\x06"


def dump(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf8")


def write_kit(path, store, usmap, recipe):
    """Save only the packages and tables needed to cook this seed's possible layouts."""
    from integrations.grants import pooled

    grants = recipe["grants"]
    boss_files, boss_deps = pooled.rewrite_changed(store, grants, dict.fromkeys(grants))
    extras = recipe["extras"]
    sources = recipe["sources"]
    cells = {Path(p).stem: p for p in store.files if p.startswith(MAP_ROOT) and "/_Generated_/" in p}
    originals = {INVENTORY}
    originals.update(cells[t.cell] for t in TEMPLATES.values())
    originals.update(s["package"] for s in sources.values() if s["source"] == "map_pickup")
    paths = sorted(originals | extras.keys() | boss_files.keys() | {loot.PATH})
    ids = {p: chunk_id(store, store.files[p]).hex() for p in paths}
    header_index = next(i for i in range(store.count) if chunk_id(store, i)[-1] == 6)
    package_ids = sorted(int.from_bytes(bytes.fromhex(cid)[:8], "little") for cid in ids.values())
    header = subset_header(store.read_chunk(header_index), package_ids, 0, {})
    manifest = {k: recipe[k] for k in ("permutation", "aliases", "allowed", "texts", "visualRows", "sources")}
    manifest.update(schema=1, ids=ids, extras=sorted(extras), extraDeps=recipe["extraDeps"],
                    bosses={k: {"path": g.path, "item": g.item} for k, g in grants.items()}, bossDeps=boss_deps)
    with ZipFile(path, "x", ZIP_DEFLATED, compresslevel=5) as kit:
        kit.writestr("manifest.json", dump(manifest))
        kit.write(usmap, "fields.usmap")
        kit.writestr("store.bin", header)
        kit.writestr("loot.bin", recipe["expanded"])
        for p in sorted(originals):
            kit.writestr("base/" + ids[p], store.read_file(p))
        for prefix, patches in (("extras/", extras), ("boss/", boss_files)):
            for p, payload in patches.items():
                kit.writestr(prefix + ids[p], payload)


class KitStore:
    """Present the reviewed subset in the form expected by the native asset adapters."""

    def __init__(self, archive, ids):
        self.archive = archive
        self.ids = ids
        self.files = {p: i for i, p in enumerate(ids)}
        self.count = len(ids) + 1
        self.header = archive.read("store.bin")
        self.data = bytes(144) + b"".join(bytes.fromhex(x) for x in ids.values()) + HEADER_CHUNK

    def read_chunk(self, index):
        if index != self.count - 1:
            raise ValueError("Expected the package store header")
        return self.header

    def read_file(self, path):
        return self.archive.read("base/" + self.ids[path])


def _write_container(patches, dependencies, store, base_paks, output, retoc):
    """Use the same archive name/ID as the original seed in an isolated UserDir."""
    if output.exists() and any(output.iterdir()):
        raise ValueError("目标资源目录必须为空")
    output.mkdir(exist_ok=True, parents=True)
    base_utoc = base_paks / (NAME + ".utoc")
    cid = base_utoc.read_bytes()[56:64]
    package_ids = {p: int.from_bytes(bytes.fromhex(store.ids[p])[:8], "little") for p in patches}
    header = subset_header(store.header, sorted(package_ids.values()), int.from_bytes(cid, "little"),
                           {package_ids[p]: deps for p, deps in dependencies.items() if p in patches})
    payloads = {store.ids[p]: data for p, data in patches.items()}
    payloads[(cid + HEADER_CHUNK[8:]).hex()] = header
    utoc = output / (NAME + ".utoc")
    with TemporaryDirectory(dir=output.parent) as tmp:
        root = Path(tmp)
        source = root / "input"
        chunks = source / "chunks"
        chunks.mkdir(parents=True)
        for key, data in payloads.items():
            (chunks / key).write_bytes(data)
        manifest = {"version": "ReplaceIoChunkHashWithIoHash", "mount_point": "../../../",
                    "chunk_paths": {store.ids[p]: "../../../" + p for p in patches}}
        (source / "manifest.json").write_bytes(dump(manifest))
        for args in (["pack-raw", source, utoc], ["unpack-raw", utoc, root / "readback"]):
            subprocess.run([retoc, *args], check=True, stdout=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if utoc.read_bytes()[56:64] != cid:
            raise ValueError("Container ID changed")
        verified = root / "readback" / "chunks"
        if {p.name.lower() for p in verified.iterdir()} != payloads.keys():
            raise ValueError("生成资源的块目录回读不一致")
        for key, data in payloads.items():
            if (verified / key).read_bytes() != data:
                raise ValueError("生成资源回读不一致：" + key)
    shutil.copyfile(base_utoc.with_suffix(".pak"), utoc.with_suffix(".pak"))


def compile_layout(seed_dir, out_paks, kit_path, retoc, enabled, vanilla_claimed, claims, protected=()):
    """Compile a new complete native layout; never opens a game save or the retail executable."""
    with ZipFile(kit_path) as kit:
        m = json.loads(kit.read("manifest.json"))
        if m.get("schema") != 1:
            raise ValueError("不支持此种子配方版本")
        layout = resolve_layout(m["permutation"], enabled=enabled, vanilla_claimed=vanilla_claimed,
                                claims=claims, protected=protected)
        store = KitStore(kit, m["ids"])
        expanded = kit.read("loot.bin")
        names = name_batch(expanded)[0]
        texts, allowed = set(m["texts"]), set(m["allowed"])
        prizes = loot.select(expanded, names, allowed, text_items=texts)
        alias = m["aliases"]
        origins = {alias.get(p, p): alias.get(q, q) for p, q in layout.origins.items()}
        physical = {p: prizes[q].item for p, q in origins.items()}
        modified = loot.apply_reviewed(expanded, names, allowed, {p: prizes[p] for p in physical},
                                       physical, text_items=texts, origins=origins)
        patches = {p: kit.read("extras/" + store.ids[p]) for p in m["extras"]} if enabled else {}
        deps = dict(m["extraDeps"]) if enabled else {}
        for point, grant in m["bosses"].items():
            if physical[alias[point]] != grant["item"]:
                p = grant["path"]
                patches[p] = kit.read("boss/" + store.ids[p])
                deps[p] = m["bossDeps"][p]
        visual_rows = set(m["visualRows"]) if enabled else {p for p, q in origins.items() if p != q}
        visual_rows.difference_update(alias.get(p, p) for p in protected)
        visual, visual_deps, report = apply_visuals(store, parse_usmap(kit.read("fields.usmap")),
                                                   modified, m["sources"], patches, visual_rows)
        patches.update(visual)
        deps.update(visual_deps)
        # Unused virtual Boss rows are inert when the whole campaign is back to vanilla.
        patches[loot.PATH] = align_table(modified, report)
        _write_container(patches, deps, store, Path(seed_dir) / "Saved/Paks", Path(out_paks), Path(retoc))
        return layout
