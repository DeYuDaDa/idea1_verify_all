"""Unittest contracts for instance-conditional native mechanism checks."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from hard_contracts import validate_instance_contract


def _obj(oid, **values):
    return {"objectId": oid, **values}


def _ctx(group, roles, before, after, event):
    return SimpleNamespace(group_id=group, roles=roles, before_target={"objects": before},
                           after_target={"objects": after}, target_event=event)


def _failed(checks):
    return [row["name"] for row in checks if not row["passed"]]


class HardContractTests(unittest.TestCase):
    def test_h01_empty_target_changes_to_coffee_but_water_target_is_preserved(self):
        roles = {"A": "mug-a", "B": "mug-b", "M": "machine"}
        before = [_obj("mug-a", isFilledWithLiquid=False, fillLiquid=None),
                  _obj("mug-b", isFilledWithLiquid=True, fillLiquid="water"),
                  _obj("machine", isToggled=True)]
        after = [_obj("mug-a", isFilledWithLiquid=True, fillLiquid="coffee"),
                 _obj("mug-b", isFilledWithLiquid=True, fillLiquid="water"),
                 _obj("machine", isToggled=True)]
        ctx = _ctx("H01", roles, before, after,
                   {"action": "PutObject", "subject": "A", "destination": "M", "success": True})
        checks = validate_instance_contract(ctx)
        self.assertEqual(_failed(checks), [])
        self.assertFalse(any("expected_answer" in row for row in checks))

        before[0].update(isFilledWithLiquid=True, fillLiquid="water")
        after[0].update(isFilledWithLiquid=True, fillLiquid="water")
        checks = validate_instance_contract(ctx)
        self.assertEqual(_failed(checks), [])

    def test_h01_unexpected_replacement_of_nonempty_target_fails_instance_contract(self):
        roles = {"A": "mug-a", "B": "mug-b", "M": "machine"}
        before = [_obj("mug-a", isFilledWithLiquid=True, fillLiquid="water"),
                  _obj("mug-b", isFilledWithLiquid=False, fillLiquid=None),
                  _obj("machine", isToggled=True)]
        after = [_obj("mug-a", isFilledWithLiquid=True, fillLiquid="coffee"),
                 _obj("mug-b", isFilledWithLiquid=False, fillLiquid=None),
                 _obj("machine", isToggled=True)]
        checks = validate_instance_contract(_ctx("H01", roles, before, after,
            {"action": "PutObject", "subject": "A", "destination": "M", "success": True}))
        self.assertIn("H01_target_liquid_transition", _failed(checks))

    def test_h02_native_carrier_prediction_flags_unchanged_contained_apple(self):
        roles = {"P": "plate-p", "Q": "plate-q", "X": "apple"}
        before = [_obj("plate-p", receptacle=True, position={"x": 0, "y": 0, "z": 0}, receptacleObjectIds=["apple"]),
                  _obj("plate-q", receptacle=True, position={"x": 1, "y": 0, "z": 0}, receptacleObjectIds=[]),
                  _obj("apple", receptacle=False, position={"x": 0, "y": 0.1, "z": 0}, parentReceptacles=["plate-p"])]
        after = [_obj("plate-p", receptacle=True, position={"x": 0.4, "y": 0, "z": 0}, receptacleObjectIds=["apple"]),
                 _obj("plate-q", receptacle=True, position={"x": 1, "y": 0, "z": 0}, receptacleObjectIds=[]),
                 _obj("apple", receptacle=False, position={"x": 0, "y": 0.1, "z": 0}, parentReceptacles=["plate-p"])]
        checks = validate_instance_contract(_ctx("H02", roles, before, after,
            {"action": "PickupObject", "subject": "P", "success": True}))
        self.assertIn("X_world_displacement", _failed(checks))
        self.assertNotIn("Q_world_displacement", _failed(checks))

    def test_h03_both_containers_hot_is_a_conditional_instance_failure(self):
        roles = {"KA": "knob-a", "KB": "knob-b", "BA": "burner-a", "BB": "burner-b",
                 "X": "kettle", "Y": "pot"}
        before = [_obj("knob-a", isToggled=False, controlledObjects=["burner-a"]),
                  _obj("knob-b", isToggled=False, controlledObjects=[{"objectId": "burner-b"}]),
                  _obj("burner-a", isToggled=False, receptacleObjectIds=["kettle"]),
                  _obj("burner-b", isToggled=False, receptacleObjectIds=["pot"]),
                  _obj("kettle", temperature="RoomTemp", parentReceptacles=["burner-a"]),
                  _obj("pot", temperature="RoomTemp", parentReceptacles=["burner-b"])]
        after = [_obj("knob-a", isToggled=True), _obj("knob-b", isToggled=False),
                 _obj("burner-a", isToggled=True), _obj("burner-b", isToggled=False),
                 _obj("kettle", temperature="Hot", parentReceptacles=["burner-a"]),
                 _obj("pot", temperature="Hot", parentReceptacles=["burner-b"])]
        checks = validate_instance_contract(_ctx("H03", roles, before, after,
            {"action": "ToggleObjectOn", "subject": "KA", "success": True}))
        self.assertIn("H03_Y_temperature", _failed(checks))
        self.assertNotIn("expected_answer", repr(checks))

    def test_h04_uses_native_recursive_membership_without_unique_path_claim(self):
        roles = {"P": "plate", "B": "bowl", "X": "apple"}
        before = [_obj("plate", receptacle=True, position={"x": 0, "y": 0, "z": 0}, receptacleObjectIds=["bowl"]),
                  _obj("bowl", receptacle=True, position={"x": 0, "y": 0.1, "z": 0}, parentReceptacles=["plate"],
                       receptacleObjectIds=["apple"]),
                  _obj("apple", receptacle=False, position={"x": 0, "y": 0.2, "z": 0}, parentReceptacles=["bowl", "plate"])]
        after = [_obj("plate", receptacle=True, position={"x": 0.3, "y": 0, "z": 0}, receptacleObjectIds=["bowl"]),
                 _obj("bowl", receptacle=True, position={"x": 0.3, "y": 0.1, "z": 0}, parentReceptacles=["plate"],
                      receptacleObjectIds=["apple"]),
                 _obj("apple", receptacle=False, position={"x": 0.3, "y": 0.2, "z": 0}, parentReceptacles=["bowl", "plate"])]
        checks = validate_instance_contract(_ctx("H04", roles, before, after,
            {"action": "PickupObject", "subject": "P", "success": True}))
        self.assertEqual(_failed(checks), [])
        self.assertTrue(all(row["detail"].get("graph_paths_are_not_claimed_unique", True) for row in checks))

    def test_missing_relation_is_unavailable_not_a_global_refutation(self):
        ctx = _ctx("H05", {"Microwave": "mw", "Z": "potato"},
                   [_obj("mw", isToggled=False, isOpen=False), _obj("potato", isCooked=False)],
                   [_obj("mw", isToggled=True, isOpen=False), _obj("potato", isCooked=True, temperature="Hot")],
                   {"action": "ToggleObjectOn", "subject": "Microwave", "success": True})
        checks = validate_instance_contract(ctx)
        relation = next(row for row in checks if row["name"] == "H05_native_inside_outside")
        self.assertFalse(relation["passed"])
        self.assertEqual(relation["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()

