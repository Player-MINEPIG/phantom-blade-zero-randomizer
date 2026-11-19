"""Move reviewed complete weapon configs while retaining the target model imports."""

from bisect import bisect_left
from struct import pack, pack_into, unpack_from

from .stats import TABLE_FOLDER, patch_stats, read_config, read_weapons
from .zen import SingleExport, name_batch


# Both configs use the same two-handed attachment layout and a single weapon
# actor. Neither row has a tempered override or config-level owning behavior.
SUPPORTED = frozenset({"BaiYing", "RenOuYanYueDao"})
MAIN_TABLE = TABLE_FOLDER + "DT_WeaponData.uasset"


def _chunk_package_id(store, path):
    start = 144 + store.files[path] * 12
    if store.data[start + 11] != 1:
        raise ValueError(f"Not a package chunk: {path}")
    return unpack_from("<Q", store.data, start)[0]


class PackageStore:
    def __init__(self, store):
        self.store = store
        index = next(i for i in range(store.count) if store.data[144 + i * 12 + 11] == 6)
        original = store.read_chunk(index)
        magic, version, _, count = unpack_from("<IIQI", original)
        if magic != 0x496F436E or version != 5:
            raise ValueError("Unexpected PBZ package store header")
        self.package_ids = unpack_from(f"<{count}Q", original, 20)
        size_offset = 20 + count * 8
        size, = unpack_from("<I", original, size_offset)
        self.entries = memoryview(original)[size_offset + 4:size_offset + 4 + size]

    def imports(self, path):
        pid = _chunk_package_id(self.store, path)
        index = bisect_left(self.package_ids, pid)
        if index >= len(self.package_ids) or self.package_ids[index] != pid:
            raise ValueError(f"No package-store entry for {path}")
        offset = index * 16
        count, relative = unpack_from("<II", self.entries, offset)
        return list(unpack_from(f"<{count}Q", self.entries, offset + relative))


