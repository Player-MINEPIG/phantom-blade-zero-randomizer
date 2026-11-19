"""Patch direct weapon rewards in reviewed Phantom Blade Zero quest flow packages."""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from struct import pack, pack_into, unpack_from

from integrations.weapons.zen import name_batch


FLOW_GRAPH = "ProjectPBZ/Content/PBZContent/Blueprint/FlowGraph/"
QUEST = FLOW_GRAPH + "QuestFlowGraph/"
GRANT_CLASS = "/Game/PBZContent/Blueprint/FlowGraph/FlowGraphNode/AddWeaponItem"
DOMAIN = "direct_weapon_grant"
REVIEWED = {
    # Location, expected original item, and original Steam 26367565 package hash.
    "DDSD/BPF_YuMianDeath": ("JadeDualChakram", "25e3ee2b6771887ea3c9191ce1df67f19c7ed41f9f65691c44cb632522666bff"),
    "DDSD/FogDoor/BPF_Fogdoor_HengDaoKe": ("HorizontalBlade", "279a5ba53759f80757ae49e1a81768fa5f70d938a0aedb06bcbdf0d3e3b75980"),
    "HuXinMiMi/BPF_DangHuiDeath": ("CaoOuSiXian", "713e5d8f9e23eb832aff4490b2cd76bd0f0f4d99e1ab11accb1eea52b6b8f757"),
    "HuXinMiMi/BPF_FengXueDaoKe_Death": ("BaiYing", "652c85fcbc4d83d8a333e87364cfdfe86272bc14b687434aa4c337ea4694ef8c"),
    "FuJiZhiLin/BPF_JianChiDeath": ("ChiZheCanJian", "f7806d66962f3c4fd3bce68e379fde5ffe1f670ca3df6bd04ac14cdebf31abe4"),
    "FuJiZhiLin/BPF_QuanChiDeath": ("TieGongZhuQuanTao", "a537495244a898111d6f00fd81f69d41efc73f6c9868cd88183b23374d3223b0"),
    "XiMengShanZhuang/BPF_XiPiaoGuaiWu_Death": ("RenOuYanYueDao", "6cc991ba1b72407295978358b57433f8d4877687093068815781cba6ffcb8172"),
}

MAIN_FRAGMENT = bytes.fromhex("01040504")
SHADOW_FRAGMENT = bytes.fromhex("01020604")


@dataclass(frozen=True)
class Grant:
    id: str
    path: str
    item: str
    category: str
    encounter: str

    def reward(self):
        return {"id": self.id, "item": self.item, "source": "boss", "encounter": self.encounter, "compatibility": DOMAIN}


@dataclass(frozen=True)
class Export:
    offset: int
    size: int
    record: int


