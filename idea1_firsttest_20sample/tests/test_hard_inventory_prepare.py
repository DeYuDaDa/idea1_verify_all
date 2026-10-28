"""Contract tests for bounded InitialRandomSpawn inventory preparation."""
from __future__ import annotations

import copy
import unittest

from hard_inventory_prepare import ensure_native_inventory


def _object(object_id, object_type, x, *, pickupable=True, can_fill=False,
            receptacle=False, parent_receptacles=None, receptacle_object_ids=None):
    return {"objectId": object_id, "objectType": object_type,
            "pickupable": pickupable, "canFillWithLiquid": can_fill,
            "receptacle": receptacle,
            "parentReceptacles": list(parent_receptacles or []),
            "receptacleObjectIds": list(receptacle_object_ids or []),
            "position": {"x": x, "y": 0.9, "z": 0.0}}


class _NativeRecord:
    def __init__(self, record):
        self.record = record


class _Session:
    def __init__(self, objects, *, mode="valid"):
        self.metadata = {"sceneName": "MockRoom", "objects": copy.deepcopy(objects)}
        self.records = []
        self.mode = mode

    def snapshot(self):
        return copy.deepcopy(self.metadata)

    def step(self, action, *, raise_on_failure=False, **kwargs):
        index = len(self.records)
        if action == "Pass":
            record = {"index": index, "action": action, "kwargs": {},
                      "lastActionSuccess": self.mode != "settle_failure",
                      "errorMessage": "simulated Pass failure" if self.mode == "settle_failure" else ""}
            self.records.append(record)
            return _NativeRecord(record)
        assert action == "InitialRandomSpawn"
        if self.mode != "no_change":
            for object_type, target_count in _duplicate_targets(kwargs):
                current = [row for row in self.metadata["objects"]
                           if row.get("objectType") == object_type]
                exemplar = current[0]
                for n in range(max(0, target_count - len(current))):
                    oid = f"{object_type}|native-copy-{n}"
                    capable = self.mode != "ineligible"
                    row = _object(
                        oid, object_type, 0.3 + n,
                        pickupable=True,
                        can_fill=(object_type == "Mug" and capable),
                        receptacle=(object_type == "Plate" and capable),
                        parent_receptacles=([] if self.mode == "bad_relation"
                                            else ["CounterTop|surface"]),
                    )
                    self.metadata["objects"].append(row)
                    if self.mode != "bad_relation":
                        surface = next(obj for obj in self.metadata["objects"]
                                       if obj["objectId"] == "CounterTop|surface")
                        surface["receptacleObjectIds"].append(oid)
                # Simulate the native action moving an existing pickupable and
                # rebuilding its ID. The verification must use state, not IDs.
                if self.mode == "ids_rebuilt":
                    old_id = exemplar["objectId"]
                    exemplar["objectId"] = f"{object_type}|rebuilt-original"
                    surface = next(obj for obj in self.metadata["objects"]
                                   if obj["objectId"] == "CounterTop|surface")
                    surface["receptacleObjectIds"] = [
                        exemplar["objectId"] if child_id == old_id else child_id
                        for child_id in surface["receptacleObjectIds"]
                    ]
        record = {"index": index, "action": action, "kwargs": kwargs,
                  "lastActionSuccess": self.mode != "failed_with_change",
                  "errorMessage": "simulated native failure" if self.mode == "failed_with_change" else ""}
        self.records.append(record)
        return _NativeRecord(record)


def _duplicate_targets(kwargs):
    # Match the documented serialized ObjectTypeCount request shape.
    return [(item["objectType"], item["count"])
            for item in kwargs["numDuplicatesOfType"]]


def _mug_scene(*, extra_mug=False, mug_fill=True):
    surface = _object("CounterTop|surface", "CounterTop", 0.0,
                      pickupable=False, receptacle=True)
    original = _object("Mug|original", "Mug", 0.0, can_fill=mug_fill,
                       parent_receptacles=["CounterTop|surface"])
    surface["receptacleObjectIds"] = ["Mug|original"]
    rows = [original, surface]
    if extra_mug:
        rows.append(_object("Mug|second", "Mug", 0.2, can_fill=True,
                            parent_receptacles=["CounterTop|surface"]))
        surface["receptacleObjectIds"].append("Mug|second")
    return rows