class Imports:
    def __init__(self, package, package_ids):
        self.asset = package
        self.package_ids = package_ids
        data = package.data
        self.offsets = unpack_from("<9I", data, 24)
        hashes, objects, exports, bundles, dep_headers, dep_entries, imports, cell_imports, cell_exports = self.offsets
        if cell_imports != bundles or cell_exports != bundles or dep_entries - dep_headers != 20:
            raise ValueError("Unsupported weapon export dependencies")
        self.hashes = list(unpack_from(f"<{(objects - hashes) // 8}Q", data, hashes))
        self.objects = list(unpack_from(f"<{(exports - objects) // 8}Q", data, objects))
        self.names, numbers = name_batch(data, imports)
        if len(self.names) != len(package_ids) or numbers + len(self.names) * 4 != package.start:
            raise ValueError("Weapon package import names disagree with the original container")
        self.name_numbers = unpack_from(f"<{len(self.names)}I", data, numbers)
        self.name_entries = self._name_entries(imports)

    def _name_entries(self, start):
        data = self.asset.data
        count = len(self.names)
        hashes = start + 16
        headers = hashes + count * 8
        position = headers + count * 2
        entries = []
        for index in range(count):
            header = data[headers + index * 2:headers + index * 2 + 2]
            size = int.from_bytes(header, "big")
            width = (size & 0x7fff) * (2 if size & 0x8000 else 1)
            entries.append((data[hashes + index * 8:hashes + index * 8 + 8], header, data[position:position + width]))
            position += width
        return entries

    def resolve(self, object_index):
        if not -len(self.objects) <= object_index < 0:
            raise ValueError("Expected an imported weapon actor")
        pointer = self.objects[-object_index - 1]
        if pointer >> 62 != 2:
            raise ValueError("Expected an imported package object")
        package = (pointer >> 32) & 0x3fffffff
        return package, self.hashes[pointer & 0xffffffff]

    def _append_name(self, source, index):
        entries = [*self.name_entries, source.name_entries[index]]
        numbers = [*self.name_numbers, source.name_numbers[index]]
        data = self.asset.data
        hash_version = data[self.offsets[6] + 8:self.offsets[6] + 16]
        if hash_version != source.asset.data[source.offsets[6] + 8:source.offsets[6] + 16]:
            raise ValueError("Imported package name hashes use different versions")
        strings = b"".join(entry[2] for entry in entries)
        return (
            pack("<II", len(entries), len(strings)) + hash_version
            + b"".join(entry[0] for entry in entries) + b"".join(entry[1] for entry in entries)
            + strings + pack(f"<{len(numbers)}I", *numbers)
        )

    def replace_actor(self, field, source, source_field):
        if field.end - field.start != 4 or source_field.end - source_field.start != 4:
            raise ValueError("Unsupported serialized weapon actor")
        source_package, export_hash = source.resolve(source_field.value)
        pid = source.package_ids[source_package]
        data = self.asset.data
        hashes, objects, exports, bundles, dep_headers, dep_entries, imports, _, _ = self.offsets
        if pid in self.package_ids:
            new_package = self.package_ids.index(pid)
            names = data[imports:self.asset.start]
            package_ids = self.package_ids
        else:
            new_package = len(self.package_ids)
            names = self._append_name(source, source_package)
            package_ids = [*self.package_ids, pid]

        if export_hash in self.hashes:
            hash_index = self.hashes.index(export_hash)
            export_hashes = data[hashes:objects]
        else:
            hash_index = len(self.hashes)
            export_hashes = data[hashes:objects] + pack("<Q", export_hash)
        pointer = (2 << 62) | (new_package << 32) | hash_index
        if pointer in self.objects:
            ref = -self.objects.index(pointer) - 1
            return self.asset.replace([(field, pack("<i", ref))]), package_ids

        new_ref = -len(self.objects) - 1
        first, *counts = unpack_from("<5I", data, dep_headers)
        if first != 0 or dep_entries + 4 * sum(counts) != imports:
            raise ValueError("Unexpected weapon dependency table")
        old_dependencies = unpack_from(f"<{sum(counts)}i", data, dep_entries)
        # Use the original weapon actor's load order for its replacement.
        if old_dependencies.count(field.value) != 1:
            raise ValueError("Expected one original weapon-actor dependency")
        source_position = old_dependencies.index(field.value)
        group = next(index for index in range(len(counts)) if source_position < sum(counts[:index + 1]))
        counts[group] += 1
        insert_at = dep_entries + 4 * (source_position + 1)
        updated_entries = data[dep_entries:insert_at] + pack("<i", new_ref) + data[insert_at:imports]
        header = bytearray(data[:hashes])
        for offset, section in (
            (24, export_hashes),
            (28, data[objects:exports] + pack("<Q", pointer)),
            (32, data[exports:bundles]),
            (36, data[bundles:dep_headers]),
            (40, pack("<5I", first, *counts)),
            (44, updated_entries),
            (48, names),
        ):
            pack_into("<I", header, offset, len(header))
            header.extend(section)
        new_bundles = unpack_from("<I", header, 36)[0]
        pack_into("<II", header, 52, new_bundles, new_bundles)
        pack_into("<I", header, 4, len(header))
        changed = self.asset.replace([(field, pack("<i", new_ref))])
        return bytes(header) + changed[self.asset.start:], package_ids


def _weapon_actor(fields):
    display = fields["Display Data"].value
    if len(display) != 1 or display[0]["ScabbardMesh"].value:
        raise ValueError("Expected a single weapon mesh without a scabbard override")
    if any(field.value for name, field in fields.items() if name.startswith("Owning ")):
        raise ValueError("Weapon config has unsupported owning effects or abilities")
    slots = display[0]
    sockets = tuple(slots[name].value for name in ("ArmedSocket", "UnarmedSocket", "ScabbardSocket"))
    return slots["WeaponClass"], sockets


