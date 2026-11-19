"""Read and swap native enemy classes in reviewed Phantom Blade Zero maps."""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import struct


XIGU_CELL = "ProjectPBZ/Content/Maps/B02/PBZ_Xigu_WP/_Generated_/7MSFXHRARGNM96ALJRBMCW2AH.umap"
XIGU_MAIN_CELL = "ProjectPBZ/Content/Maps/B02/PBZ_Xigu_WP/_Generated_/82OBM6ICJZS18QDOP03KXFZHY.umap"
ENCAMPMENT_CELL = "ProjectPBZ/Content/Maps/B04_05/PBZ_Zhengdaodaying_WP/_Generated_/A4FPJ05LRWUTAQUUFRWC0WEJI.umap"
HOUJIE_CELL = "ProjectPBZ/Content/Maps/B09/PBZ_Houjie_WP/_Generated_/64Q0WR55YIK5YSQBU92NEAOS4.umap"
PANGZHEN_CELL = "ProjectPBZ/Content/Maps/B08_09_10/PBZ_Pangzhen_WP/_Generated_/9MNPQBUK8GIWDIWOAMGM1EYTR.umap"
SUPPORTED_MAPS = {
    XIGU_CELL: "df8d05d926a7155fba459ee1e3337f6ddbf7a0f53600cc2003daae5fcd7cbc6b",
    XIGU_MAIN_CELL: "1f28b748c3eed6a9d9bd8e05497f59a99e2f5a08254f95ca7a1eeaebc0a29c58",
    ENCAMPMENT_CELL: "b054ebb02020a1292cbcf5a287f0b8544a8638eeb729785a6e925ed1d5508efa",
    HOUJIE_CELL: "6c54c26f68ff329439aa8ac7e70dc12ec993eb06584dbaaaa5568b6a045c41b3",
    PANGZHEN_CELL: "d73407b936a0ce5b2777c2c52882dcf53cec837d9ae331bdfd3a6ba2a91f81f5",
}

# Ordinary enemy classes observed in the supported cells.
MELEE_CLASSES = frozenset({
    "BP_Monster_EMei_EMeiCi_C",
    "BP_Monster_EMei_ShuangCi_C",
    "BP_Monster_FemaleThug_Hoe_C",
    "BP_Monster_FemaleThug_TwinHoe_C",
    "BP_Monster_HuaShan_Normal_Blue_C",
    "BP_Monster_HuaShan_Normal_White_C",
    "BP_Monster_HuoTongRen_Fist_C",
    "BP_Monster_MaleThug_BigShield_C",
    "BP_Monster_MaleThug_Club_Yellow_C",
    "BP_Monster_MaleThug_Club_Yellow_Shield_C",
    "BP_Monster_MaleThug_Spear_Blue_C",
    "BP_Monster_MaleThug_Sword_Blue_C",
    "BP_Monster_MaleThug_Sword_Blue_Shield_C",
    "BP_Monster_MaleThug_TwinAxe_C",
    "BP_Monster_SpearMan_Spear_Blue_C",
    "BP_Monster_SpearMan_Spear_White_C",
    "BP_Monster_Vessel_Vagrant_C",
})
RANGED_CLASSES = frozenset({
    "BP_Monster_ArrowMan_Bow_C",
    "BP_Monster_CrossBow_C",
    "BP_Monster_EMei_Crossbow_C",
    "BP_Monster_FemaleThug_Dart_C",
    "BP_Monster_FemaleThug_Molotov_C",
    "BP_Monster_MaleThug_Throw_Rock_Blue_C",
})
ACTOR_CLASSES = MELEE_CLASSES | RANGED_CLASSES
SUPPORTED_GROUP_SCRIPTS = frozenset({"GroupScript_Level_C", "MobGroupScript_CombatNotify_C"})

# BP_AISpawner_C provides 30 properties before the native AISpawner schema.
SPAWNER_CLASS = 31
GROUP_MEMBERS = 10
GROUP_RUNTIME_MEMBERS = 11
GROUP_SCRIPTS = 12
NATIVE_MOB_GROUP = 0x7971CBB9D2143F31
SERIALIZED_CLASS_SIZE = 20


@dataclass(frozen=True)
class Spawner:
    id: str
    actor: str
    class_offset: int
    group: str | None = None

    @property
    def role(self):
        return "ranged" if self.actor.rsplit(".", 1)[-1] in RANGED_CLASSES else "melee"


def _names(data):
    count, size = struct.unpack_from("<II", data, 60)
    if not 0 < count < 200_000:
        raise ValueError("Unsupported Zen name batch")
    headers = 76 + count * 8
    start = pos = headers + count * 2
    names = []
    for index in range(count):
        header = struct.unpack_from(">H", data, headers + index * 2)[0]
        wide = bool(header & 0x8000)
        length = (header & 0x7FFF) * (2 if wide else 1)
        names.append(data[pos:pos + length].decode("utf-16le" if wide else "utf-8"))
        pos += length
    if pos != start + size or pos > len(data):
        raise ValueError("Invalid Zen name batch size")
    return names


