"""Identify movable text items from the retail inventory table."""

from hashlib import sha256

from integrations.weapons.zen import SingleExport


INVENTORY = "ProjectPBZ/Content/PBZContent/DataTable/Item/DT_InventoryData.uasset"
INVENTORY_SHA256 = "9bd49f00745d39b08dde6fa3ef8ce1b7020baa00b5e1c5842293625facf6ab65"
BOOK = 1
BOOK_PAGE = 2
LETTER = 3
TEXT_TYPES = {BOOK, BOOK_PAGE, LETTER}
EMPTY_ASSET = ("None", "None", "")


def _has_gameplay_effect(fields):
    for name in ("AddTagWhenHas", "AddTagWhenUse"):
        tag = fields.get(name)
        if tag and tag["TagName"].value not in (None, "None"):
            return True
    return (
        bool(fields.get("DialogueGroupIDs"))
        or fields.get("ItemDetailType") not in (None, 0)
        or any(fields.get(name) not in (None, EMPTY_ASSET) for name in ("RunFlowAsset", "ItemGA", "AddAttributeGE"))
    )


def read_text_items(store, schemas):
    """Return game item IDs for text without a task tag or an attached gameplay action."""
    data = store.read_file(INVENTORY)
    if sha256(data).hexdigest() != INVENTORY_SHA256:
        raise ValueError("Inventory table does not match Steam 26367565")
    reader = SingleExport(data).reader(schemas)
    if reader.read("10s") != bytes.fromhex("0003f9ffffff00000000"):
        raise ValueError("Unsupported InventoryData preamble")
    text = {}
    for _ in range(reader.count()):
        reader.name()
        fields = {name: field.value for name, field in reader.properties("PBZItemDataStruct").items()}
        item = fields.get("ItemId")
        if fields.get("ItemType") not in TEXT_TYPES or item in (None, "None"):
            continue
        if item in text:
            raise ValueError(f"Duplicate text item ID {item!r}")
        text[item] = fields
    if reader.position != len(data):
        raise ValueError("Unparsed bytes after the last inventory row")

    permitted = {item for item, fields in text.items() if not _has_gameplay_effect(fields)}
    return frozenset(
        item for item in permitted
        if text[item]["ItemType"] != BOOK_PAGE
        or (text[item].get("IntegrationItemID") in permitted and text[text[item]["IntegrationItemID"]]["ItemType"] == BOOK)
    )
