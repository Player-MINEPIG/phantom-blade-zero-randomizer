import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pbzmod.reward_receipts import classify_receipts, read_receipts, receipt_locations


class ReceiptTest(unittest.TestCase):
    def test_only_explicit_receipts_classify_the_reward(self):
        guid_a = "0123456789ABCDEF0123456789ABCDEF"
        guid_b = "11111111111111111111111111111111"
        guid_c = "22222222222222222222222222222222"
        guid_d = "33333333333333333333333333333333"
        locations = {
            "white": {"source": "map_pickup", "saveId": "world-white"},
            "chest": {"source": "chest", "saveId": "world-chest"},
            "ambiguous": {"source": "map_pickup", "saveId": "world-unsure"},
            "missing": {"source": "map_pickup", "saveId": "world-missing"},
            "boss": {"source": "boss", "nodeGuid": guid_a},
            "quest": {"source": "quest", "nodeGuids": [guid_b, guid_c]},
            "otherQuest": {"source": "quest", "nodeGuids": [guid_c, guid_d]},
            "mobs": {"source": "enemy_drop", "combatSaveId": "world-combat"},
            "otherMob": {"source": "enemy_drop", "combatSaveId": "world-other-combat"},
        }
        data = {
            "LevelActorManager": {
                "world-white": {"Destroy": True},
                "world-chest": {"SwitchState": False},
                "world-unsure": {"Destroy": "true"},
            },
            "EventPipeline": {"ExecuteNodeGuid": {
                guid_a.lower(): True,
                f"world-quest_123_{guid_b}": True,
                f"world-quest_456_{guid_c}": False,
            }},
            "PBZGameSystem": {"CompleteAddItemMobDomainNames": ["world-combat"]},
        }
        result = classify_receipts(data, locations)
        self.assertEqual(result.claimed, ("boss", "mobs", "quest", "white"))
        self.assertEqual(result.unknown, ("ambiguous", "missing", "otherMob", "otherQuest"))
        self.assertEqual(result.unclaimed, ("chest",))

    def test_empty_fields_and_inventory_do_not_guess(self):
        locations = {
            "white": {"source": "map_pickup", "saveId": "world-white"},
            "quest": {"source": "quest"},
            "combat": {"source": "enemy_drop", "combatSaveId": "world-combat"},
        }
        data = {
            "LevelActorManager": None,
            "EventPipeline": {"ExecuteNodeGuid": {}},
            "PBZGameSystem": {"CompleteAddItemMobDomainNames": []},
            "Inventory": {"AccessoryInfos": {"some-item": {"AcquiredCycle": 0}}},
        }
        result = classify_receipts(data, locations)
        self.assertEqual(result.claimed, ())
        self.assertEqual(result.unclaimed, ())
        self.assertEqual(result.unknown, ("combat", "quest", "white"))

    def test_reports_the_reviewed_failed_quest_separately_from_claimed_or_unknown(self):
        point = "FuJiZhiLin.AC_BreakDrink"
        guid = "ac8ecd33b92b5f4895957d8e45d9f602"
        points = receipt_locations([{"id": point, "source": "quest"}], {point: {
            "evidence": [{"node_class": "LootItems_C", "node_guid": guid}],
        }})
        records = [{"QuestClass": points[point]["failedQuestClass"],
                    "QuestCompletion": "EQuestCompletion::QC_Failed"}]
        data = {"Narrative": {"NarrativeSavedQuests": records}}
        result = classify_receipts(data, points)
        self.assertEqual(result.failed, (point,))
        self.assertEqual(result.claimed, ())
        self.assertEqual(result.unknown, ())
        data["EventPipeline"] = {"ExecuteNodeGuid": {points[point]["nodeGuids"][0]: True}}
        result = classify_receipts(data, points)
        self.assertEqual(result.claimed, (point,))
        self.assertEqual(result.failed, ())
        records[0]["QuestClass"] = "/Game/Unreviewed.OtherQuest_C"
        del data["EventPipeline"]
        self.assertEqual(classify_receipts(data, points).unknown, (point,))

    def test_uses_original_source_metadata_and_reads_only_an_explicit_json_file(self):
        rewards = [
            {"id": "white", "source": "map_pickup"},
            {"id": "quest", "source": "quest"},
            {"id": "grant:3322110077665544bbaa9988ffeeddcc", "source": "boss"},
        ]
        sources = {
            "white": {"actor": "BP_Rubbish_C_UAID_0",
                      "package": "ProjectPBZ/Content/Maps/B00/PBZ_WP/_Generated_/0.umap"},
            "quest": {"evidence": [
                {"node_class": "LootItems_C", "node_guid": "22446688aaccee001122334455667788"},
            ]},
        }
        locations = receipt_locations(rewards, sources)
        self.assertEqual(locations["white"]["saveId"], "PBZ_WP-BP_Rubbish_C_UAID_0")
        self.assertEqual(locations[rewards[2]["id"]]["nodeGuid"], "00112233445566778899AABBCCDDEEFF")
        self.assertEqual(locations["quest"]["nodeGuids"], ("8866442200EECCAA4433221188776655",))

        with TemporaryDirectory() as tmp:
            path = Path(tmp, "export.JSON")
            path.write_text(json.dumps({"LevelActorManager": {
                "PBZ_WP-BP_Rubbish_C_UAID_0": {"Destroy": True},
            }}), encoding="utf-8-sig")
            self.assertEqual(read_receipts(path, locations).claimed, ("white",))
            with self.assertRaisesRegex(ValueError, "already-exported"):
                read_receipts(Path(tmp, "save.sav"), locations)
            with self.assertRaisesRegex(ValueError, "one already-exported"):
                classify_receipts([], locations)


if __name__ == "__main__":
    unittest.main()