def _plate_scene():
    surface = _object("CounterTop|surface", "CounterTop", 0.0,
                      pickupable=False, receptacle=True)
    plate = _object("Plate|original", "Plate", 0.0, receptacle=True,
                    parent_receptacles=["CounterTop|surface"])
    surface["receptacleObjectIds"] = ["Plate|original"]
    return [plate, surface]


class HardInventoryPrepareTests(unittest.TestCase):
    def test_short_inventory_uses_one_target_total_native_request_and_verifies_state(self):
        session = _Session(_mug_scene())
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "added_and_verified")
        self.assertEqual(result["after_object_counts"]["Mug"], 2)
        self.assertEqual(len(result["after_ids"]["Mug"]), 2)
        self.assertEqual(session.records[0]["action"], "InitialRandomSpawn")
        self.assertEqual(session.records[0]["kwargs"]["numDuplicatesOfType"],
                         [{"objectType": "Mug", "count": 2}])
        self.assertEqual(session.records[0]["kwargs"]["forceVisible"], True)
        self.assertTrue(result["types"]["Mug"]["relation_check"]["verified"])
        self.assertEqual(result["before_snapshot"]["objects"][0]["objectId"], "Mug|original")
        self.assertTrue(result["after_snapshot"]["objects"])
        self.assertEqual(sum(row["action"] == "InitialRandomSpawn" for row in session.records), 1)

    def test_native_id_rebuild_does_not_break_count_based_verification(self):
        session = _Session(_mug_scene(), mode="ids_rebuilt")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "added_and_verified")
        self.assertIn("Mug|rebuilt-original", result["after_ids"]["Mug"])
        self.assertNotIn("added_ids", result["types"]["Mug"])

    def test_sufficient_inventory_does_not_operate(self):
        session = _Session(_mug_scene(extra_mug=True))
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "already_sufficient")
        self.assertEqual(result["action_receipts"], [])
        self.assertEqual(session.records, [])
        self.assertIs(result["before_snapshot"], result["after_snapshot"])

    def test_missing_native_exemplar_is_unavailable_without_mutation(self):
        session = _Session([_object("CounterTop|surface", "CounterTop", 0.0,
                                    pickupable=False, receptacle=True)])
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_unavailable")
        self.assertEqual(session.records, [])

    def test_target_total_request_does_not_claim_replacement_for_ineligible_inventory(self):
        session = _Session(_mug_scene(extra_mug=True, mug_fill=False))
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_unavailable")
        self.assertEqual(session.records, [])

    def test_plate_keeps_strict_pickupable_and_receptacle_gate(self):
        session = _Session(_plate_scene())
        result = ensure_native_inventory(session, ["H02"])
        self.assertEqual(result["status"], "added_and_verified")
        self.assertEqual(result["after_object_counts"]["Plate"], 2)
        self.assertTrue(all(row["pickupable"] and row["receptacle"]
                            for row in result["after_snapshot"]["objects"]
                            if row.get("objectType") == "Plate"))

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

    def test_native_success_without_actual_count_gain_is_incomplete(self):
        session = _Session(_mug_scene(), mode="no_change")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_incomplete")
        self.assertFalse(result["types"]["Mug"]["count_verified"])

    def test_ineligible_native_duplicate_fails_capability_check(self):
        session = _Session(_mug_scene(), mode="ineligible")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_incomplete")
        self.assertFalse(result["types"]["Mug"]["capabilities_verified"])

    def test_broken_bidirectional_relation_fails_verification(self):
        session = _Session(_mug_scene(), mode="bad_relation")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_incomplete")
        self.assertFalse(result["types"]["Mug"]["relation_check"]["verified"])

    def test_failed_settling_receipt_fails_stability_gate(self):
        session = _Session(_mug_scene(), mode="settle_failure")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_incomplete")
        self.assertFalse(result["types"]["Mug"]["stability_verified"])

    def test_failed_native_receipt_never_counts_as_success(self):
        session = _Session(_mug_scene(), mode="failed_with_change")
        result = ensure_native_inventory(session, ["H01"])
        self.assertEqual(result["status"], "inventory_incomplete")
        self.assertIs(result["native_action"]["lastActionSuccess"], False)
        self.assertEqual(len(session.records), 1)


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(HardInventoryPrepareTests))
    return suite
