"""Classify reward receipts in a player-supplied, single-snapshot JSON export."""

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
from struct import unpack


PLACED_FIELDS = {"map_pickup": "Destroy", "chest": "SwitchState"}
COMBAT_KEY = {
    "Xigu.AC_ActHit": "BP_MobDomain_C_UAID_BCFCE7058A8B5BA302_1983989132+MobGroupScript_AddItemAfterCombat_C_0",
}
FAILED_QUEST = {
    "FuJiZhiLin.AC_BreakDrink": "/Game/PBZstory/PBZQuest/Simple/JiuSiFuShang.JiuSiFuShang_C",
}
GUID = re.compile(r"[0-9a-fA-F]{32}")


@dataclass(frozen=True)
class ReceiptSummary:
    claimed: tuple[str, ...]
    unknown: tuple[str, ...]
    unclaimed: tuple[str, ...]
    failed: tuple[str, ...] = ()


def _cooked_guid(value):
    if isinstance(value, str) and GUID.fullmatch(value):
        return "".join(f"{word:08X}" for word in unpack("<4I", bytes.fromhex(value)))
    return None


def receipt_locations(rewards, sources):
    """Build known save identifiers from the original asset catalogue."""
    locations = {}
    for reward in rewards:
        point = reward["id"]
        source = reward["source"]
        location = {"source": source}
        info = sources.get(point, {})
        if source in PLACED_FIELDS and info.get("actor") and info.get("package"):
            package = PurePosixPath(info["package"])
            if package.parent.name == "_Generated_":
                location["saveId"] = f"{package.parent.parent.name}-{info['actor']}"
                location["saveField"] = PLACED_FIELDS[source]
        elif source == "boss" and point.startswith("grant:"):
            location["nodeGuid"] = _cooked_guid(point.removeprefix("grant:"))
        elif source == "quest":
            evidence = info.get("evidence", ())
            guids = tuple(
                _cooked_guid(entry.get("node_guid"))
                for entry in evidence if entry.get("node_class") == "LootItems_C"
            )
            if guids and len(guids) == len(evidence) and all(guids):
                location["nodeGuids"] = guids
                if point in FAILED_QUEST:
                    location["failedQuestClass"] = FAILED_QUEST[point]
        elif source == "enemy_drop" and point in COMBAT_KEY:
            location["combatSaveId"] = COMBAT_KEY[point]
        locations[point] = location
    return locations


def _dictionary(value):
    return value if isinstance(value, dict) else {}


def _guid(value):
    if not isinstance(value, str):
        return None
    compact = value.replace("-", "").strip("{}")
    return compact.upper() if GUID.fullmatch(compact) else None


def classify_receipts(document, locations):
    """Use explicit native receipts only. Missing, empty and unsupported data stays unknown."""
    if not isinstance(document, dict):
        raise ValueError("Supply one already-exported save snapshot as a JSON object")
    actors = _dictionary(document.get("LevelActorManager"))
    pipeline = _dictionary(document.get("EventPipeline"))
    game = _dictionary(document.get("PBZGameSystem"))
    narrative = _dictionary(document.get("Narrative"))
    quest_records = narrative.get("NarrativeSavedQuests")
    failed_quests = set()
    if isinstance(quest_records, list):
        for value in quest_records:
            record = _dictionary(value)
            name = record.get("QuestClass")
            if isinstance(name, str) and record.get("QuestCompletion") == "EQuestCompletion::QC_Failed":
                failed_quests.add(name.casefold())
    combat_receipts = game.get("CompleteAddItemMobDomainNames")
    combat = {value for value in combat_receipts if isinstance(value, str)} if isinstance(combat_receipts, list) else set()

    node_receipts = {}
    for key, value in _dictionary(pipeline.get("ExecuteNodeGuid")).items():
        guid = _guid(key.rsplit("_", 1)[-1])
        if guid:
            node_receipts.setdefault(guid, set()).add(value if type(value) is bool else None)

    classified = {True: [], False: [], None: []}
    failed = []
    for point, location in sorted(locations.items()):
        source = location.get("source")
        status = None
        if source in PLACED_FIELDS:
            actor = _dictionary(actors.get(location.get("saveId")))
            field = PLACED_FIELDS[source]
            flag = actor.get(field)
            if type(flag) is bool:
                status = flag
        elif source in {"boss", "quest"}:
            candidates = location.get("nodeGuids") or (location.get("nodeGuid"),)
            flags = [node_receipts.get(_guid(guid), set()) for guid in candidates]
            if any(True in flag for flag in flags):
                status = True
            elif location.get("failedQuestClass", "").casefold() in failed_quests:
                failed.append(point)
                continue
            elif flags and all(flag == {False} for flag in flags):
                status = False
        elif source == "enemy_drop" and location.get("combatSaveId") in combat:
            status = True
        classified[status].append(point)

    return ReceiptSummary(tuple(classified[True]), tuple(classified[None]), tuple(classified[False]), tuple(failed))


def read_receipts(path, locations):
    """Open an already exported JSON file supplied by the player."""
    path = Path(path)
    if path.suffix.casefold() != ".json":
        raise ValueError("Reward receipts require an already-exported .json file")
    return classify_receipts(json.loads(path.read_text(encoding="utf-8-sig")), locations)