def _properties(data, start, end):
    pos = start
    fragments = []
    hidden = 0
    index = 0
    while pos + 2 <= end:
        fragment, = struct.unpack_from("<H", data, pos)
        pos += 2
        index += fragment & 0x7F
        count = fragment >> 9
        masked = bool(fragment & 0x80)
        fragments.append((range(index, index + count), masked))
        index += count
        if masked:
            hidden += count
        if fragment & 0x100:
            break
    else:
        raise ValueError("Unterminated property header")

    mask_size = 0 if not hidden else 1 if hidden <= 8 else 2 if hidden <= 16 else 4 * ((hidden + 31) // 32)
    if pos + mask_size > end:
        raise ValueError("Truncated property zero mask")
    mask = int.from_bytes(data[pos:pos + mask_size], "little")
    active = []
    for indices, masked in fragments:
        for index in indices:
            if not masked or not mask & 1:
                active.append(index)
            if masked:
                mask >>= 1
    return pos + mask_size, active


def _read_path(data, pos, end, names):
    fixed_end = pos + SERIALIZED_CLASS_SIZE
    if fixed_end > end:
        raise ValueError("Truncated soft object path")
    package, pkg_number, asset, asset_number, size = struct.unpack_from("<IIIIi", data, pos)
    if pkg_number or asset_number or package >= len(names) or asset >= len(names) or size < 0:
        raise ValueError("Unsupported soft object path")
    path_end = fixed_end + size
    if path_end > end:
        raise ValueError("Truncated soft object subpath")
    subpath = data[fixed_end:path_end].decode("utf-8")
    return names[package], names[asset], subpath, path_end


def _spawner(data, start, end, names, id_):
    pos, fields = _properties(data, start, end)
    if SPAWNER_CLASS not in fields:
        return None
    for field in fields:
        if field == SPAWNER_CLASS:
            break
        if 1 <= field <= 9:
            pos += 4
        elif field == 30:
            pos += 8
        else:
            return None
    package, actor, subpath, _ = _read_path(data, pos, end, names)
    if (
        actor not in ACTOR_CLASSES
        or not package.startswith("/PBZCombatAsset/ActorData/Mobs/")
        or package.rsplit("/", 1)[-1] + "_C" != actor
        or subpath
    ):
        return None
    return Spawner(id_, f"{package}.{actor}", pos)


def _members(data, start, end, names, package_name, export_names):
    pos, fields = _properties(data, start, end)
    if not fields or fields[0] != GROUP_MEMBERS:
        return (), False
    if pos + 4 > end:
        raise ValueError("Truncated MobGroup.Members count")
    count, = struct.unpack_from("<I", data, pos)
    pos += 4
    if count > (end - pos) // SERIALIZED_CLASS_SIZE:
        raise ValueError("Invalid MobGroup.Members count")
    members = []
    supported = GROUP_RUNTIME_MEMBERS not in fields
    for _ in range(count):
        package, _, subpath, pos = _read_path(data, pos, end, names)
        if package != package_name or not subpath.startswith("PersistentLevel."):
            supported = False
        if subpath.startswith("PersistentLevel."):
            members.append(subpath.removeprefix("PersistentLevel."))
    if supported and GROUP_SCRIPTS in fields:
        if pos + 4 > end:
            raise ValueError("Truncated MobGroup.Scripts count")
        count, = struct.unpack_from("<I", data, pos)
        pos += 4
        if count > (end - pos) // 4:
            raise ValueError("Invalid MobGroup.Scripts count")
        scripts = struct.unpack_from(f"<{count}i", data, pos)
        supported = all(
            0 < script <= len(export_names) and export_names[script - 1] in SUPPORTED_GROUP_SCRIPTS
            for script in scripts
        )
    return members, supported and len(set(members)) == len(members)


def inspect_map(data):
    """Locate supported AISpawner.Class fields and local MobGroup memberships."""
    names = _names(data)
    data_start, pkg_name = struct.unpack_from("<II", data, 4)
    exports_start, exports_end = struct.unpack_from("<II", data, 32)
    if not (0 < exports_start <= exports_end <= data_start <= len(data)) or (exports_end - exports_start) % 72:
        raise ValueError("Unsupported Zen export map")
    if pkg_name >= len(names):
        raise ValueError("Zen package name index out of range")

    offsets = range(exports_start, exports_end, 72)
    export_names = []
    for offset in offsets:
        index, = struct.unpack_from("<I", data, offset + 16)
        export_names.append(names[index] if index < len(names) else "")

    spawners = {}
    groups = {}
    for index, (offset, name) in enumerate(zip(offsets, export_names)):
        is_spawner = name.startswith("BP_AISpawner_C_UAID_")
        class_index, = struct.unpack_from("<Q", data, offset + 32)
        is_group = name == "MobGroup" and class_index == NATIVE_MOB_GROUP
        if not is_spawner and not is_group:
            continue
        serial_offset, size, _, name_number = struct.unpack_from("<QQII", data, offset)
        start = data_start + serial_offset
        end = start + size
        if not data_start <= start < end <= len(data):
            raise ValueError(f"Invalid serial range for export {name}")
        if is_spawner:
            id_ = f"{name}_{name_number - 1}" if name_number else name
            spawner = _spawner(data, start, end, names, id_)
            if spawner is not None:
                if id_ in spawners:
                    raise ValueError(f"Duplicate spawner export {id_}")
                spawners[id_] = spawner
        else:
            groups[str(index)] = _members(data, start, end, names, names[pkg_name], export_names)

    memberships = Counter(id_ for members, _ in groups.values() for id_ in members)
    assigned_groups = {}
    for group, (members, supported) in groups.items():
        if not supported or not all(id_ in spawners and memberships[id_] == 1 for id_ in members):
            continue
        for id_ in members:
            assigned_groups[id_] = group
    return {
        id_: Spawner(id_, spawners[id_].actor, spawners[id_].class_offset, group)
        for id_, group in assigned_groups.items()
    }


def _load_maps(read_file):
    maps = {}
    for path, expected in SUPPORTED_MAPS.items():
        try:
            data = read_file(path)
        except KeyError as error:
            raise ValueError(f"Required base asset missing: {path}") from error
        if sha256(data).hexdigest() != expected:
            raise ValueError(f"Unsupported base asset hash for {path}")
        maps[path] = (data, inspect_map(data))
    return maps


def catalog_monsters(read_file):
    """Return the supported native spawn slots for the randomizer catalog."""
    rows = []
    for path, (_, spawners) in _load_maps(read_file).items():
        for spawner in spawners.values():
            row = {
                "id": f"{path}#{spawner.id}",
                "actor": spawner.actor,
                "compatibility": f"{path}#{spawner.role}",
                "group": f"{path}#{spawner.group}",
            }
            rows.append(row)
    return rows


def patch_monsters(read_file, assignments, mode):
    """Return modified map bytes for the seed's local monster assignment."""
    if mode not in {"unit", "group"}:
        raise ValueError("Monster patch mode must be unit or group")
    if not isinstance(assignments, dict) or any(not isinstance(source, str) for source in assignments.values()):
        raise ValueError("Monster plan assignments must map slot IDs to slot IDs")
    maps = _load_maps(read_file)
    all_slots = {
        f"{path}#{id_}": (path, spawner)
        for path, (_, spawners) in maps.items()
        for id_, spawner in spawners.items()
    }
    if set(assignments) != set(all_slots) or Counter(assignments.values()) != Counter(all_slots.keys()):
        raise ValueError("Monster plan must permute all supported spawn slots")

    replaced = {}
    expected = {}
    outgoing_groups = {}
    incoming_groups = {}
    for id_, source_id in assignments.items():
        path, destination = all_slots[id_]
        source_path, source = all_slots[source_id]
        if path != source_path or destination.role != source.role:
            raise ValueError("Monster plan crosses package or combat-role compatibility")
        if mode == "group":
            group_key = (path, destination.group)
            source_key = (path, source.group)
            if (
                outgoing_groups.setdefault(group_key, source_key) != source_key
                or incoming_groups.setdefault(source_key, group_key) != group_key
            ):
                raise ValueError("Monster plan splits a group")
        if destination.actor == source.actor:
            continue
        data, _ = maps[path]
        if path not in replaced:
            replaced[path] = bytearray(data)
            expected[path] = {}
        start, end = destination.class_offset, destination.class_offset + SERIALIZED_CLASS_SIZE
        replaced[path][start:end] = data[source.class_offset:source.class_offset + SERIALIZED_CLASS_SIZE]
        expected[path][destination.id] = source.actor

    result = {}
    for path, patched in replaced.items():
        data = bytes(patched)
        before, old_spawners = maps[path]
        spawners = inspect_map(data)
        if len(data) != len(before) or spawners.keys() != old_spawners.keys():
            raise ValueError(f"Spawner patch changed the map layout for {path}")
        for id_, original in old_spawners.items():
            slot = spawners[id_]
            if slot.group != original.group or slot.actor != expected[path].get(id_, original.actor):
                raise ValueError(f"Spawner patch failed readback for {path}#{id_}")
        result[path] = data
    return result
