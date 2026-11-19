"""Build the randomizer catalog from the pinned PBZArchipelago release data."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from zipfile import ZipFile


RELEASE = "v0.9.2"
CATALOG_VERSION = "pbz-archipelago-v0.9.2"
WORLD_SHA256 = "da70dc999d7fe193756378b2a8dadab567d005b8b7425b22f0745d380bbc7731"
MOD_SHA256 = "780a0cc3719e459b3e706ecbdda9d5f28985f6e41c8aea019b5f1ef9f065392c"
SOURCE_BY_CONTAINER = {"chest": "chest", "pickup": "map_pickup"}
ACTOR_BY_CONTAINER = {"chest": r"BP_Chest_C", "pickup": r"BP_Rubbish(?:_[a-zA-Z])?_C"}
SUPPORTED_ITEMS = {
    "materials": re.compile(r"(?:Weapon_Material_\d{2}|Ac_Material_\d+|Medi_Material_\d+)"),
    "reforge": re.compile(r"Return_(?:ShaqiWeapon|Weapon)_1"),
    "treasure": re.compile(r"T_\d{5}"),
}
LUA_REWARD = re.compile(
    r'^  \[(?P<check_id>\d+)\]=\{s="(?P<save_id>[^"\\]+)", '
    r'p=\{[^}\n]*\}, v=\{(?P<items>.*)\}\},$',
    re.MULTILINE,
)
LUA_STRING_LIST = re.compile(r'"[A-Za-z0-9_]+"(?:, "[A-Za-z0-9_]+")*')


def _read_release_member(path, expected_sha256, member):
    if sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError(f"{path.name} does not match PBZArchipelago {RELEASE}")
    with ZipFile(path) as archive:
        return archive.read(member).decode("utf-8-sig")


def convert(world_path, mod_path):
    data = json.loads(_read_release_member(world_path, WORLD_SHA256, "phantom_blade_zero/data.json"))
    lua = _read_release_member(mod_path, MOD_SHA256, "PBZArchipelago/Scripts/locations_data.lua")
    bridge_rewards = {}
    for entry in LUA_REWARD.finditer(lua):
        check_id = int(entry["check_id"])
        serialized = entry["items"]
        if check_id in bridge_rewards or not LUA_STRING_LIST.fullmatch(serialized):
            raise ValueError(f"Invalid Lua reward record for check {check_id}")
        bridge_rewards[check_id] = (entry["save_id"], re.findall(r'"([^"]+)"', serialized))

    items = {}
    rewards = {}
    bridge_checks = {}
    bridge_items = {}
    for location in data["locations"].values():
        container = location.get("container")
        if container not in SOURCE_BY_CONTAINER:
            continue
        name = location["item"]
        item = data["items"][name]
        cid = item["cid"]
        supported_ids = SUPPORTED_ITEMS.get(location["cat"])
        if not supported_ids or item["cat"] != location["cat"] or item["grant"] != "prop":
            continue
        if not supported_ids.fullmatch(cid):
            continue
        check_id = location["id"]
        save_id = location["saveId"]
        if bridge_rewards.get(check_id) != (save_id, [cid]):
            continue
        actor_pattern = ACTOR_BY_CONTAINER[container]
        if not re.fullmatch(rf"[\w]+-{actor_pattern}_UAID_[\w]+", save_id):
            continue
        if save_id in rewards:
            raise ValueError(f"Duplicate reward point {save_id!r}")
        bridge_item = {"grant": item["grant"], "name": name, "ap_item_id": item["id"]}
        if cid in bridge_items and bridge_items[cid] != bridge_item:
            raise ValueError(f"Ambiguous metadata for item {cid!r}")
        items[cid] = {"id": cid, "category": "collectible"}
        rewards[save_id] = {"id": save_id, "item": cid, "source": SOURCE_BY_CONTAINER[container]}
        bridge_checks[save_id] = check_id
        bridge_items[cid] = bridge_item

    if not rewards:
        raise ValueError("The release did not yield any supported reward records")
    catalog = {
        "version": CATALOG_VERSION,
        "items": [items[cid] for cid in sorted(items)],
        "rewards": [rewards[save_id] for save_id in sorted(rewards)],
        "encounters": [],
    }
    bridge_map = {"version": CATALOG_VERSION, "checks": bridge_checks, "items": bridge_items}
    return catalog, bridge_map


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path, help="upstream phantom_blade_zero.apworld")
    parser.add_argument("mod", type=Path, help="upstream PBZArchipelago.zip")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        catalog, bridge_map = convert(args.world, args.mod)
        args.output.mkdir(parents=True, exist_ok=True)
        for basename, content in (("catalog", catalog), ("bridge-map", bridge_map)):
            path = args.output / f"{basename}.upstream-{RELEASE}.json"
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            print(path)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
