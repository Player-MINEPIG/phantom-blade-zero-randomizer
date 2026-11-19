"""Route the reviewed boss awards through the same LevelLoot table as pickups."""

from hashlib import sha256
from struct import pack, pack_into, unpack_from

from integrations.weapons.movesets import PackageStore, _chunk_package_id
from integrations.weapons.zen import SingleExport, name_batch
from pbzmod import loot
from pbzmod.zen_names import NamePool
from . import flow_weapons as flow


TEMPLATE = flow.QUEST + "XiGu/BPF_YuEr_FJZL.uasset"
TEMPLATE_SHA = "b778ed7ead81238f5a2e47ddd5b94a52fbaecc27fdffacad1d1ca0a68eb1e90f"
NODE = "LootItems_C"
CLASS_PATH = flow.GRANT_CLASS.rsplit("/", 1)[0] + "/LootItems"
LOOT_PREFIX = bytes.fromhex("01020904")


def _replace_names(data, names):
    header = unpack_from("<15I", data)
    pad = (-names.end) % 8
    if unpack_from("<Q", data, names.end)[0] != pad or any(
        data[names.end + 8 : names.end + 8 + pad]
    ):
        raise ValueError("Unexpected name batch padding")
    prefix = data[:60] + names.serialize()
    padding = -len(prefix) % 8
    result = bytearray(
        prefix + pack("<Q", padding) + bytes(padding) + data[names.end + 8 + pad :]
    )
    delta = len(result) - len(data)
    pack_into("<I", result, 4, header[1] + delta)
    pack_into("<9I", result, 24, *(offset + delta for offset in header[6:15]))
    return result


def _reference(store):
    data = store.read_file(TEMPLATE)
    if sha256(data).hexdigest() != TEMPLATE_SHA:
        raise ValueError("Unsupported original LootItems reference graph")
    return data


def physical_rows(grants):
    """Stable FName instances, independent of the enabled subset or seed."""
    ordinal = {item: 1001 + idx for idx, (item, _) in enumerate(flow.REVIEWED.values())}
    return {id_: f"{NODE}_{ordinal[g.item]}" for id_, g in grants.items()}


def extend_table(store, data, grants):
    if sha256(data).hexdigest() != loot.ORIGINAL:
        raise ValueError("Unsupported original LevelLoot table")
    original_names = NamePool(data)
    rows = loot.read_table(data, original_names.names)
    offsets = [pos for pos, _ in rows.values()]
    ends = dict(zip(offsets, offsets[1:] + [len(data)]))
    aliases = physical_rows(grants)
    node_name = original_names.copy(NamePool(_reference(store)), NODE)
    added = bytearray()
    for id_, grant in grants.items():
        alias = aliases[id_]
        if alias in rows:
            raise ValueError(f"Reward row already exists: {alias}")
        source = flow._load(store, grant.path)
        item, main, _, _, instance = source.read_grant()
        if instance:
            raise ValueError("Expected an unnumbered weapon ID")
        index = original_names.copy(NamePool(source.data), item)
        # Copy the stock single-weapon row for this weapon category, including its quantity.
        template = "Xigu.001.Long" if main else "Xigu.001.UnnamedBow"
        position, fields = rows[template]
        payload = bytearray(data[position : ends[position]])
        old = fields[1][0][3][0][0]
        old_ref = pack("<II", original_names.names.index(old), 0)
        if payload.count(old_ref) != 1:
            raise ValueError("Ambiguous weapon field in stock row")
        pack_into("<II", payload, payload.index(old_ref), index, 0)
        key = pack("<II", node_name, int(alias.rsplit("_", 1)[1]) + 1)
        payload[:8] = payload[10:18] = key
        added.extend(payload)
    result = _replace_names(data, original_names)
    table = SingleExport(result)
    count_offset = table.start + 10
    if unpack_from("<I", result, count_offset)[0] != len(rows):
        raise ValueError("Unexpected LevelLoot table count")
    pack_into("<I", result, count_offset, len(rows) + len(grants))
    result.extend(added)
    pack_into("<Q", result, table.entry + 8, len(result) - table.start)
    checked = loot.select(bytes(result), original_names.names, set())
    for id_, row in aliases.items():
        if (
            checked[row].item != grants[id_].item
            or checked[row].category != grants[id_].category
        ):
            raise ValueError(f"Weapon row did not round-trip: {row}")
    return bytes(result)


