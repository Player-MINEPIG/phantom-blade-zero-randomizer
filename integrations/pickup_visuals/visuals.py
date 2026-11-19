"""Follow final LevelLoot prizes on placed BP_Rubbish Niagara components."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from struct import pack, pack_into, unpack_from

from integrations.weapons.movesets import PackageStore
from integrations.weapons.zen import AssetReader, SingleExport, name_batch
from pbzmod import loot
from pbzmod.zen_names import NamePool


MAP_ROOT = "ProjectPBZ/Content/Maps/"
INVENTORY = "ProjectPBZ/Content/PBZContent/DataTable/Item/DT_InventoryData.uasset"
NIAGARA_COMPONENT = 0x76937DE93B4BF840
ACTOR_LEVELS = ("Item Level", "Item Level By LootTable", "MaxLevel")
WEAPON_LEVEL = 18
ACCESSORY_LEVEL = 17


@dataclass(frozen=True)
class Template:
    cell: str
    actor: str
    asset: str


# Each template is an original placed Niagara component, including its native
# user parameters. S4 is the original locked-door key effect (K_02006).
TEMPLATES = {
    0: Template("71S0SGBQHQ1QYNI3AHZ2E29E6", "BP_Rubbish_C_UAID_E89C25A751205AD602_1827873373", "NS_Item_WhiteDust_003"),
    1: Template("B16SRKHZ35HU512T3GJY8J6YJ", "BP_Rubbish_C_UAID_60CF84809909589302_1658736340", "NS_BlueLight_Small"),
    2: Template("5GGKIOJBJSMT4UES6X0DOYMPT", "BP_Rubbish_C_UAID_60CF848099095FA502_1392443842", "NS_PurpleLightBeam_Small"),
    3: Template("E8I8C9MR4LOCT7B74XRCSTW5P", "BP_Rubbish_C_UAID_74563C6BC2BDF08D02_1620053046", "NS_OrangeLightBeam_Big"),
    4: Template("9YYUHGGSTDPWB5LBOVSPUH6S2", "BP_Rubbish_C_UAID_CC28AACAD5F9174602_2033399211", "NS_GreenFlameS"),
    5: Template("1OV32RGDU0IINITA3QEQ6H4JU", "BP_Rubbish_C_UAID_60CF84809909049902_1131205080", "NS_Item_WhiteDust_002"),
    6: Template("ENCQPH3GLHLHDKBJRSL3WRKNS", "BP_Rubbish_C_UAID_60CF8480990943FD02_1086948674", "NS_Item_WhiteDust_002"),
    7: Template("CLP7FKYZP1ZLUH4NGN3O3RUKV", "BP_Rubbish_C_UAID_E89C25A750C707DB02_1267476202", "NS_Item_WhiteDust_001"),
    8: Template("BFI1A3JLDZFC68N7MJGD1XI3A", "BP_Rubbish_C_UAID_CC28AACAD5F9625702_1770448387", "NS_Item_Green"),
    9: Template("5GGKIOJBJSMT4UES6X0DOYMPT", "BP_Rubbish_C_UAID_60CF848099095FA502_1392443842", "NS_PurpleLightBeam_Small"),
    11: Template("BABNU2TWLSIJVH5GVZPUXKNWJ", "BP_Rubbish_C_UAID_74563C6BC2BDB9F502_2031630963", "NS_PurpleLightBeam_Big"),
    12: Template("B16SRKHZ35HU512T3GJY8J6YJ", "BP_Rubbish_C_UAID_60CF84809909589302_1658736340", "NS_BlueLight_Small"),
    13: Template("EEZ984E6NKW9XXGQOA3YYDISU", "BP_Rubbish_C_UAID_74563CC57EE2693A02_1906345835", "NS_BlueLight"),
    14: Template("6NWKZNOL6IVE40JZ5JRTGEHRR", "BP_Rubbish_C_UAID_60CF8480990999F202_2034092033", "NS_BlueLight_Big"),
    15: Template("0GDM8KBWMV8YLXPS1I25IDB1C", "BP_Rubbish_C_UAID_E89C25A751205B8D02_1258473895", "NS_OrangeLightBeam_Small"),
    17: Template("E8I8C9MR4LOCT7B74XRCSTW5P", "BP_Rubbish_C_UAID_74563C6BC2BDF08D02_1620053046", "NS_OrangeLightBeam_Big"),
    18: Template("BYC5XC7YZXVINFQBOZURNLZSD", "BP_Rubbish_C_UAID_60CF848217CAD4F902_2037423808", "NS_Item_Technicolor"),
}

EFFECT_COLORS = {
    "NS_Item_WhiteDust_001": "white",
    "NS_Item_WhiteDust_002": "white",
    "NS_Item_WhiteDust_003": "white",
    "NS_Item_Green": "green",
    "NS_Item_Technicolor": "orange_red",
    "NS_GreenFlameS": "green",
    "NS_OrangeLightBeam": "orange",
    "NS_OrangeLightBeam_Big": "orange",
    "NS_OrangeLightBeam_Small": "orange",
    "NS_BlueLight": "blue",
    "NS_BlueLight_Small": "blue",
    "NS_BlueLight_Big": "blue",
    "NS_BlueLightBeam": "blue",
    "NS_PurpleLightBeam": "purple",
    "NS_PurpleLightBeam_Small": "purple",
    "NS_PurpleLightBeam_Big": "purple",
}


class VisualReader(AssetReader):
    NATIVE_STRUCTS = AssetReader.NATIVE_STRUCTS | {"Guid": "16s"}

    def __init__(self, *args):
        super().__init__(*args)
        self.names_read = []
        self.objects_read = []

    def name(self):
        self.names_read.append(self.position)
        return super().name()

    def read_value(self, kind):
        if kind == (4,):
            self.objects_read.append(self.position)
        if kind in ((9, "NiagaraVariable"), (9, "NiagaraVariableWithOffset")):
            name = self.name()
            type_def = self.properties("NiagaraTypeDefinition")
            value = self.read("i") if kind[1] == "NiagaraVariableWithOffset" else self.read(f"{self.count()}s")
            return name, type_def, value
        return super().read_value(kind)


@dataclass(frozen=True)
class Export:
    index: int
    start: int
    end: int
    class_ref: int


@dataclass(frozen=True)
class Pickup:
    actor: Export
    component: Export
    levels: tuple[int, ...]
    row: str
    asset: int
    effect: str
    override_start: int
    override_end: int
    override_names: tuple
    override_objects: tuple

    @property
    def level(self):
        return self.levels[0]


class WorldCell:
    def __init__(self, data, schemas, package_ids):
        self.data = data
        self.schemas = schemas
        self.summary = unpack_from("<15I", data)
        self.start = self.summary[1]
        h, i, e, b, dh, de, names = self.summary[6:13]
        if (self.summary[0] or self.summary[13:15] != (b, b) or
                not 60 <= h <= i <= e <= b <= dh <= de <= names <= self.start <= len(data) or
                (i - h) % 8 or (e - i) % 8 or (b - e) % 72 or (de - dh) != (b - e) // 72 * 20):
            raise ValueError("Unsupported pickup world-cell header")
        self.names = NamePool(data, 60)
        self.package_names = NamePool(data, names)
        self.package_ids = list(package_ids)
        count = len(self.package_names.names)
        if count != len(self.package_ids) or self.package_names.end + count * 4 != self.start:
            raise ValueError("Pickup dependency names disagree with the package store")
        self.package_numbers = list(unpack_from(f"<{count}I", data, self.package_names.end))
        self.hashes = list(unpack_from(f"<{(i - h) // 8}Q", data, h))
        self.objects = list(unpack_from(f"<{(e - i) // 8}Q", data, i))
        self.exports = []
        self.actor_ids = {}
        for index, offset in enumerate(range(e, b, 72)):
            rel, size, name, number, _, cls = unpack_from("<QQIIQQ", data, offset)
            export = Export(index, self.start + rel, self.start + rel + size, cls)
            if not self.start <= export.start <= export.end <= len(data):
                raise ValueError("Pickup export outside world cell")
            self.exports.append(export)
            actor = self.names.names[name]
            if "_UAID_" in actor and actor.startswith("BP_Rubbish"):
                identifier = actor if number == 0 else f"{actor}_{number - 1}"
                self.actor_ids[identifier] = export
        self.dependencies = bytearray(data[de:names])
        self.changes = {}

    def reader(self, export):
        return VisualReader(self.data, self.names.names, self.schemas, export.start, export.end)

    def imported_name(self, pointer):
        if pointer >> 62 != 2:
            raise ValueError("Expected a package import in a pickup cell")
        return self.package_names.names[(pointer >> 32) & 0x3fffffff]

    def object_pointer(self, ref):
        if not -len(self.objects) <= ref < 0:
            raise ValueError("Pickup references an unexpected local object")
        return self.objects[-ref - 1]

    def object_identity(self, ref):
        if not ref:
            return None
        if ref > 0:
            if ref > len(self.exports):
                raise ValueError("Niagara override references an invalid local export")
            return "local", ref
        pointer = self.object_pointer(ref)
        if pointer >> 62 == 2:
            package = self.package_ids[(pointer >> 32) & 0x3fffffff]
            return package, self.hashes[pointer & 0xffffffff]
        if pointer >> 62 == 1:
            return pointer
        raise ValueError("Unsupported Niagara object identity")

    def actor_class(self, actor):
        blueprint = self.imported_name(actor.class_ref).rsplit("/", 1)[-1]
        if blueprint not in {"BP_Rubbish", "BP_Rubbish_A", "BP_Rubbish_b", "BP_Rubbish_C"}:
            raise ValueError("Unexpected pickup actor class")
        return blueprint + "_C"

    def pickup(self, identifier):
        actor = self.actor_ids[identifier]
        props = self.reader(actor).properties(self.actor_class(actor))
        component_ref = props["Niagara"].value
        if component_ref is None or not 0 < component_ref <= len(self.exports):
            raise ValueError("Pickup does not reference a local Niagara component")
        component = self.exports[component_ref - 1]
        if component.class_ref != NIAGARA_COMPONENT:
            raise ValueError("Unexpected pickup Niagara component class")
        reader = self.reader(component)
        fields = reader.properties("PBZNiagaraComponent")
        asset = fields["Asset"].value
        override = fields.get("OverrideParameters")
        if override is None or override.value is None:
            raise ValueError("Pickup Niagara component is missing its parameter store")
        if override.start != fields["Asset"].end:
            raise ValueError("Unexpected Niagara field layout")
        levels = tuple((props[name].value or 0) if name in props else 0 for name in ACTOR_LEVELS)
        return Pickup(
            actor, component, levels,
            props["Loot Item ID"].value, asset, self.imported_name(self.object_pointer(asset)),
            override.start, override.end,
            tuple(pos for pos in reader.names_read if override.start <= pos < override.end),
            tuple(pos for pos in reader.objects_read if override.start <= pos < override.end),
        )

    def copy_object(self, source, ref):
        if ref == 0:
            return 0
        pointer = source.object_pointer(ref)
        if pointer >> 62 == 2:
            src = (pointer >> 32) & 0x3fffffff
            pid = source.package_ids[src]
            if pid not in self.package_ids:
                if source.package_names.names[src] in self.package_names.names:
                    raise ValueError("Duplicate pickup import name has a different package ID")
                self.package_names.append_from(source.package_names, src)
                self.package_ids.append(pid)
                self.package_numbers.append(source.package_numbers[src])
            hashed = source.hashes[pointer & 0xffffffff]
            if hashed not in self.hashes:
                self.hashes.append(hashed)
            pointer = (2 << 62) | (self.package_ids.index(pid) << 32) | self.hashes.index(hashed)
        elif pointer >> 62 != 1:
            raise ValueError("Unsupported Niagara template object reference")
        if pointer not in self.objects:
            self.objects.append(pointer)
        return -1 - self.objects.index(pointer)

    def signature(self, pickup):
        """Compare the effect and parameters independently of per-cell indices."""
        start = pickup.override_start
        override = bytearray(self.data[start:pickup.override_end])
        names = []
        objects = []
        for pos in pickup.override_names:
            index, ordinal = unpack_from("<II", self.data, pos)
            names.append((pos - start, self.names.names[index], ordinal))
            pack_into("<II", override, pos - start, 0, 0)
        for pos in pickup.override_objects:
            ref = unpack_from("<i", self.data, pos)[0]
            objects.append((pos - start, self.object_identity(ref)))
            pack_into("<i", override, pos - start, 0)
        return self.object_identity(pickup.asset), bytes(override), tuple(names), tuple(objects)

    def change_effect(self, target, source, appearance):
        new_ref = self.copy_object(source, appearance.asset)
        override = bytearray(source.data[appearance.override_start:appearance.override_end])
        for pos in appearance.override_names:
            index = unpack_from("<I", source.data, pos)[0]
            translated = self.names.append_from(source.names, index)
            pack_into("<I", override, pos - appearance.override_start, translated)
        for pos in appearance.override_objects:
            ref = unpack_from("<i", source.data, pos)[0]
            # Reviewed overrides reference registered Niagara type definitions.
            # An external UObject would also need a separate dependency bundle.
            if ref and source.object_pointer(ref) >> 62 != 1:
                raise ValueError("Pickup template adds an unreviewed Niagara override dependency")
            pack_into("<i", override, pos - appearance.override_start, self.copy_object(source, ref))
        start = target.component.start
        asset_start = target.override_start - 4
        self.changes[target.component.index] = (
            self.data[start:asset_start] + pack("<i", new_ref) + override
            + self.data[target.override_end:target.component.end]
        )
        pack_into("<i", self.dependencies, 4 * self.effect_dependency(target), new_ref)

    def effect_dependency(self, target):
        first, *counts = unpack_from("<5i", self.data, self.summary[10] + 20 * target.component.index)
        if first < 0 or any(count < 0 for count in counts) or 4 * (first + sum(counts)) > len(self.dependencies):
            raise ValueError("Bad Niagara export dependency range")
        indices = [index for index in range(first, first + sum(counts))
                   if unpack_from("<i", self.dependencies, 4 * index)[0] == target.asset]
        if len(indices) != 1:
            raise ValueError("Expected one dependency on the previous Niagara asset")
        return indices[0]

    def change_levels(self, actor, level):
        reader = self.reader(actor)
        schema = reader._schema(self.actor_class(actor))
        original = dict(reader._property_slots())
        payload = {}
        for index, zero in original.items():
            start = reader.position
            if not zero:
                reader.read_value(schema[index][1])
            payload[index] = self.data[start:reader.position]
        for index, (name, _) in schema.items():
            if name in ACTOR_LEVELS:
                payload[index] = bytes([level]) if level else b""
        self.changes[actor.index] = encode_properties(payload) + self.data[reader.position:actor.end]

    def serialize(self):
        h, i, e, b, dh, de, _ = self.summary[6:13]
        original_end = name_batch(self.data)[1]
        padding = unpack_from("<Q", self.data, original_end)[0]
        if padding != -original_end % 8:
            raise ValueError("Unexpected pickup name padding")
        header = bytearray(self.data[:60] + self.names.serialize())
        new_pad = -len(header) % 8
        header.extend(pack("<Q", new_pad) + bytes(new_pad))
        header.extend(self.data[original_end + 8 + padding:h])
        export_table = bytearray(self.data[e:b])
        pos = self.start
        body = bytearray()
        for export in sorted(self.exports, key=lambda entry: entry.start):
            if export.start < pos:
                raise ValueError("Overlapping pickup world-cell exports")
            body.extend(self.data[pos:export.start])
            replacement = self.changes.get(export.index, self.data[export.start:export.end])
            pack_into("<QQ", export_table, export.index * 72, len(body), len(replacement))
            body.extend(replacement)
            pos = export.end
        body.extend(self.data[pos:])
        sections = (
            pack(f"<{len(self.hashes)}Q", *self.hashes), pack(f"<{len(self.objects)}Q", *self.objects),
            export_table, self.data[b:dh], self.data[dh:de], self.dependencies,
            self.package_names.serialize() + pack(f"<{len(self.package_numbers)}I", *self.package_numbers),
        )
        for offset, section in enumerate(sections, 6):
            pack_into("<I", header, 4 * offset, len(header))
            header.extend(section)
        pack_into("<I", header, 4, len(header))
        bundles = unpack_from("<I", header, 36)[0]
        pack_into("<II", header, 52, bundles, bundles)
        return bytes(header + body)


def encode_properties(payload):
    """Rebuild an unversioned header while preserving all untouched values."""
    fragments = []
    chunks = []
    zero_count = 0
    cursor = 0
    for index, value in sorted(payload.items()):
        while index - cursor > 127:
            fragments.append(127)
            cursor += 127
        fragment = (index - cursor) | (1 << 9)
        if not value:
            fragment |= 128
            zero_count += 1
        fragments.append(fragment)
        chunks.append(value)
        cursor = index + 1
    if not fragments:
        fragments.append(0)
    fragments[-1] |= 1 << 8
    mask_size = 0 if not zero_count else (zero_count + 7) // 8 if zero_count <= 16 else 4 * ((zero_count + 31) // 32)
    mask = ((1 << zero_count) - 1).to_bytes(mask_size, "little")
    return pack(f"<{len(fragments)}H", *fragments) + mask + b"".join(chunks)


def inventory_levels(store, schemas):
    asset = SingleExport(store.read_file(INVENTORY))
    reader = asset.reader(schemas)
    if reader.read("10s") != bytes.fromhex("0003f9ffffff00000000"):
        raise ValueError("Unsupported inventory table preamble")
    count = reader.count()
    items = {}
    for _ in range(count):
        reader.name()
        fields = reader.properties("PBZItemDataStruct")
        if fields.get("ItemId") and fields["ItemId"].value:
            level = fields.get("ItemLevel")
            items[fields["ItemId"].value] = (level.value or 0) if level else 0
    if reader.position != reader.end:
        raise ValueError("Unparsed bytes in the inventory table")
    return items


def prize_visual(level_data, item_levels):
    if len(level_data) != 1:
        raise ValueError("Pickup must resolve to one native loot envelope")
    level = level_data[0]
    for key, category, override_level in ((3, "weapon", WEAPON_LEVEL), (5, "accessory", ACCESSORY_LEVEL), (2, "item", None)):
        entries = level.get(key, [])
        if entries:
            if len(entries) != 1:
                raise ValueError("Pickup must resolve to one displayed prize")
            item = entries[0][0]
            return category, item, item_levels[item] if override_level is None else override_level
    if level.get(1):
        return "dust", loot._dust_id(level[1]), level.get(6, 0)
    if level.get(4) and len(level[4]) == 1:
        return "medicine", level[4][0][0], level.get(6, 0)
    raise ValueError("Unknown native pickup prize")


def apply(store, schemas, level_loot_bytes, world_sources, patches, changed_rows):
    """Return the merged map patches, dependency overrides, and per-pickup readbacks.

    `world_sources` may list several placements for one row. A placement's
    `package` or `cell` locates its map and `actor` identifies an exact export.
    `patches` supplies already changed maps, such as the monster shuffle.
    """
    placements = defaultdict(list)
    paths = {PurePosixPath(path).stem: path for path in store.files
             if path.startswith(MAP_ROOT) and path.endswith(".umap") and "/_Generated_/" in path}
    for row in sorted(set(changed_rows)):
        source = world_sources.get(row, ())
        for entry in (source,) if isinstance(source, dict) else source:
            if entry["source"] == "map_pickup":
                path = entry.get("package") or paths[PurePosixPath(entry["cell"]).stem]
                placements[path].append((row, entry["actor"]))
    if not placements:
        return {}, {}, []
    items = inventory_levels(store, schemas)
    rows = loot.read_table(level_loot_bytes, name_batch(level_loot_bytes)[0])
    package_store = PackageStore(store)
    templates = {}
    modified = {}
    dependencies = {}
    report = []
    for path, actors in sorted(placements.items()):
        original = store.read_file(path)
        data = patches.get(path, original)
        package_ids = package_store.imports(path)
        cell = WorldCell(data, schemas, package_ids)
        before = []
        for row, identifier in sorted(set(actors)):
            pickup = cell.pickup(identifier)
            if pickup.row != row:
                raise ValueError(f"Pickup {identifier} no longer references {row}")
            category, item, level = prize_visual(rows[row][1][1], items)
            if level not in templates:
                anchor = TEMPLATES[level]
                template_path = paths[anchor.cell]
                source = WorldCell(store.read_file(template_path), schemas, package_store.imports(template_path))
                appearance = source.pickup(anchor.actor)
                if appearance.effect.rsplit("/", 1)[-1] != anchor.asset:
                    raise ValueError(f"Unexpected vanilla pickup effect for level {level}")
                templates[level] = source, appearance, source.signature(appearance)
            source, appearance, signature = templates[level]
            effect_changed = cell.signature(pickup) != signature
            if effect_changed:
                cell.change_effect(pickup, source, appearance)
            if pickup.levels != (level,) * len(ACTOR_LEVELS):
                cell.change_levels(pickup.actor, level)
            before.append((row, identifier, pickup, signature, level, category, item, effect_changed))
        if cell.changes:
            rewritten = cell.serialize()
            modified[path] = rewritten
            if cell.package_ids != package_ids:
                dependencies[path] = cell.package_ids
            cell = WorldCell(rewritten, schemas, cell.package_ids)
        for row, identifier, pickup, signature, level, category, item, effect_changed in before:
            final = cell.pickup(identifier)
            desired_levels = (level,) * len(ACTOR_LEVELS)
            if (final.row, cell.signature(final), final.levels) != (row, signature, desired_levels):
                raise ValueError(f"Pickup visual readback failed for {identifier}")
            if effect_changed:
                cell.effect_dependency(final)
            report.append({
                "row": row, "package": path, "actor": identifier, "item": item, "category": category,
                "before_effect": pickup.effect, "after_effect": final.effect,
                "before_color": EFFECT_COLORS.get(pickup.effect.rsplit("/", 1)[-1]),
                "after_color": EFFECT_COLORS[final.effect.rsplit("/", 1)[-1]],
                "before_level": pickup.level, "after_level": final.level,
                "effect_changed": effect_changed,
            })
    return modified, dependencies, report
