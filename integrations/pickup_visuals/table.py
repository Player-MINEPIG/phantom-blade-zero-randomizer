"""Synchronize native loot display levels with the placed pickup effects."""

from integrations.weapons.zen import AssetReader, Field, SingleExport
from pbzmod import loot

from .visuals import encode_properties


ITEM_LEVEL = 6


def _replacement(asset, row, row_start, desired):
    cursor = loot.Cursor(asset.data, asset.names)
    cursor.pos = row_start + 8
    header = AssetReader(asset.data, asset.names, {}, cursor.pos, len(asset.data))
    if header._property_slots() != [(0, False), (1, False)]:
        raise ValueError(f"Unexpected pickup loot row header: {row}")
    cursor.pos = header.position
    if cursor.value("name") != row or cursor.take("i") != 1:
        raise ValueError(f"Expected a single pickup loot envelope: {row}")
    start = cursor.pos
    header.position = start
    slots = header._property_slots()
    cursor.pos = header.position
    chunks = {}
    for index, zero in slots:
        offset = cursor.pos
        if not zero:
            cursor.value(loot.FIELDS["level"][index])
        if index == ITEM_LEVEL and not zero:
            return Field(None, offset, cursor.pos), bytes([desired])
        chunks[index] = asset.data[offset:cursor.pos]
    chunks[ITEM_LEVEL] = bytes([desired])
    return Field(None, start, cursor.pos), encode_properties(chunks)


def align_table(table_bytes, report):
    """Write the inspected pickup colour to each corresponding LevelLoot row."""
    levels = {}
    for pickup in report:
        row, desired = pickup["row"], pickup["after_level"]
        if not isinstance(desired, int) or not 0 <= desired <= 18:
            raise ValueError(f"Invalid pickup display level for {row}")
        if levels.setdefault(row, desired) != desired:
            raise ValueError(f"Conflicting pickup display levels for {row}")
    if not levels:
        return table_bytes

    asset = SingleExport(table_bytes)
    rows = loot.read_table(table_bytes, asset.names)
    replacements = []
    for row, desired in levels.items():
        start, fields = rows[row]
        if len(fields[1]) != 1:
            raise ValueError(f"Expected a single pickup loot envelope: {row}")
        envelope = fields[1][0]
        if envelope.get(ITEM_LEVEL, 0) == desired:
            continue
        replacements.append(_replacement(asset, row, start, desired))
        envelope[ITEM_LEVEL] = desired
    if not replacements:
        return table_bytes

    result = asset.replace(replacements)
    updated = loot.read_table(result, asset.names)
    if {row: fields for row, (_, fields) in updated.items()} != {row: fields for row, (_, fields) in rows.items()}:
        raise ValueError("Pickup display level readback changed a loot reward")
    return result