def _object_hashes(data, names, node):
    h = unpack_from("<15I", data)
    for record in range(h[8], h[9], 72):
        ni, number = unpack_from("<II", data, record + 16)
        if names[ni] == node and number:
            refs = [unpack_from("<Q", data, record + offset)[0] for offset in (32, 48)]
            if not all(v >> 62 == 2 for v in refs) or refs[0] >> 32 != refs[1] >> 32:
                raise ValueError("Invalid class or template reference on reward node")
            indexes = [v & 0xFFFFFFFF for v in refs]
            return (
                (refs[0] >> 32) & 0x3FFFFFFF,
                indexes,
                [unpack_from("<Q", data, h[6] + 8 * i)[0] for i in indexes],
            )
    raise ValueError(f"Missing node {node}")


def redirect(store, grant, alias, reference, package_store):
    source = flow._load(store, grant.path)
    _, main, guid, _, _ = source.read_grant()
    names = NamePool(source.data)
    slot, hash_indices, _ = _object_hashes(source.data, names.names, "AddWeaponItem_C")
    _, _, new_hashes = _object_hashes(reference, NamePool(reference).names, NODE)
    node_name = names.copy(NamePool(reference), NODE, replace="AddWeaponItem_C")
    tmp = _replace_names(source.data, names)
    h = unpack_from("<15I", tmp)
    imports = NamePool(tmp, h[12])
    template_h = unpack_from("<15I", reference)
    if imports.names[slot] != flow.GRANT_CLASS or CLASS_PATH in imports.names:
        raise ValueError("Unexpected original quest class imports")
    for pos in range(h[7], h[8], 8):
        (ref,) = unpack_from("<Q", tmp, pos)
        if ref >> 62 != 2:
            continue
        uses_slot = (ref >> 32) & 0x3FFFFFFF == slot
        if uses_slot != ((ref & 0xFFFFFFFF) in hash_indices):
            raise ValueError(
                "A different import shares the original reward class or hash"
            )
    for index, value in zip(hash_indices, new_hashes):
        pack_into("<Q", tmp, h[6] + 8 * index, value)
    imports.copy(
        NamePool(reference, template_h[12]), CLASS_PATH, replace=flow.GRANT_CLASS
    )
    original_header = h[1]
    new_header = tmp[: h[12]] + imports.serialize() + tmp[imports.end : original_header]
    pack_into("<I", new_header, 4, len(new_header))
    payload = bytes(tmp[original_header:])
    pos = source.grant.offset
    name = pack("<II", node_name, int(alias.rsplit("_", 1)[1]) + 1)
    # Both stock nodes take one item FName and inherit the same GUID and pins.
    # The original main-weapon node has one additional bool preceding those fields.
    replacement = LOOT_PREFIX + payload[pos + 4 : pos + 8] + name
    body = payload[:pos] + replacement + payload[pos + 16 + main :]
    primary_delta = h[8] - source.summary[8]
    for entry in source.exports:
        record = entry.record + primary_delta
        if entry == source.grant:
            pack_into("<Q", new_header, record + 8, entry.size - int(main))
        elif entry.offset > pos:
            pack_into("<Q", new_header, record, entry.offset - int(main))
    result = bytes(new_header) + body
    check_h = unpack_from("<15I", result)
    check_names, _ = name_batch(result)
    recorded_slot, _, hashes = _object_hashes(result, check_names, NODE)
    check_imports, names_end = name_batch(result, check_h[12])
    if (
        check_imports[recorded_slot] != CLASS_PATH
        or hashes != new_hashes
        or names_end + 4 * len(check_imports) != check_h[1]
    ):
        raise ValueError("Rewritten quest has invalid LootItems imports")
    check_pos = check_h[1] + pos
    if (
        result[check_pos + 8 : check_pos + 16] != name
        or result[check_pos + 20 : check_pos + 36].hex() != guid
    ):
        raise ValueError("Rewritten reward lost its row key or original GUID")
    ids = package_store.imports(grant.path)
    if ids[slot] != _chunk_package_id(
        store, flow.FLOW_GRAPH + "FlowGraphNode/AddWeaponItem.uasset"
    ):
        raise ValueError("Quest container has an unexpected package dependency")
    ids[slot] = _chunk_package_id(
        store, flow.FLOW_GRAPH + "FlowGraphNode/LootItems.uasset"
    )
    return result, ids


def rewrite_changed(store, grants, assignments):
    aliases = physical_rows(grants)
    patches, dependencies = {}, {}
    reference = _reference(store)
    package_store = PackageStore(store)
    for id_, grant in grants.items():
        if assignments[id_] != grant.item:
            patches[grant.path], dependencies[grant.path] = redirect(
                store, grant, aliases[id_], reference, package_store
            )
    return patches, dependencies