class QuestPackage:
    def __init__(self, data):
        self.data = data
        self.summary = unpack_from("<15I", data)
        self.names, self.name_end = name_batch(data)
        self.header = self.summary[1]
        first, stop = self.summary[8:10]
        if (
            self.summary[0] or self.summary[13:15] != (stop, stop)
            or not self.name_end < first < stop < self.header < len(data)
            or (stop - first) % 72
        ):
            raise ValueError("Unexpected grant export map layout")
        self.exports = []
        grants = []
        for position in range(first, stop, 72):
            offset, size, name, number, _, export_class = unpack_from("<QQIIQQ", data, position)
            entry = Export(offset, size, position)
            self.exports.append(entry)
            if self.names[name] == "AddWeaponItem_C" and number:
                grants.append(entry)
                if not self._import_is_grant(export_class):
                    raise ValueError("Weapon grant export belongs to a different class")
        if len(grants) != 1:
            raise ValueError("Expected one direct weapon grant in the reviewed quest")
        self.grant = grants[0]
        if self.header + max(export.offset + export.size for export in self.exports) != len(data):
            raise ValueError("Quest package size differs from the export map")

    def _import_is_grant(self, export_class):
        if export_class >> 62 != 2:
            return False
        packages, _ = name_batch(self.data, self.summary[12])
        return packages[(export_class >> 32) & 0x3fffffff] == GRANT_CLASS

    def read_grant(self):
        pos = self.header + self.grant.offset
        shape = self.data[pos:pos + 4]
        tail = self.data[pos + 4:pos + 8]
        if shape not in (MAIN_FRAGMENT, SHADOW_FRAGMENT) or tail not in (b"\x05\x02\x01\x03", b"\x05\x02\x01\x05"):
            raise ValueError("Unexpected unversioned grant properties")
        index, number = unpack_from("<II", self.data, pos + 8)
        main = shape == MAIN_FRAGMENT
        guid_start = pos + 20 + main
        if (main and self.data[pos + 16] != 1) or guid_start + 16 > pos + self.grant.size:
            raise ValueError("Unexpected direct weapon payload")
        guid = self.data[guid_start:guid_start + 16].hex()
        if not any(self.data[guid_start:guid_start + 16]):
            raise ValueError("Direct weapon node has no GUID")
        item = self.names[index] if number == 0 else f"{self.names[index]}_{number - 1}"
        return item, main, guid, index, number

    def _name_payload(self, index):
        names = self.names
        hashes = 76
        headers = hashes + len(names) * 8
        start = headers + len(names) * 2
        for i in range(index + 1):
            head = self.data[headers + i * 2:headers + i * 2 + 2]
            length = int.from_bytes(head, "big")
            width = (length & 0x7fff) * (2 if length & 0x8000 else 1)
            end = start + width
            if i == index:
                return self.data[hashes + i * 8:hashes + i * 8 + 8], head, self.data[start:end]
            start = end
        raise ValueError("Missing weapon name payload")

    def _ensure_name(self, source, index):
        name = source.names[index]
        if name in self.names:
            return bytearray(self.data[:self.header]), self.names.index(name)
        source_hash, descriptor, text = source._name_payload(index)
        version = self.data[68:76]
        if version != source.data[68:76]:
            raise ValueError("Incompatible quest package name hashes")
        count, strings_size = unpack_from("<II", self.data, 60)
        headers_start = 76 + count * 8
        strings_start = headers_start + count * 2
        new_name_batch = (
            pack("<II", count + 1, strings_size + len(text)) + version
            + self.data[76:headers_start] + source_hash
            + self.data[headers_start:strings_start] + descriptor
            + self.data[strings_start:self.name_end] + text
        )
        old_padding, = unpack_from("<Q", self.data, self.name_end)
        if old_padding != -self.name_end % 8:
            raise ValueError("Unexpected quest package padding")
        header = bytearray(self.data[:60] + new_name_batch)
        new_padding = -len(header) % 8
        header.extend(pack("<Q", new_padding) + bytes(new_padding))
        header.extend(self.data[self.name_end + 8 + old_padding:self.header])
        change = len(header) - self.header
        pack_into("<I", header, 4, len(header))
        pack_into("<9I", header, 24, *(offset + change for offset in self.summary[6:15]))
        return header, count

    def assign(self, source):
        _, main, guid, _, _ = self.read_grant()
        item, source_main, _, source_index, instance = source.read_grant()
        header, index = self._ensure_name(source, source_index)
        pos = self.grant.offset
        original = self.data[self.header:]
        replacement = (MAIN_FRAGMENT if source_main else SHADOW_FRAGMENT) + original[pos + 4:pos + 8]
        replacement += pack("<II", index, instance)
        if source_main:
            replacement += b"\x01"
        body = original[:pos] + replacement + original[pos + 16 + main:]
        size_change = int(source_main) - int(main)
        header_change = len(header) - self.header
        for export in self.exports:
            if export == self.grant:
                pack_into("<Q", header, export.record + header_change + 8, export.size + size_change)
            elif export.offset > pos:
                pack_into("<Q", header, export.record + header_change, export.offset + size_change)
        result = bytes(header) + body
        rewritten = QuestPackage(result)
        if rewritten.read_grant()[:3] != (item, source_main, guid):
            raise ValueError("Direct weapon grant readback disagrees with the plan")
        for before, after in zip(self.exports, rewritten.exports, strict=True):
            if before == self.grant:
                continue
            old_payload = original[before.offset:before.offset + before.size]
            new_start = rewritten.header + after.offset
            if old_payload != result[new_start:new_start + after.size]:
                raise ValueError("A different quest export changed while editing the grant")
        return result


def _load(store, path):
    name = path.removeprefix(QUEST).removesuffix(".uasset")
    expected, digest = REVIEWED[name]
    data = store.read_file(path)
    if sha256(data).hexdigest() != digest:
        raise ValueError(f"Unsupported version of weapon grant {path}")
    package = QuestPackage(data)
    if package.read_grant()[0] != expected:
        raise ValueError(f"Unexpected original weapon reward at {path}")
    return package


def scan(store, *, exclude_items=()):
    """Return reviewed single-node grants keyed by their persistent FlowNode GUID."""
    grants = {}
    for location, (item, _) in REVIEWED.items():
        if item in exclude_items:
            continue
        path = QUEST + location + ".uasset"
        parsed = _load(store, path)
        _, main, guid, _, _ = parsed.read_grant()
        id_ = f"grant:{guid}"
        if id_ in grants:
            raise ValueError(f"Duplicate direct weapon grant GUID: {guid}")
        category = "main_weapon" if main else "shadow_weapon"
        encounter = "encounter:" + PurePosixPath(location).name
        grants[id_] = Grant(id_, path, item, category, encounter)
    return grants


def apply(store, grants, assignments):
    """Return cooked package paths and bytes for the changed grant assignments."""
    from_items = {grant.item: grant for grant in grants.values()}
    targets = {id_: assignments.get(id_, grant.item) for id_, grant in grants.items()}
    if Counter(targets.values()) != Counter(grant.item for grant in grants.values()):
        raise ValueError("Direct weapon assignments must preserve the reviewed weapon pool")
    packages = {}
    patches = {}
    for id_, item in targets.items():
        target = grants[id_]
        if item == target.item:
            continue
        source = from_items[item]
        for grant in (target, source):
            if grant.path not in packages:
                packages[grant.path] = _load(store, grant.path)
        patches[target.path] = packages[target.path].assign(packages[source.path])
    return patches
