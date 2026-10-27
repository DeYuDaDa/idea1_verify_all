import copy
import unittest
from types import SimpleNamespace

from hard_scenarios import _target_event


class BoundaryContext:
    def __init__(self, fail_postcondition=False):
        self.roles = {"P": "plate"}
        self.navigation_calls = []
        self.executed_phases = [{"label": "拿盘目标事件", "kind": "target"}]
        self.target_frozen = False
        self.position = 0.
        self.session = SimpleNamespace(records=[], snapshot=self.snapshot)
        self.fail_postcondition = fail_postcondition
        self.ops = SimpleNamespace(pickup_event=self.pickup, settle=self.settle)

    def snapshot(self):
        return {"objects": [{"objectId": "plate", "position": {"x": self.position, "y": 0., "z": 0.}}]}

    def obj(self, role):
        return copy.deepcopy(self.snapshot()["objects"][0])

    def phase(self, label, public=True, kind="history"):
        self.executed_phases.append({"label": label, "kind": kind})

    def navigate_to(self, object_id, purpose):
        assert not self.target_frozen
        assert self.executed_phases[-1]["kind"] == "history"
        self.navigation_calls.append((object_id, purpose))
        self.position = 10.  # A change before the event must not be scored as its effect.
        self.session.records.append({"index": 0, "action": "MoveAhead"})

    def pickup(self, object_id, look_first=False):
        assert self.target_frozen
        assert self.executed_phases[-1]["kind"] == "target"
        self.position = 10.1
        row = {"index": 1, "action": "PickupObject", "kwargs": {"objectId": object_id},
               "lastActionSuccess": True}
        self.session.records.append(row)
        if self.fail_postcondition:
            raise RuntimeError("postcondition failed after a successful receipt")
        return SimpleNamespace(record=row)

    def settle(self, steps):
        assert not self.target_frozen
        return []

    def check(self, *args):
        pass


class HardEventBoundaryTests(unittest.TestCase):
    def test_native_approach_is_outside_the_measured_target_boundary(self):
        ctx = BoundaryContext()
        row = _target_event(ctx, "PickupObject", "P")
        self.assertEqual(ctx.before_target["objects"][0]["position"]["x"], 10.)
        self.assertEqual(ctx.after_target["objects"][0]["position"]["x"], 10.1)
        self.assertEqual(row["event_index"], 1)
        self.assertTrue(row["success"])
        self.assertFalse(ctx.target_frozen)

    def test_native_success_is_not_confused_with_a_failed_postcondition(self):
        ctx = BoundaryContext(fail_postcondition=True)
        row = _target_event(ctx, "PickupObject", "P")
        self.assertTrue(row["native_action_success"])
        self.assertFalse(row["success"])
        self.assertFalse(row["postcondition_verified"])
        self.assertEqual(row["record"]["kwargs"]["objectId"], "plate")
        self.assertFalse(ctx.target_frozen)


if __name__ == "__main__":
    unittest.main()
