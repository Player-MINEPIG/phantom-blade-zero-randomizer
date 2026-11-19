"""Swap paired battle dialogue keys in reviewed PBZ combat abilities."""

from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import PurePosixPath
import json

from .zen_dialogue import (
    LOCRES_ROOT,
    LOCRES_SHA256,
    ROW_SKIP_IN_GROUP,
    TABLE_PATH,
    Slot,
    _active_properties,
    _exports,
    _localization_rows,
)


ROOT = "ProjectPBZ/Plugins/Secret/PBZCombatAsset/Content/ActorData/Mobs/"

# Hash and number of Blueprint properties before BP_MonsterSubtitlesBase_C.
ABILITIES = {
    "045_JingYe/Ability/Abilities/GA_JingYe_Subtitles.uasset": ("a0fa35fa9c7df913383db6d24e5cf29e6c1fce369715f718f051949af3fdfa86", 1),
    "049_ChangHong/Passive/GA_ChangHong_Subtitles.uasset": ("7c34e9c3919ffca26515e97099067e1384e229227159bb52893aaedb2ad0bb13", 1),
    "050_LeiDang_P2/Ability/Abilities/GA_LeiDang_P2_Subtitles.uasset": ("42716ea4c2c13c21d0677998bc4bf9453efef959a21c094baf18dc92f0e9e3e5", 1),
    "051_HookMan_P2/Ability/GA_HookMan_P2_Subtitles.uasset": ("5ea80c9d80e63b141c389e064f990ab9cfd02c356b9fed5a906306b063785179", 1),
    "053_ChangHong_P2/Passive/GA_ChangHong_P2_Subtitles.uasset": ("7a2eec8a6d626b87ded64a6ec2f296f7b05f06d4218723d0841f6d4770342004", 1),
    "063_ChiLian_P1/Ability/GA_ChiLian_P1_Subtitles.uasset": ("ab12a9ab5650ab9c354ef5231b6b800da3fab79b55b6ef7988c04bb0e870b064", 1),
    "072_CanQu_BiYuan/Ability/GA_BiYuan_Subtitles.uasset": ("48144d27702815ad732309c4e0f1e8ea09618a0cbaed441b9e7735e7c4fb07b6", 1),
    "CanQu_BiHai/Ability/Passive/GA_CanQu_BiHai_Subtitles.uasset": ("b0b87c5c34bd5f807e8d9de4ff869472e8f0f163e37bb65b1a71973f8e345ca6", 1),
    "FengXueDaoKe/Ability/Abilities/GA_FengXueDaoKe_Subtitles.uasset": ("332403a7407d0306ba8a35f29dc15278093d1d8e1eae205873977c3c42e7a76c", 1),
    "HuaQianXiao/Ability/Abilities/Passive/GA_HuaQianXiao_Subtitles.uasset": ("5a06836a148f137b0ab1301558ab80d271bcdbe1f62a88513c7a828f7dc79aa8", 1),
    "JiangJun/Ability/WuXuan/Passive/GA_WuXuan_SubTitles.uasset": ("00b6594327784b512b10f9a84b57da3f251ee7c5cab707f1def4fb1537397787", 2),
    "JiangJun/Ability/ZhuoBi/Abilities/GA_ZhuoBi_Subtitles.uasset": ("3b65d731626f34d74ae06cea63ffaefec0f29cf13e6647e20181b29262ea9408", 1),
    "LuanShi/Ability/Abilities/GA_Luanshi_SubTitles.uasset": ("0c3e0c69cf3c859d5b00f59628edd784ebae617cfe26a4158e0caa528fa1f154", 2),
    "YuCong/Abilities/Bing/GA_YuCong_Bing_Subtitles.uasset": ("4f67dc2c5f4ac4640e7f11dccb9de2673f4ffc3c4713bff9b7c2824e168ba5a6", 1),
    "044_PengMeng/Passive/GA_PengMeng_Subtitles_BreakEnd.uasset": ("dddf721ba3bea3aeb01bd4d8e14c80ec0dfb1849e9e3443cac28949edaed86ba", 2),
}


def _array_count(reader, end):
    count = reader.u32()
    if count > end - reader.p:
        raise ValueError("Battle subtitle array exceeds its class export")
    return count


def _skip_tag(reader):
    fields = _active_properties(reader)
    if fields == [0]:
        reader.take(8)
    elif fields:
        raise ValueError("Unsupported battle subtitle GameplayTag")


def _skip_tag_requirements(reader, end):
    for field in _active_properties(reader):
        if field in (0, 1):
            reader.take(_array_count(reader, end) * 8)
        elif field == 2:
            for query_field in _active_properties(reader):
                if query_field == 0:
                    reader.take(4)
                elif query_field == 1:
                    for _ in range(_array_count(reader, end)):
                        _skip_tag(reader)
                elif query_field == 2:
                    reader.take(_array_count(reader, end))
                elif query_field in (3, 4):
                    reader.fstring()
                else:
                    raise ValueError("Unsupported battle subtitle tag query")
        else:
            raise ValueError("Unsupported battle subtitle tag requirements")


def _flow_key(reader):
    namespace = ""
    key = ""
    span = None
    for field in _active_properties(reader):
        if field == 0:
            namespace = reader.fstring()
        elif field == 1:
            start = reader.p
            key = reader.fstring()
            span = (start, reader.p)
        elif field == 2:
            if reader.take(9) != b"\0\0\0\0\xff\0\0\0\0":
                raise ValueError("Unsupported battle subtitle cached FText")
        else:
            raise ValueError("Unsupported FlowLocText property in battle subtitles")
    return namespace, key, span


