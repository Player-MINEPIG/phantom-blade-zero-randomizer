"""Verify the Peng Meng victory, Dread Axe, and chain fields in Steam build 26367565."""

import argparse
from hashlib import sha256
import importlib
import json
from pathlib import Path
from struct import unpack_from
import sys


CONTENT = "ProjectPBZ/Content/"
CELL = CONTENT + "Maps/B02/PBZ_Xigu_WP/_Generated_/82OBM6ICJZS18QDOP03KXFZHY.umap"
VICTORY_GRAPH = CONTENT + "PBZContent/Blueprint/FlowGraph/QuestFlowGraph/XiGu/BPF_FuLaoDaDeath.uasset"
WEAPON_TABLE = CONTENT + "PBZContent/DataTable/UI/DT_ShaqiWeaponData.uasset"
CHAIN = CONTENT + "RenewalContent/Actors/GameplayBlocker/BP_ChainBlocker.uasset"
BLOCKER_BASE = "ProjectPBZ/Plugins/Secret/AdvancedSpecialMove/Content/BP/Actor/SpecialMoveVolume/BP_GameplayBlocker_Base.uasset"

HASHES = {
    CELL: "1f28b748c3eed6a9d9bd8e05497f59a99e2f5a08254f95ca7a1eeaebc0a29c58",
    VICTORY_GRAPH: "83bb6583819eab1e8632fa5a3ab972eff6f64e4c11080bd57f3d434bc372eb54",
    WEAPON_TABLE: "a9b3a7f0795975bab7e7ed339f4da6a555594bc633f3ec30ca463b7b5b940be4",
    CHAIN: "9554d47aacfdea5627de4a4891d7cd0d442a594a8b717872fda472626e711408",
    BLOCKER_BASE: "73e999c30ff265aedd15dcce286797155d004774b9b2fee36b81e00b7dc8d813",
}


def inspect(store, name_batch):
    assets = {}
    names = {}
    for path, expected in HASHES.items():
        data = store.read_file(path)
        if sha256(data).hexdigest() != expected:
            raise ValueError(f"Asset does not match Steam build 26367565: {path}")
        assets[path] = data
        names[path], _ = name_batch(data)

    def name_at(path, offset):
        index, instance = unpack_from("<II", assets[path], offset)
        return names[path][index] if not instance else f"{names[path][index]}_{instance - 1}"

    mob_group, = unpack_from("<I", assets[CELL], 1212311)
    script_count, script, *_ = unpack_from("<4I", assets[CELL], 2024162)
    if (mob_group, script_count, script) != (1691, 3, 1713):
        raise ValueError("Boss spawner does not link to the reviewed group-clear script")

    values = {
        "spawner_id": name_at(CELL, 1212180),
        "boss_class": name_at(CELL, 1212196),
        "emitted_on_group_clear": name_at(CELL, 2025510),
        "observed_by_victory_graph": name_at(VICTORY_GRAPH, 11892),
        "reward_weapon": name_at(VICTORY_GRAPH, 9240),
        "weapon_ability_tag": name_at(WEAPON_TABLE, 52478),
        "chain_required_tag": name_at(CHAIN, 6778),
    }
    if values["emitted_on_group_clear"] != values["observed_by_victory_graph"]:
        raise ValueError("Boss clear script and victory graph use different tags")
    if values["chain_required_tag"] != values["weapon_ability_tag"]:
        raise ValueError("Weapon and chain interaction use different ability tags")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paks", type=Path, help="installed game's ProjectPBZ/Content/Paks directory")
    parser.add_argument("--reader-dir", type=Path, required=True, help="directory containing resources_reader.py")
    parser.add_argument("--oodle", type=Path, required=True, help="locally installed Oodle DLL")
    args = parser.parse_args()
    sys.path.insert(0, str(args.reader_dir.resolve()))
    try:
        reader = importlib.import_module("resources_reader")
        store = reader.IoStore(args.paks / "ProjectPBZ-Windows.utoc", reader.OodleReader(args.oodle))
        values = inspect(store, reader.name_batch)
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(values, indent=2))


if __name__ == "__main__":
    main()