def _remap_table(data, schemas, movesets):
    package = SingleExport(data)
    reader = package.reader(schemas)
    if reader.read("10s") != bytes.fromhex("0003f9ffffff00000000"):
        raise ValueError("Unsupported weapon lookup table")
    configs = {}
    for _ in range(reader.count()):
        reader.name()
        fields = reader.properties("WeaponData")
        id_ = fields["ItemId"].value
        if id_ in movesets:
            configs[id_] = fields["WeaponConfig"]
    if reader.position != reader.end or configs.keys() != movesets.keys():
        raise ValueError("Weapon moveset table rows do not match the assignment")
    return package.replace([
        (configs[target], data[configs[donor].start:configs[donor].end])
        for target, donor in movesets.items()
    ])


def build_patches(store, schemas, stats, movesets):
    """Return (cooked path → modified bytes, cooked path → replacement package IDs)."""
    swaps = {target: source for target, source in movesets.items() if target != source}
    if not swaps:
        return patch_stats(store, schemas, stats), {}
    if swaps.keys() != SUPPORTED or set(swaps.values()) != SUPPORTED:
        raise ValueError("Native moveset swapping currently supports only the BaiYing and RenOuYanYueDao pair")
    weapons = read_weapons(store, schemas)
    if any(id_ not in weapons or weapons[id_].tempered for id_ in SUPPORTED):
        raise ValueError("Weapon config paths do not match the reviewed moveset pair")

    # Each donor config receives the stat assignment of the item now using it.
    remapped_stats = {swaps.get(target, target): source for target, source in stats.items()}
    for target, donor in swaps.items():
        remapped_stats[donor] = stats.get(target, target)
    patches = patch_stats(store, schemas, remapped_stats)
    dependencies = PackageStore(store)
    models = {}
    for id_ in SUPPORTED:
        weapon = weapons[id_]
        package = SingleExport(store.read_file(weapon.base))
        field, sockets = _weapon_actor(read_config(package, schemas, weapon.config_schema))
        models[id_] = (Imports(package, dependencies.imports(weapon.base)), field, sockets)

    header_updates = {}
    for target_id, donor_id in swaps.items():
        target_imports, target_actor, target_sockets = models[target_id]
        weapon = weapons[donor_id]
        donor_imports = models[donor_id][0]
        config = SingleExport(patches.get(weapon.base, donor_imports.asset.data))
        original_fields = read_config(config, schemas, weapon.config_schema)
        donor_actor, donor_sockets = _weapon_actor(original_fields)
        if donor_sockets != target_sockets or not original_fields.get("Weapon Combos"):
            raise ValueError("Weapon sockets or combo configuration differ from the reviewed pair")
        updated, package_ids = Imports(config, donor_imports.package_ids).replace_actor(
            donor_actor, target_imports, target_actor,
        )
        result = SingleExport(updated)
        fields = read_config(result, schemas, weapon.config_schema)
        updated_actor, updated_sockets = _weapon_actor(fields)
        new_imports = Imports(result, package_ids)
        source_pkg, source_hash = target_imports.resolve(target_actor.value)
        new_pkg, new_hash = new_imports.resolve(updated_actor.value)
        if (
            package_ids[new_pkg] != target_imports.package_ids[source_pkg] or new_hash != source_hash
            or updated_sockets != target_sockets
            or any(result.data[fields[name].start:fields[name].end] != config.data[previous.start:previous.end]
                   for name, previous in original_fields.items() if name != "Display Data")
        ):
            raise ValueError("Re-read weapon config changed a field outside the model import")
        patches[weapon.base] = updated
        if package_ids != donor_imports.package_ids:
            header_updates[weapon.base] = package_ids
    patches[MAIN_TABLE] = _remap_table(store.read_file(MAIN_TABLE), schemas, swaps)
    return patches, header_updates