def _subtitle_keys(data, relative, helpers):
    _, native_index = ABILITIES[relative]
    _, exports = _exports(data, helpers.name_batch)
    cdo = f"Default__{PurePosixPath(relative).stem}_C"
    matches = [(start, end) for name, number, start, end in exports if name == cdo and not number]
    if len(matches) != 1:
        raise ValueError(f"Could not identify battle subtitle CDO in {relative}")
    (start, end), = matches
    reader = helpers.Reader(data, start)
    fields = _active_properties(reader)
    data_index = native_index + 1
    if data_index not in fields:
        raise ValueError(f"Missing Subtitle Data in {relative}")
    for field in fields:
        if field == data_index:
            break
        if field == native_index - 1:
            reader.take(4)
        elif native_index == 2 and field == 0 and not _active_properties(reader):
            continue
        else:
            raise ValueError(f"Unsupported CDO layout in {relative}")

    keys = []
    group_count = _array_count(reader, end)
    for _ in range(group_count):
        for field in _active_properties(reader):
            if field == 0:
                _skip_tag(reader)
            elif field == 1:
                _skip_tag_requirements(reader, end)
            elif field == 2:
                keys.extend(_flow_key(reader) for _ in range(_array_count(reader, end)))
            elif field in (3, 4, 5, 6):
                reader.take({3: 4, 4: 8, 5: 1, 6: 1}[field])
            elif field == 7:
                _flow_key(reader)
            else:
                raise ValueError(f"Unsupported MobTagSubtitlesData property in {relative}")
    if reader.p > end:
        raise ValueError(f"Battle subtitle rows exceed class export bounds in {relative}")
    return keys


def scan(iostore, pak, helpers):
    """Resolve native combat subtitle slots to game-local Wwise events and locale rows."""
    rows = _localization_rows(iostore.read_file(TABLE_PATH), helpers)
    subtitle_keys = None
    for culture, expected_hash in LOCRES_SHA256.items():
        data = pak.read_file(f"{LOCRES_ROOT}{culture}/Game.locres")
        if sha256(data).hexdigest() != expected_hash:
            raise ValueError(f"{culture} localization does not match supported Steam build 26367565")
        keys = {key for key, text in helpers.localization(data).items() if text}
        subtitle_keys = keys if subtitle_keys is None else subtitle_keys & keys
    events = {
        PurePosixPath(path).stem for path in iostore.files
        if "/Wwise/Events/VO/Plot/" in path and path.endswith(".uasset")
    }

    slots = []
    sources = {}
    for relative, (expected_hash, _) in ABILITIES.items():
        path = ROOT + relative
        data = iostore.read_file(path)
        if sha256(data).hexdigest() != expected_hash:
            raise ValueError(f"Unsupported battle subtitle asset hash for {relative}")
        pools = defaultdict(list)
        for ordinal, (namespace, key, span) in enumerate(_subtitle_keys(data, relative, helpers)):
            row = rows.get(key)
            if namespace != "Default" or "_battle_" not in key.lower() or row is None or key not in subtitle_keys:
                continue
            audio = row.get(2)
            if not row.get(1) or audio not in events or "battle" not in audio.lower():
                continue
            if any(row.get(field) for field in (13, 14, 15)):
                continue
            metadata = [(i, value) for i, value in row.items() if i not in ROW_SKIP_IN_GROUP]
            width = span[1] - span[0]
            compatibility = sha256(json.dumps([path, metadata, width]).encode()).hexdigest()
            id_ = f"{relative}#CombatSubtitle_{ordinal}"
            pools[compatibility].append(Slot(id_, path, ordinal, key, audio, compatibility, (span,)))
        for pool in pools.values():
            if len({slot.key for slot in pool}) > 1:
                slots.extend(pool)
                sources[path] = data
    if not slots:
        raise ValueError("No compatible battle subtitle slots found")
    return slots, sources


def catalog_rows(slots):
    return [
        {"id": slot.id, "kind": "combat", "compatibility": slot.compatibility, "audio": slot.audio, "subtitle": slot.key}
        for slot in slots
    ]


def apply(sources, slots, assignments, helpers):
    """Apply a seeded permutation of battle keys and reparse their class exports."""
    by_id = {slot.id: slot for slot in slots}
    if assignments.keys() != by_id.keys() or Counter(assignments.values()) != Counter(by_id.keys()):
        raise ValueError("Battle subtitle assignments must be a permutation of the scanned slots")
    changed = {}
    expected = defaultdict(dict)
    for slot in slots:
        source = by_id[assignments[slot.id]]
        if source.compatibility != slot.compatibility:
            raise ValueError(f"Incompatible battle subtitle source for {slot.id}")
        if source.key == slot.key:
            continue
        (start, end), = slot.fields
        (other_start, other_end), = source.fields
        if end - start != other_end - other_start:
            raise ValueError(f"Battle subtitle patch changes the Zen export layout for {slot.id}")
        original = sources[slot.path]
        if slot.path not in changed:
            changed[slot.path] = bytearray(original)
        changed[slot.path][start:end] = original[other_start:other_end]
        expected[slot.path][slot.ordinal] = source.key

    for path, data in changed.items():
        if len(data) != len(sources[path]):
            raise ValueError(f"Battle subtitle patch changed the asset size for {path}")
        rows = _subtitle_keys(bytes(data), path.removeprefix(ROOT), helpers)
        if any(rows[ordinal][1] != key for ordinal, key in expected[path].items()):
            raise ValueError(f"Battle subtitle patch failed readback for {path}")
    return {path: bytes(data) for path, data in changed.items()}
