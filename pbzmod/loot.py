"""Decode LevelLootTableData using its build-specific unversioned row layout."""

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
import struct

PATH = "ProjectPBZ/Content/PBZContent/DataTable/DT_LevelLootDataTable.uasset"
ORIGINAL = "8afd310c1deef60dd3eae7418d40f17c4990ea2d26f554c68652df1dabe30460"
INJECTED_REWARD_ROWS = frozenset(f"LootItems_C_{index}" for index in range(1001, 1008))

# Field order, including inherited Probability at the end, from the 302256 USMAP.
FIELDS = {
    "row": ("name", "array:level"),
    "level": (
        "i",
        "array:dust",
        "array:item",
        "array:weapon",
        "array:medicine",
        "array:accessory",
        "B",
    ),
    "dust": ("i", "i", "array:f", "f"),
    "item": ("name", "i", "i", "f"),
    "weapon": ("name", "B", "f"),
    "medicine": ("name", "i", "i", "array:f", "f"),
    "accessory": ("name", "f"),
}


class Cursor:
    def __init__(self, data, names):
        self.data = data
        self.names = names
        self.pos = struct.unpack_from("<I", data, 4)[0]

    def take(self, fmt):
        fmt = "<" + fmt
        result = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += struct.calcsize(fmt)
        return result[0] if len(result) == 1 else result

    def value(self, kind):
        if kind == "name":
            index, number = self.take("II")
            base = self.names[index]
            return base if not number else f"{base}_{number - 1}"
        if kind.startswith("array:"):
            count = self.take("i")
            if not 0 <= count <= 65535:
                raise ValueError(f"Invalid array at {self.pos - 4}")
            return [self.value(kind[6:]) for _ in range(count)]
        if kind not in FIELDS:
            return self.take(kind)
        indexes = []
        index = bits = 0
        while True:
            fragment = self.take("H")
            index += fragment & 127
            for _ in range(fragment >> 9):
                if index >= len(FIELDS[kind]):
                    raise ValueError(f"Unknown {kind} property {index} at {self.pos}")
                masked = bool(fragment & 128)
                indexes.append((index, bits if masked else None))
                bits += masked
                index += 1
            if fragment & 256:
                break
        size = (
            0
            if bits == 0
            else 1 if bits <= 8 else 2 if bits <= 16 else ((bits + 31) // 32) * 4
        )
        mask = int.from_bytes(self.data[self.pos : self.pos + size], "little")
        self.pos += size
        return {
            i: self.value(FIELDS[kind][i])
            for i, bit in indexes
            if bit is None or not mask & (1 << bit)
        }


@dataclass(frozen=True)
class Prize:
    row: str
    item: str
    category: str
    outer: int
    inner: int


def read_table(data, names):
    c = Cursor(data, names)
    if data[c.pos : c.pos + 10] != bytes.fromhex("0003fbffffff00000000"):
        raise ValueError("Unrecognized LevelLoot table preamble")
    c.pos += 10
    count = c.take("I")
    rows = {}
    for _ in range(count):
        start = c.pos
        name = c.value("name")
        if name in rows:
            raise ValueError(f"Duplicate loot row {name}")
        fields = c.value("row")
        rows[name] = (start, fields)
    if c.pos != len(data):
        raise ValueError(f"Unparsed bytes after last loot row: {len(data)-c.pos}")
    return rows


def _dust_id(entries):
    if len(entries) != 1:
        return None
    entry = entries[0]
    minimum, maximum = entry.get(0, 0), entry.get(1, 0)
    curve = entry.get(2, [])
    if entry.get(3) != 1 or minimum <= 0 or maximum < minimum or any(not isfinite(v) or v <= 0 for v in curve):
        return None
    profile = sha256(struct.pack(f"<{len(curve)}f", *curve)).hexdigest()[:16]
    return f"dust:{minimum}:{maximum}:{profile}"


def _prize(level, allowed_items, text_items):
    if level.get(0) or level.get(4):
        return None
    dust = level.get(1, [])
    dust_id = _dust_id(dust) if dust else None
    if dust and dust_id is None:
        return None
    main_items, weapons, accessories = (level.get(i, []) for i in (2, 3, 5))
    count = len(main_items) + len(weapons) + len(accessories)
    if count == 0 and dust_id is not None:
        return dust_id, "collectible"
    if count != 1:
        return None
    if main_items:
        entry = main_items[0]
        item = entry.get(0)
        if entry.get(3) == 1 and (
            item in allowed_items or (item in text_items and entry.get(1) == entry.get(2) == 1)
        ):
            return item, "collectible"
    elif not dust and accessories and accessories[0].get(1) == 1:
        return accessories[0].get(0), "collectible"
    elif not dust and weapons and weapons[0].get(2) == 1:
        entry = weapons[0]
        return entry.get(0), "main_weapon" if entry.get(1, 0) else "shadow_weapon"
    return None


def select(data, names, allowed_items, *, text_items=frozenset()):
    """Find guaranteed rewards whose native row can move intact."""
    rows = read_table(data, names)
    prizes = {}
    for row, (start, fields) in rows.items():
        if fields.get(0) != row or len(fields.get(1, [])) != 1:
            continue
        if row not in INJECTED_REWARD_ROWS and ("." not in row or row.casefold().startswith(("test", "debug"))):
            continue
        prize = _prize(fields[1][0], allowed_items, text_items)
        if prize is None:
            continue
        item, category = prize
        if not item or item in PROTECTED:
            continue
        if (
            data[start + 8 : start + 10] != b"\x00\x05"
            or data[start : start + 8] != data[start + 10 : start + 18]
        ):
            raise ValueError(f"Unexpected row identity layout: {row}")
        prizes[row] = Prize(row, item, category, start, start + 10)
    return prizes


# Traversal and starter gear stay at their native sources until the gate consuming
# each ability can be moved to the matching encounter victory.
PROTECTED = frozenset(
    {
        # The optional Three-Faced Puppet route needs the soulforged Long blade.
        "Long",
        "BrutalAxe",
        "ShachiHook",
        "JinGua",
        "LionHead",
        "YouLongTou",
        "YouLongCha",
        "TigerCannon",
        "Tang",
        "Double",
        "UnnamedBow",
        "MiaoShouFeiDao",
        "ZhuoBiDun",
        "DuYanGong",
        "HuangJinHuoChong",
        "XueDiZi",
        "ThunderSpear",
        "CuiXinPiPa",
    }
)


def apply(data, names, allowed_items, selected, assignments, *, text_items=frozenset()):
    if sha256(data).hexdigest() != ORIGINAL:
        raise ValueError("LevelLoot source hash does not match Steam 26367565")
    return apply_reviewed(data, names, allowed_items, selected, assignments, text_items=text_items)


def reward_sources(selected, assignments):
    """Identify the original row that supplies each whole reward, including its quantity."""
    if selected.keys() - assignments.keys():
        raise ValueError("Reward plan does not cover the selected loot rows")
    if Counter(prize.item for prize in selected.values()) != Counter(assignments[row] for row in selected):
        raise ValueError("Reward plan must preserve the selected loot prizes")
    rows_by_item = defaultdict(deque)
    # Reserve all unchanged rows first, including duplicate IDs with different amounts.
    origins = {row: row for row in selected}
    moved = sorted(row for row in selected if assignments[row] != selected[row].item)
    for row in moved:
        rows_by_item[selected[row].item].append(row)
    for row in moved:
        origins[row] = rows_by_item[assignments[row]].popleft()
    return origins


def apply_reviewed(data, names, allowed_items, selected, assignments, *, text_items=frozenset(), origins=None):
    """Apply assignments after the caller has authenticated or extended the base table."""
    prizes = select(data, names, allowed_items, text_items=text_items)
    if selected.keys() - prizes.keys():
        raise ValueError("Reward plan does not cover the selected loot rows")
    explicit_origins = origins is not None
    if explicit_origins:
        if origins.keys() != selected.keys() or set(origins.values()) != selected.keys():
            raise ValueError("Explicit reward origins must permute the selected loot rows")
        if any(assignments.get(row) != prizes[donor].item for row, donor in origins.items()):
            raise ValueError("Explicit reward origins disagree with the item assignments")
    else:
        origins = reward_sources({row: prizes[row] for row in selected}, assignments)
    out = bytearray(data)
    for row, donor in origins.items():
        if row == donor:
            continue
        source = prizes[donor]
        target = prizes[row]
        key = data[target.outer : target.outer + 8]
        for offset in (source.outer, source.inner):
            out[offset : offset + 8] = key
    result = bytes(out)
    actual = select(result, names, allowed_items, text_items=text_items)
    expected = {
        row: assignments[row] if row in selected else p.item
        for row, p in prizes.items()
    }
    if {row: p.item for row, p in actual.items()} != expected:
        raise ValueError("Serialized reward round-trip differs from the generated plan")
    if explicit_origins:
        original = read_table(data, names)
        rebuilt = read_table(result, names)
        if any(rebuilt[row][1][1] != original[donor][1][1] for row, donor in origins.items()):
            raise ValueError("Serialized reward payload differs from the explicit source")
    return result
