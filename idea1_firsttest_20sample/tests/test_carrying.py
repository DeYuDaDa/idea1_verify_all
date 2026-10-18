import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

from generator import CaseBuilder, ConstructionError
from runtime import StepResult


class FakeSession:
    """Metadata-backed P20 fixture; it never creates an AI2-THOR controller."""

    def __init__(self):
        self.scene = "FloorPlan1"
        self.records = []
        self.controller = SimpleNamespace(last_event=SimpleNamespace(metadata={}))
        self._metadata = {
            "objects": [
                {"objectId": "Plate|1", "objectType": "Plate", "pickupable": True,
                 "receptacle": True, "position": {"x": 0.0, "y": 0.8, "z": 0.0},
                 "parentReceptacles": [], "receptacleObjectIds": []},
                {"objectId": "Apple|1", "objectType": "Apple", "pickupable": True,
                 "position": {"x": 0.0, "y": 0.9, "z": 0.0},
                 "parentReceptacles": [], "receptacleObjectIds": []},
                {"objectId": "Counter|1", "objectType": "CounterTop", "receptacle": True,
                 "position": {"x": 0.0, "y": 0.75, "z": 0.0},
                 "parentReceptacles": [], "receptacleObjectIds": []},
            ],
            "agent": {"inventoryObjects": []},
        }

    def snapshot(self, result=None):
        return copy.deepcopy(result.metadata if result is not None else self._metadata)

    def find_object(self, object_type, *, origin=None):
        return next((copy.deepcopy(obj) for obj in self._metadata["objects"]
                     if obj["objectType"] == object_type), None)

    def inventory(self):
        return copy.deepcopy(self._metadata["agent"]["inventoryObjects"])

    def save_pngs(self, result, directory, *, stem, include_instance=True):
        return {"rgb": str(Path(directory) / f"{stem}.png"), "instance": None}


class FakeOps:
    """Replace only simulator-facing actions; CaseBuilder checks stay real."""

    def __init__(self, session, *, move_apple=True, lose_support_on_freeze=False):
        self.session = session
        self.move_apple = move_apple
        self.lose_support_on_freeze = lose_support_on_freeze
        self.look_count = 0

    def _obj(self, object_id):
        return next(obj for obj in self.session._metadata["objects"]
                    if obj["objectId"] == object_id)

    def place_initial(self, object_id, receptacle_id):
        child = self._obj(object_id)
        old_parents = child.get("parentReceptacles") or []
        for old_id in old_parents:
            parent = self._obj(old_id)
            parent["receptacleObjectIds"] = [oid for oid in parent.get("receptacleObjectIds", []) if oid != object_id]
        child["parentReceptacles"] = [receptacle_id]
        parent = self._obj(receptacle_id)
        children = parent.setdefault("receptacleObjectIds", [])
        if object_id not in children:
            children.append(object_id)
        child["position"] = dict(parent["position"])

    def look(self, object_id):
        self.look_count += 1
        if self.lose_support_on_freeze and self.look_count == 2:
            apple = self._obj("Apple|1")
            apple["parentReceptacles"] = []
            plate = self._obj("Plate|1")
            plate["receptacleObjectIds"] = []

    def pickup_event(self, object_id, *, look_first=True):
        plate = self._obj(object_id)
        plate["isPickedUp"] = True
        self.session._metadata["agent"]["inventoryObjects"] = [{"objectId": object_id}]
        if self.move_apple:
            apple = self._obj("Apple|1")
            apple["position"]["x"] += 0.5
        # Held-receptacle metadata may omit the child's parent relation.
        apple = self._obj("Apple|1")
        apple["parentReceptacles"] = []
        plate["receptacleObjectIds"] = []
        record = {"action": "PickupObject", "kwargs": {"objectId": object_id},
                  "lastActionSuccess": True, "errorMessage": ""}
        self.session.records.append(record)
        event = SimpleNamespace(metadata=copy.deepcopy(self.session._metadata))
        result = StepResult(event, copy.deepcopy(self.session._metadata), record)
        self.session.controller.last_event = event
        return result

    def settle(self, steps=5):
        return []


def make_builder(variant, *, move_apple=True, lose_support_on_freeze=False):
    session = FakeSession()
    builder = CaseBuilder.__new__(CaseBuilder)
    builder.session = session
    builder.ops = FakeOps(session, move_apple=move_apple,
                          lose_support_on_freeze=lose_support_on_freeze)
    builder.pair_id, builder.variant = "P20", variant
    builder.stage = Path("/tmp/p20_carrying_test")
    builder.spec = {}
    builder.config = {"position_tolerance_m": 0.02, "settle_steps": 1}
    builder.seed = 17
    builder.roles = {}
    builder.frames = []
    builder.checks = []
    builder.history = []
    builder.direct = {}
    builder.indirect = {}
    builder.questions = []
    builder.selected = []
    builder.contrast = []
    builder.before = None
    builder.after = None
    builder.event_result = None
    builder.event_index = None
    builder.rules = []
    builder.excluded_query_fields = set()
    return builder


class CarryingBuilderTests(unittest.TestCase):
    def test_apple_is_carried_by_displacement_even_when_post_parent_is_empty(self):
        builder = make_builder("A")

        builder.carrying()

        plate_id = builder.roles["Plate_1"]
        apple_id = builder.roles["Apple_1"]
        before_apple = next(o for o in builder.before["objects"] if o["objectId"] == apple_id)
        after_apple = next(o for o in builder.after["objects"] if o["objectId"] == apple_id)
        self.assertIn(plate_id, before_apple["parentReceptacles"])
        self.assertGreater(
            (after_apple["position"]["x"] - before_apple["position"]["x"]),
            builder.config["position_tolerance_m"],
        )
        self.assertEqual(after_apple["parentReceptacles"], [])
        self.assertIn(("Apple_1", "parentReceptacles"), builder.excluded_query_fields)
        audit = next(c for c in builder.checks if c["name"] == "post_pickup_apple_parents_audit_only")
        self.assertTrue(audit["passed"])
        self.assertFalse(audit["detail"]["used_as_support_gold"])

    def test_variant_a_fails_if_apple_does_not_move(self):
        builder = make_builder("A", move_apple=False)

        with self.assertRaisesRegex(ConstructionError, "apple_carrying_boundary"):
            builder.carrying()

    def test_support_must_still_exist_in_frozen_before_snapshot(self):
        builder = make_builder("A", lose_support_on_freeze=True)

        with self.assertRaisesRegex(ConstructionError, "apple_support_at_frozen_before"):
            builder.carrying()
        failed_check = next(c for c in builder.checks if c["name"] == "apple_support_at_frozen_before")
        self.assertFalse(failed_check["passed"])
        self.assertFalse(any(record["action"] == "PickupObject" for record in builder.session.records))


if __name__ == "__main__":
    unittest.main()
