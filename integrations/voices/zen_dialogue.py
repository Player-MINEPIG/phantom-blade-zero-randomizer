"""Build fixed-size patches for standing dialogue in PBZ Steam build 26367565."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import importlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
from types import ModuleType

from randomizer import generate


CATALOG_VERSION = "pbz-steam-26367565-standing-dialogue-v1"
GRAPH_ROOT = "ProjectPBZ/Content/PBZContent/Blueprint/FlowGraph/DialogueGraph/QuestDialogue/Generated/"
TABLE_PATH = "ProjectPBZ/Content/PBZContent/DataTable/Localizaion/DT_LocTable.uasset"
TABLE_SHA256 = "21185fd13b6caf7aa1d7dc29234aa63dc85c0761cafad35718dfd7f17a160018"
LOCRES_ROOT = "ProjectPBZ/Content/Localization/Game/"
LOCRES_SHA256 = {
    "zh-Hans": "2cba6781622188d33d3ad20679725fbd5e68a398ba9cfc14c1da9de213c94813",
    "en-US": "7100a58190628f23dcfe12cfe4894abe1f3663cbe4ec37fcb718ece81bb7640c",
}
NON_STANDING = re.compile(r"(?i)/boss/|memory|_mem|seq|2d|3d|cutscene")
ROW_STRINGS = {0, 1, 2, 3, 4, 6, 10, 13, 14, 15, 21, 22, 23}
ROW_SKIP_IN_GROUP = {0, 2, 3, 4}
NESTED_TIMINGS = {11, 15, 16, 18, 19}
DIALOGUE_CONTENT_CONFIG = 20
ROW_NAME = 35
ROW_NAME_STR = 36


@dataclass(frozen=True)
class Slot:
    id: str
    path: str
    ordinal: int
    key: str
    audio: str
    compatibility: str
    fields: tuple[tuple[int, int], ...]


def _active_properties(reader):
    fragments = []
    index = zero_count = 0
    for _ in range(128):
        packed = int.from_bytes(reader.take(2), "little")
        index += packed & 127
        count = packed >> 9
        masked = bool(packed & 128)
        fragments.append((range(index, index + count), masked))
        index += count
        zero_count += count if masked else 0
        if packed & 256:
            break
    else:
        raise ValueError("Unterminated unversioned property header")

    mask_size = (zero_count + 7) // 8
    if mask_size > 2:
        mask_size = 4 * ((zero_count + 31) // 32)
    mask = int.from_bytes(reader.take(mask_size), "little")
    fields = []
    for indices, masked in fragments:
        for index in indices:
            if not masked or not mask & 1:
                fields.append(index)
            if masked:
                mask >>= 1
    return fields


def _fname(reader, names):
    index, instance = struct.unpack("<II", reader.take(8))
    if index >= len(names):
        raise ValueError(f"Name index {index} is outside the Zen package name batch")
    return names[index] if not instance else f"{names[index]}_{instance - 1}"


def _exports(data, name_batch):
    names, _ = name_batch(data)
    summary = struct.unpack_from("<15I", data)
    header, first, stop = summary[1], summary[8], summary[9]
    if summary[0] != 0 or not 60 <= first <= stop <= header <= len(data):
        raise ValueError("Unsupported Zen header bounds")
    if summary[13:15] != (stop, stop) or (stop - first) % 72:
        raise ValueError("Unsupported Zen export map")
    exports = []
    for position in range(first, stop, 72):
        relative, length, index, ordinal = struct.unpack_from("<QQII", data, position)
        start = header + relative
        end = start + length
        if index >= len(names) or end > len(data):
            raise ValueError("Zen export exceeds asset bounds")
        exports.append((names[index], ordinal, start, end))
    return names, exports


def _localization_rows(data, helpers):
    if sha256(data).hexdigest() != TABLE_SHA256:
        raise ValueError("DT_LocTable does not match supported Steam build 26367565")
    names, exports = _exports(data, helpers.name_batch)
    ((asset, _, start, end),) = exports
    reader = helpers.Reader(data, start)
    if asset != "DT_LocTable" or _active_properties(reader) != [0] or reader.i32() != -5 or reader.i32() != 0:
        raise ValueError("Unsupported DT_LocTable header")
    rows = {}
    for _ in range(reader.u32()):
        key = _fname(reader, names)
        values = {}
        for field in _active_properties(reader):
            if field in ROW_STRINGS:
                value = reader.fstring()
            elif field == 19:
                value = _fname(reader, names)
            elif 0 <= field < 24:
                value = reader.take(1)[0]
            else:
                raise ValueError(f"Unknown LocDataTableRow field {field}")
            values[field] = value
        if values.get(0) != key or key in rows:
            raise ValueError(f"Invalid or duplicate localization row {key!r}")
        rows[key] = values
    if reader.p != end:
        raise ValueError("DT_LocTable rows do not fill the original export")
    return rows


def _dialogue_fields(data, helpers):
    names, exports = _exports(data, helpers.name_batch)
    if any("/Cinematics/" in name or "LevelSequence" in name for name in names):
        return {}
    nodes = {}
    for name, ordinal, start, end in exports:
        if name != "DialogueNode_C" or not ordinal:
            continue
        reader = helpers.Reader(data, start)
        fields = _active_properties(reader)
        # The known layout stores DialogueContentConfig, then the inherited
        # RowName and RowNameStr. Skip variants with an animation/scene reference
        # or another payload before these fields.
        if ROW_NAME not in fields or ROW_NAME_STR not in fields:
            continue
        if any(field not in (DIALOGUE_CONTENT_CONFIG, ROW_NAME) for field in fields if field < ROW_NAME_STR):
            continue
        timings = []
        non_timing = []
        timing_fields = []
        if DIALOGUE_CONTENT_CONFIG in fields:
            for field in _active_properties(reader):
                position = reader.p
                if field in (0, 1):
                    value = reader.fstring()
                elif field in (10, 11, 15, 16, 18, 19):
                    value = reader.take(4).hex()
                elif field in (2, 3, 5, 6, 7, 8, 9, 12, 13, 14, 17):
                    value = reader.take(1)[0]
                elif field == 4:
                    value = reader.take(24).hex()
                else:
                    raise ValueError(f"Unknown DialogueContentData field {field}")
                if field in NESTED_TIMINGS:
                    timings.append((position, reader.p))
                    timing_fields.append(field)
                else:
                    non_timing.append((field, value))
        position = reader.p
        key = _fname(reader, names)
        key_string = reader.fstring()
        if reader.p > end or ordinal in nodes:
            raise ValueError("Dialogue references exceed their original export or duplicate a node id")
        if key != key_string or not key.startswith("Dlg_") or NON_STANDING.search(key):
            continue
        nodes[ordinal] = (key, ((position, reader.p), *timings), (non_timing, timing_fields))
    return nodes


def scan(iostore, pak, helpers, graph=None):
    """Return candidate slot records and original Zen payloads from local game files."""
    rows = _localization_rows(iostore.read_file(TABLE_PATH), helpers)
    subtitle_keys = None
    for culture, expected_hash in LOCRES_SHA256.items():
        data = pak.read_file(f"{LOCRES_ROOT}{culture}/Game.locres")
        if sha256(data).hexdigest() != expected_hash:
            raise ValueError(f"{culture} localization does not match Steam build 26367565")
        keys = {key for key, text in helpers.localization(data).items() if text}
        subtitle_keys = keys if subtitle_keys is None else subtitle_keys & keys
    events = {
        PurePosixPath(path).stem for path in iostore.files
        if "/Wwise/Events/VO/Plot/" in path and path.endswith(".uasset")
    }
    sources = {}
    slots = []
    for path in sorted(iostore.files):
        if not path.startswith(GRAPH_ROOT) or not path.endswith(".uasset"):
            continue
        relative = path[len(GRAPH_ROOT):]
        if NON_STANDING.search("/" + relative) or graph and relative != graph:
            continue
        data = iostore.read_file(path)
        groups = defaultdict(list)
        for ordinal, (key, fields, config) in _dialogue_fields(data, helpers).items():
            row = rows.get(key)
            if row is None or key not in subtitle_keys or not row.get(1) or row.get(2) not in events:
                continue
            if any(row.get(field) for field in (13, 14, 15)):
                continue
            metadata = [(i, value) for i, value in row.items() if i not in ROW_SKIP_IN_GROUP]
            width = fields[0][1] - fields[0][0]
            compatibility = sha256(json.dumps([path, metadata, width, config]).encode()).hexdigest()
            id_ = f"{relative}#DialogueNode_C_{ordinal - 1}"
            groups[compatibility].append(Slot(id_, path, ordinal, key, row[2], compatibility, fields))
        for group in groups.values():
            if len({slot.key for slot in group}) > 1:
                slots.extend(group)
                sources[path] = data
    if not slots:
        raise ValueError("No compatible standing dialogue slots found")
    return slots, sources


def catalog_rows(slots):
    return [
        {"id": slot.id, "kind": "ambient", "compatibility": slot.compatibility, "audio": slot.audio, "subtitle": slot.key}
        for slot in slots
    ]


def apply(sources, slots, assignments, helpers):
    """Apply a complete seeded permutation and re-read the changed Zen exports."""
    by_id = {slot.id: slot for slot in slots}
    if by_id.keys() != assignments.keys() or set(by_id) != set(assignments.values()):
        raise ValueError("Dialogue assignments must be a permutation of the scanned slots")
    changed = {}
    expected = defaultdict(dict)
    for slot in slots:
        source = by_id[assignments[slot.id]]
        if source.compatibility != slot.compatibility:
            raise ValueError(f"Incompatible standing dialogue source for {slot.id}")
        if source.id == slot.id:
            continue
        original = sources[slot.path]
        for (start, end), (other_start, other_end) in zip(slot.fields, source.fields, strict=True):
            if end - start != other_end - other_start:
                raise ValueError(f"Patch changes the Zen export layout for {slot.id}")
            replacement = original[other_start:other_end]
            if original[start:end] != replacement:
                if slot.path not in changed:
                    changed[slot.path] = bytearray(original)
                changed[slot.path][start:end] = replacement
        expected[slot.path][slot.ordinal] = (
            source.key,
            tuple(original[start:end] for start, end in source.fields),
        )
    for path, output in changed.items():
        readback = _dialogue_fields(bytes(output), helpers)
        if len(output) != len(sources[path]):
            raise ValueError(f"Dialogue patch failed readback for {path}")
        for ordinal, (expected_key, expected_bytes) in expected[path].items():
            key, fields, _ = readback[ordinal]
            if key != expected_key or tuple(bytes(output[start:end]) for start, end in fields) != expected_bytes:
                raise ValueError(f"Dialogue patch failed readback for {path} node {ordinal}")
    return {path: bytes(blob) for path, blob in changed.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paks", type=Path, help="installed game's ProjectPBZ/Content/Paks directory")
    parser.add_argument("output", type=Path, help="new directory for raw Zen overrides and the assignment plan")
    parser.add_argument("--reader-dir", type=Path, required=True, help="directory containing resources_reader.py and pak_reader.py")
    parser.add_argument("--oodle", type=Path, required=True, help="locally installed Oodle DLL")
    parser.add_argument("--seed", required=True)
    parser.add_argument("--graph", help="restrict the build to one generated graph, e.g. DDSD/DG_GuaiMian2.uasset")
    args = parser.parse_args()

    package = ModuleType("pbz_voice_source")
    package.__path__ = [str(args.reader_dir.resolve())]
    sys.modules[package.__name__] = package
    try:
        helpers = importlib.import_module(f"{package.__name__}.resources_reader")
        pak_reader = importlib.import_module(f"{package.__name__}.pak_reader")
        codec = helpers.OodleReader(args.oodle)
        iostore = helpers.IoStore(args.paks / "ProjectPBZ-Windows.utoc", codec)
        pak = pak_reader.PakReader(args.paks / "ProjectPBZ-Windows.pak", codec)
        slots, sources = scan(iostore, pak, helpers, args.graph)
        catalog = {"version": CATALOG_VERSION, "items": [], "rewards": [], "voices": catalog_rows(slots)}
        plan = generate(catalog, {"seed": args.seed})
        overrides = apply(sources, slots, plan["voices"], helpers)
        args.output.mkdir(parents=True)
        for asset, data in overrides.items():
            path = args.output / "zen" / asset
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (args.output / "voice-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ImportError, KeyError, OSError, ValueError, struct.error) as error:
        parser.exit(1, f"{error}\n")
    print(f"Validated {len(slots)} dialogue slots and wrote {len(overrides)} raw Zen overrides to {args.output}")


if __name__ == "__main__":
    main()
