"""Resolve placed map pickups and chests to their original LevelLoot row."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from struct import unpack_from

from integrations.weapons.movesets import PackageStore, _chunk_package_id
from integrations.weapons.zen import AssetReader, name_batch


DEVICE_ROOT = "ProjectPBZ/Content/PBZContent/Blueprint/Item/Device/"
MAP_ROOT = "ProjectPBZ/Content/Maps/"
DEVICES = {
    "BP_Rubbish": "map_pickup",
    "BP_Rubbish_A": "map_pickup",
    "BP_Rubbish_b": "map_pickup",
    "BP_Rubbish_C": "map_pickup",
    "BP_Chest": "chest",
}
SCRIPTED_REWARDS = (
    "ProjectPBZ/Content/PBZContent/Blueprint/FlowGraph/FlowGraphNode/LootItems.uasset",
    "ProjectPBZ/Content/PBZContent/Blueprint/FlowGraph/FlowGraphNode/FromActor_LootItem.uasset",
    "ProjectPBZ/Plugins/Secret/PBZCombatAsset/Content/ActorData/Mobs/Common/SGameAIExtension/MobGroupScript_AddItemAfterCombat.uasset",
)

# These fields attach a pickup to an authored interaction or a separate path.
# Pickups and Get Dust are also serialized as cached data for ordinary actors.
ACTOR_CONDITIONS = frozenset(
    {
        "UseLegacyType",
        "HasStinger",
        "Not Interact",
        "RequiredItems",
        "BeginQuest",
        "Switch Item ID",
        "bUseCommonRequiredItem",
        "ActorLinkList",
        "KeyType",
        "KeyMaterialDataAsset",
        "bOpenByAISystem",
        "AddTagWhenSuccess",
        "AddTagWhenFailed",
        "SequenceActionConfigs",
        "Tags_CompletedInteract",
    }
)
FLOW_CONDITIONS = frozenset(
    {
        "RootFlow",
        "FlowPresetDataList",
        "IdentityTags",
        "NotifyTagsFromGraph",
        "NotifyTagsFromAnotherComponent",
        "TagsConcerned",
        "TagsWithSourceConcerned",
    }
)
ACTOR_FIELDS = ACTOR_CONDITIONS | {
    "Loot Item ID",
    "LootLevel",
    "RubbishType",
    "BP_PBZFlowComponent",
    "LevelSequenceAsset",
}


@dataclass(frozen=True)
class Export:
    name: str
    ordinal: int
    parent: int
    class_ref: int
    public_hash: int
    start: int
    end: int


def _package(data):
    names, _ = name_batch(data)
    header = unpack_from("<15I", data)
    payload, hash_table, import_table, export_table, bundles = (
        header[1], header[6], header[7], header[8], header[9]
    )
    if (
        header[0] != 0
        or not 60 <= hash_table <= import_table <= export_table <= bundles <= payload <= len(data)
        or (import_table - hash_table) % 8
        or (export_table - import_table) % 8
        or (bundles - export_table) % 72
    ):
        raise ValueError("Unsupported Zen package header")
    hashes = unpack_from(f"<{(import_table - hash_table) // 8}Q", data, hash_table)
    exports = []
    for entry in range(export_table, bundles, 72):
        offset, size, index, ordinal, parent, class_ref, _, _, public_hash = unpack_from(
            "<QQIIQQQQQ", data, entry
        )
        start = payload + offset
        end = start + size
        if index >= len(names) or end > len(data):
            raise ValueError("A Zen export is out of bounds")
        exports.append(Export(names[index], ordinal, parent, class_ref, public_hash, start, end))
    return names, hashes, exports


def _object_class(pointer, package_ids, hashes):
    if pointer >> 62 != 2:
        return None
    package_index = (pointer >> 32) & 0x3fffffff
    hash_index = pointer & 0xffffffff
    return package_ids[package_index], hashes[hash_index]


def _class_export(exports, class_name):
    (actor_class,) = (
        entry for entry in exports if entry.name == class_name and not entry.ordinal
    )
    return actor_class


def _device_classes(store, schemas):
    classes = {}
    base_defaults = {}
    for blueprint, source in DEVICES.items():
        path = f"{DEVICE_ROOT}{blueprint}.uasset"
        data = store.read_file(path)
        names, _, exports = _package(data)
        class_name = blueprint + "_C"
        actor_class = _class_export(exports, class_name)
        class_default = _class_export(exports, f"Default__{class_name}")
        local_defaults = dict(
            _read_fields(data, names, schemas, class_default, class_name, ACTOR_FIELDS)
        )
        defaults = base_defaults.get(source, {}) | local_defaults
        base_defaults.setdefault(source, defaults)
        identity = (_chunk_package_id(store, path), actor_class.public_hash)
        classes[identity] = class_name, source, defaults
    return classes


def _script_classes(store):
    classes = {}
    for path in SCRIPTED_REWARDS:
        _, _, exports = _package(store.read_file(path))
        class_name = PurePosixPath(path).stem + "_C"
        actor_class = _class_export(exports, class_name)
        classes[(_chunk_package_id(store, path), actor_class.public_hash)] = class_name
    return classes


def _read_fields(data, names, schemas, export, cls, requested):
    reader = AssetReader(data, names, schemas, export.start, export.end)
    schema = reader._schema(cls)
    limit = max(index for index, (name, _) in schema.items() if name in requested)
    for index, is_zero in reader._property_slots():
        if index > limit:
            break
        name, kind = schema[index]
        value = None if is_zero else reader.read_value(kind)
        if name in requested:
            yield name, value


def _active(value):
    if isinstance(value, tuple) and len(value) == 2:
        return any(value)
    return bool(value)


def _row_references(data, package, schemas, package_ids, classes):
    names, hashes, exports = package
    for export in exports:
        kind = classes.get(_object_class(export.class_ref, package_ids, hashes))
        if kind is not None:
            fields = _read_fields(data, names, schemas, export, kind, {"LootItemID"})
            for _, value in fields:
                if value is not None:
                    yield value


def _placements(data, package, path, schemas, package_ids, classes, row_names):
    names, hashes, exports = package
    candidates = []
    for number, export in enumerate(exports):
        device = classes.get(_object_class(export.class_ref, package_ids, hashes))
        if device is None or "_UAID_" not in export.name:
            continue
        cls, source, defaults = device
        props = {}
        unreadable = False
        try:
            props.update(_read_fields(data, names, schemas, export, cls, ACTOR_FIELDS))
        except (KeyError, IndexError, ValueError) as error:
            # An unreadable actor prevents proving uniqueness for a matching name.
            if "Loot Item ID" not in props:
                raise ValueError(
                    f"Cannot read reward actor {export.name} in {path}: {error}"
                ) from error
            unreadable = True
        # Chests have an ordinary class-level opening sequence; an instance
        # override is a distinct authored interaction.
        has_custom_sequence = _active(props.get("LevelSequenceAsset"))
        props = defaults | props
        row = props.get("Loot Item ID")
        if row not in row_names:
            continue
        protected = (
            unreadable
            or has_custom_sequence
            or props.get("RubbishType") != 1
            or any(_active(props.get(attr)) for attr in ACTOR_CONDITIONS)
        )
        flow = props.get("BP_PBZFlowComponent")
        if not protected and flow:
            if not 0 < flow <= len(exports) or exports[flow - 1].parent != number:
                protected = True
            else:
                try:
                    fields = _read_fields(
                        data, names, schemas, exports[flow - 1],
                        "BP_PBZFlowComponent_C", FLOW_CONDITIONS,
                    )
                    protected = any(_active(value) for _, value in fields)
                except (KeyError, IndexError, ValueError):
                    protected = True
        actor_name = export.name if not export.ordinal else f"{export.name}_{export.ordinal - 1}"
        info = {
            "source": source,
            "package": path,
            "cell": PurePosixPath(path).stem,
            "actor": actor_name,
            "actor_class": cls,
            "loot_level": props.get("LootLevel") or 0,
            "rubbish_type": props.get("RubbishType") or 0,
        }
        candidates.append((row, protected, info))
    return candidates


def scan(store, schemas, row_names):
    """Return uniquely placed, ordinary LevelLoot sources keyed by exact row name."""
    wanted = frozenset(row_names)
    if not wanted:
        return {}
    classes = _device_classes(store, schemas)
    scripts = _script_classes(store)
    device_packages = {package for package, _ in classes}
    script_packages = {package for package, _ in scripts}
    package_store = PackageStore(store)
    placements = defaultdict(list)
    scripted = set()
    for path in store.files:
        if not path.startswith("ProjectPBZ/") or not path.endswith((".umap", ".uasset")):
            continue
        package_ids = package_store.imports(path)
        placed = (
            path.startswith(MAP_ROOT)
            and path.endswith(".umap")
            and "/_Generated_/" in path
            and not device_packages.isdisjoint(package_ids)
        )
        has_script = not script_packages.isdisjoint(package_ids)
        if not placed and not has_script:
            continue
        data = store.read_file(path)
        package = _package(data)
        if has_script:
            scripted.update(_row_references(data, package, schemas, package_ids, scripts))
        if placed:
            for name, protected, info in _placements(
                data, package, path, schemas, package_ids, classes, wanted
            ):
                placements[name].append((protected, info))
    return {
        name: matches[0][1]
        for name, matches in sorted(placements.items())
        if len(matches) == 1 and not matches[0][0] and name not in scripted
    }
