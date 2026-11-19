"""Readable original prizes and same-world landmarks for the receipt checklist."""

from collections import defaultdict
from math import atan2, degrees, dist, hypot, isfinite
from pathlib import PurePosixPath

from integrations.voices.zen_dialogue import LOCRES_ROOT
from integrations.weapons.zen import AssetReader, SingleExport, name_batch

from . import loot
from .pickup_sources import _package, _read_fields
from .reward_rows import INVENTORY


UI_TABLES = "ProjectPBZ/Content/PBZContent/DataTable/UI/"
ITEM_TABLES = (
    (INVENTORY, "PBZItemDataStruct", "ItemName"),
    (UI_TABLES + "DT_Accessory.uasset", "AccessoryData", "AccessoryName"),
    (UI_TABLES + "DT_WeaponData.uasset", "WeaponData", "WeaponName"),
    (UI_TABLES + "DT_ShaqiWeaponData.uasset", "ShaqiWeaponData", "WeaponName"),
)
SOURCE_NAMES = {"map_pickup": "光点", "chest": "宝箱", "boss": "Boss", "quest": "任务", "enemy_drop": "战斗"}
DIRECTIONS = ("前", "右前", "右", "右后", "后", "左后", "左", "左前")


class _BellReader(AssetReader):
    NATIVE_STRUCTS = {name: shape for name, shape in AssetReader.NATIVE_STRUCTS.items() if name != "Transform"}


def _rows(store, schemas, path, schema, reader_type=AssetReader):
    asset = SingleExport(store.read_file(path))
    reader = reader_type(asset.data, asset.names, schemas, asset.start, len(asset.data))
    if reader.read("10s") not in (bytes.fromhex("0003f9ffffff00000000"), bytes.fromhex("0003fbffffff00000000")):
        raise ValueError(f"Unsupported table preamble: {path}")
    for _ in range(reader.count()):
        row = reader.name()
        yield row, {key: field.value for key, field in reader.properties(schema).items()}
    if reader.position != reader.end:
        raise ValueError(f"Unexpected data after the last row: {path}")


def _text(value, localization):
    if value and value.get("Key"):
        text = localization.get(value["Key"].value)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _names(store, schemas, localization):
    names = {}
    for path, schema, field in ITEM_TABLES:
        for row_name, row in _rows(store, schemas, path, schema):
            item = row.get("ItemId")
            text = _text(row.get(field), localization)
            if not text and any("\u4e00" <= char <= "\u9fff" for char in row_name):
                text = row_name
            if item and text:
                names[item] = text
    return names


def _bells(store, schemas, localization):
    worlds = {}
    for row, fields in _rows(store, schemas, UI_TABLES + "DT_MapData.uasset", "MapData"):
        world = fields.get("LevelName")
        if not world or world == "None":
            continue
        info = world.casefold(), _text(fields.get("MapName"), localization)
        worlds[row.casefold()] = info
        if fields.get("MapID"):
            worlds[fields["MapID"].casefold()] = info

    grouped = defaultdict(list)
    for _, fields in _rows(store, schemas, UI_TABLES + "DT_BellData.uasset", "BellDataStruct", _BellReader):
        map_id = fields.get("MapID")
        bell = fields.get("BellID")
        point = fields.get("BellLocation")
        if not (map_id and bell and point and map_id.casefold() in worlds and all(map(isfinite, point))):
            continue
        world, map_name = worlds[map_id.casefold()]
        rotation = fields.get("TeleportCameraRotation")
        yaw = rotation[1] if rotation and isfinite(rotation[1]) else None
        label = _text(fields.get("BellName"), localization) or bell
        grouped[world].append((point, bell, label, map_name, yaw))
    return grouped


