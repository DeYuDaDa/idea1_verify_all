"""Pure-contract tests for bounded native inventory preparation."""
from __future__ import annotations

import copy
import unittest

from hard_inventory_prepare import ensure_native_inventory


def _object(object_id, object_type, x, *, pickupable=True, can_fill=False, receptacle=False):
    return {"objectId": object_id, "objectType": object_type, "pickupable": pickupable,
            "canFillWithLiquid": can_fill, "receptacle": receptacle,
            "position": {"x": x, "y": 0.9, "z": 0.0},
            "axisAlignedBoundingBox": {"center": {"x": x, "y": 1.0, "z": 0.0},
                                       "size": {"x": 0.1, "y": 0.2, "z": 0.1}}}


class _NativeRecord:
    def __init__(self, record):
        self.record = record


class _Session:
    def __init__(self, objects, *, mode="valid"):
        self.metadata = {"objects": copy.deepcopy(objects)}
        self.records = []
        self.mode = mode

    def snapshot(self):
        return copy.deepcopy(self.metadata)

    def step(self, action, *, raise_on_failure=False, **kwargs):
        if action == "Pass":
            record = {"index": len(self.records), "action": action, "kwargs": {},
                      "lastActionSuccess": True, "errorMessage": ""}
            self.records.append(record)
            return _NativeRecord(record)
        assert action == "CreateObjectAtLocation"
        index = len(self.records)
        oid = "Mug|original" if self.mode == "same_id" else f"Mug|spawn{index}"
        if self.mode in {"valid", "ineligible", "failed_with_change"}:
            row = _object(oid, "Mug", kwargs["position"]["x"],
                          can_fill=self.mode != "ineligible")
            row["parentReceptacles"] = ["CounterTop|surface"]
            self.metadata["objects"].append(row)
            surface = next(row for row in self.metadata["objects"]
                           if row["objectId"] == "CounterTop|surface")
            surface["receptacleObjectIds"] = sorted(set(surface.get("receptacleObjectIds", []) + [oid]))
        record = {"index": index, "action": action, "kwargs": kwargs,
                  "lastActionSuccess": self.mode != "failed_with_change",
                  "errorMessage": "simulated native failure" if self.mode == "failed_with_change" else ""}
        self.records.append(record)
        return _NativeRecord(record)


def _mug_scene():
    surface = _object("CounterTop|surface", "CounterTop", 0.0,
                      pickupable=False, receptacle=True)
    surface["axisAlignedBoundingBox"]["size"] = {"x": 1.2, "y": 0.1, "z": 1.0}
    return [_object("Mug|original", "Mug", 0.0, can_fill=True), surface]


class HardInventoryPrepareTests(unittest.TestCase):
    def test_existing_ineligible_object_is_not_a_new_id_or_qualified_inventory(self):
        session = _Session(_mug_scene() + [_object("Mug|not-fillable", "Mug", 0.2, can_fill=False)])
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["before_object_counts"]["Mug"], 1)
        self.assertEqual(result["status"], "added_and_verified")
        self.assertEqual(result["types"]["Mug"]["added_ids"], ["Mug|spawn0"])
        self.assertNotIn("Mug|not-fillable", result["after_ids"]["Mug"])

    def test_existing_inventory_does_not_issue_a_native_action(self):
        session = _Session(_mug_scene() + [_object("Mug|second", "Mug", 0.2, can_fill=True)])
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "already_sufficient")
        self.assertEqual(result["before_object_counts"]["Mug"], 2)
        self.assertEqual(result["action_receipts"], [])
        self.assertEqual(session.records, [])


    def test_short_inventory_requires_native_receipt_distinct_capable_id_and_relation(self):
        session = _Session(_mug_scene())
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "added_and_verified")
        self.assertEqual(result["after_object_counts"]["Mug"], 2)
        self.assertEqual(len(set(result["after_ids"]["Mug"])), 2)
        self.assertEqual(result["types"]["Mug"]["added_ids"], ["Mug|spawn0"])
        self.assertEqual(session.records[0]["action"], "CreateObjectAtLocation")
        self.assertIs(session.records[0]["kwargs"]["forceAction"], False)
        self.assertEqual(len(result["types"]["Mug"]["attempts"][0]["settle_receipts"]), 4)


    def test_public_history_blocks_scene_mutation(self):
        session = _Session(_mug_scene())
        result = ensure_native_inventory(session, ["H01"], history_started=True)
        self.assertEqual(result["status"], "blocked_public_history")
        self.assertEqual(session.records, [])


    def test_unrequested_group_does_not_mutate_inventory(self):
        session = _Session(_mug_scene())
        result = ensure_native_inventory(session, ["H05"])
        self.assertEqual(result["status"], "already_sufficient")
        self.assertEqual(result["required_counts"], {})
        self.assertEqual(session.records, [])

    def test_ineligible_created_object_stops_without_extra_spawns(self):
        session = _Session(_mug_scene(), mode="ineligible")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_incomplete")
        self.assertEqual(len(session.records), 1)
        self.assertEqual(result["types"]["Mug"]["attempts"][0]["status"], "created_object_ineligible")

    def test_same_id_success_receipt_is_not_counted_as_addition(self):
        session = _Session(_mug_scene(), mode="same_id")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_incomplete")
        self.assertEqual(result["types"]["Mug"]["attempts"][0]["status"], "unexpected_distinct_id_delta")

    def test_failed_receipt_with_scene_change_is_not_counted(self):
        session = _Session(_mug_scene(), mode="failed_with_change")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_incomplete")
        self.assertEqual(result["types"]["Mug"]["attempts"][0]["status"], "failed_receipt_with_scene_change")


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(HardInventoryPrepareTests))
    return suite