def _place(world, point, bells):
    if not point or not bells.get(world.casefold()):
        return None
    origin, _, bell, map_name, yaw = min(
        bells[world.casefold()], key=lambda record: (dist(point, record[0]), record[1]),
    )
    x, y, z = (coordinate - anchor for coordinate, anchor in zip(point, origin, strict=True))
    bell_name = bell if bell.endswith("铃铛") else f"{bell}铃铛"
    parts = [map_name or world, bell_name, f"直线约 {round(dist(point, origin) / 100)} 米"]
    if yaw is not None and hypot(x, y) >= 100:
        direction = DIRECTIONS[round((degrees(atan2(y, x)) - yaw) / 45) % len(DIRECTIONS)]
        parts.append(f"传送朝向的{direction}方")
    if abs(z) >= 500:
        height = "高" if z > 0 else "低"
        parts.append(f"比铃铛{height}约 {abs(z) / 100:.0f} 米")
    return " · ".join(parts)


def _positions(store, schemas, sources):
    by_cell = defaultdict(list)
    for point, source in sources.items():
        if source.get("source") in {"map_pickup", "chest"} and all(
            source.get(key) for key in ("package", "actor", "actor_class")
        ):
            by_cell[source["package"]].append((point, source))
    for path, locations in by_cell.items():
        package = PurePosixPath(path)
        if package.parent.name != "_Generated_":
            continue
        data = store.read_file(path)
        names, _, exports = _package(data)
        actors = {f"{e.name}_{e.ordinal - 1}" if e.ordinal else e.name: e for e in exports}
        for point, source in locations:
            actor = actors.get(source["actor"])
            if not actor:
                continue
            root = dict(_read_fields(
                data, names, schemas, actor, source["actor_class"], {"RootComponent"},
            )).get("RootComponent")
            if not root or not 0 < root <= len(exports):
                continue
            properties = dict(_read_fields(
                data, names, schemas, exports[root - 1], "SceneComponent",
                {"RelativeLocation", "AttachParent", "bAbsoluteLocation"},
            ))
            position = properties.get("RelativeLocation")
            if position and all(map(isfinite, position)) and (
                not properties.get("AttachParent") or properties.get("bAbsoluteLocation")
            ):
                yield point, (package.parent.parent.name, position)


def _dust_quantity(levels):
    if len(levels) != 1 or len(dust := levels[0].get(1, [])) != 1:
        return None
    entry = dust[0]
    first = (entry.get(2) or [1])[0]
    low, high = entry.get(0, 0), entry.get(1, 0)
    if entry.get(3) != 1 or not 0 < low <= high or first != 1.0:
        return None
    return str(low) if low == high else f"{low}–{high}"


def describe_points(store, pak, helpers, schemas, rewards, sources, expanded, aliases):
    """Describe original rewards and nearby bells using stock assets at build time."""
    rewards = tuple(rewards)
    strings = helpers.localization(pak.read_file(f"{LOCRES_ROOT}zh-Hans/Game.locres"))
    names = _names(store, schemas, strings)
    bells = _bells(store, schemas, strings)
    positions = dict(_positions(store, schemas, {
        reward["id"]: sources[reward["id"]] for reward in rewards if reward["id"] in sources
    }))
    rows = loot.read_table(expanded, name_batch(expanded)[0])
    labels = {}
    for reward in rewards:
        point = reward["id"]
        item = reward["item"]
        source = reward["source"]
        name = "意识尘埃" if item.startswith("dust:") else names.get(item)
        levels = rows.get(aliases.get(point, point), (0, {}))[1].get(1, ())
        amount = _dust_quantity(levels)
        position = positions.get(point)
        place = _place(*position, bells) if position else None
        display = name or item
        if len(levels) == 1 and len(entries := levels[0].get(2, [])) == 1:
            low, high = entries[0].get(1, 0), entries[0].get(2, 0)
            if low > 0 and high >= low:
                display += f" ×{low}" if low == high else f" ×{low}–{high}"
        if amount:
            dust_name = f"意识尘埃 ×{amount}（首周目）"
            display = dust_name if item.startswith("dust:") else f"{display} + {dust_name}"
        parts = [SOURCE_NAMES.get(source, source), display, place, point]
        label = {"item": item, "itemLabel": display, "source": source,
                 "label": " | ".join(part for part in parts if part)}
        if name:
            label["itemName"] = name
        if place:
            label["place"] = place
        labels[point] = label
    return labels
