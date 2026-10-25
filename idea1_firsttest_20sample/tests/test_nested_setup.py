"""Contracts for bounded F10 setup planning; no simulator is started."""
import copy
import unittest
from types import SimpleNamespace

from nested_setup import NestedPlacementFailure, _place_nested, establish_nested


def item(oid, kind, *, pickupable=False, receptacle=False, x=0.2, z=0.2):
    return {"objectId": oid, "objectType": kind, "pickupable": pickupable,
            "receptacle": receptacle, "parentReceptacles": [],
            "receptacleObjectIds": [], "axisAlignedBoundingBox":
                {"size": {"x": x, "y": 0.1, "z": z}}}


class FakeOps:
    def __init__(self, ctx):
        self.ctx = ctx
        self.fail_point_for = {"inner_a"}
        self.fail_put_for = {"inner_a"}
        self.settles = 0

    def place_initial(self, child, parent):
        self.ctx.calls.append((child, parent))
        if child in self.fail_point_for:
            raise RuntimeError("native placement collision")
        self._relate(child, parent)
        return []

    def _relate(self, child, parent):
        objects = self.ctx.session.metadata["objects"]
        c = next(o for o in objects if o["objectId"] == child)
        p = next(o for o in objects if o["objectId"] == parent)
        c["parentReceptacles"] = [parent]
        p["receptacleObjectIds"] = [child]

    def pickup_event(self, child, look_first=False):
        self.ctx.session.held = child
        return SimpleNamespace(record={"action": "PickupObject", "objectId": child, "lastActionSuccess": True})

    def put_event(self, child, parent):
        if child in self.fail_put_for:
            raise RuntimeError("native PutObject destination constraint")
        self._relate(child, parent)
        self.ctx.session.held = None
        return SimpleNamespace(record={"action": "PutObject", "objectId": parent, "lastActionSuccess": True})

    def settle(self, steps):
        self.settles += 1
        return []


class FakeContext:
    def __init__(self):
        self.roles = {}
        self.checks = []
        self.calls = []
        self.session = SimpleNamespace(scene="FloorPlan1", records=[], metadata={"objects": [
            item("support", "CounterTop", receptacle=True, x=1, z=1),
            item("outer_a", "Plate", pickupable=True, receptacle=True),
            item("outer_b", "Plate", pickupable=True, receptacle=True),
            item("inner_a", "Bowl", pickupable=True, receptacle=True),
            item("inner_b", "Bowl", pickupable=True, receptacle=True),
            item("content_a", "Apple", pickupable=True, x=0.05, z=0.05),
            item("content_b", "Apple", pickupable=True, x=0.05, z=0.05),
        ]})
        self._baseline = copy.deepcopy(self.session.metadata)
        self.session.snapshot = self.session_snapshot
        self.session.reset = self.reset
        self.session.inventory = lambda: ([{"objectId": self.session.held}]
                                          if getattr(self.session, "held", None) else [])
        self.ops = FakeOps(self)

    def bind(self, alias, oid):
        self.roles[alias] = oid

    def obj(self, alias):
        oid = self.roles.get(alias, alias)
        return copy.deepcopy(next(o for o in self.session.metadata["objects"] if o["objectId"] == oid))

    def select(self, alias, kind, capability=None, exclude=()):
        self.bind(alias, "support")
        return "support"

    def session_snapshot(self):
        return copy.deepcopy(self.session.metadata)

    def reset(self, scene):
        self.session.scene = scene
        self.session.metadata = copy.deepcopy(self._baseline)
        self.session.records = []
        self.session.held = None
        # Exercise the helper contract even when a reset clears role bindings.
        self.roles.clear()

    def move_setup(self, child, parent):
        return self.ops.place_initial(self.roles.get(child, child), self.roles.get(parent, parent))

    def check(self, name, passed, detail=None):
        self.checks.append((name, passed, detail))

    def capture(self, label, image=True):
        self.session.records = []


class NestedSetupTests(unittest.TestCase):
    def test_outer_to_inner_order_and_plan_include_alias_types(self):
        ctx = FakeContext()
        # No failure in this contract; keep the first candidate valid.
        ctx.ops.fail_point_for.clear()
        ctx.ops.fail_put_for.clear()
        plan = establish_nested(ctx, scene="FloorPlan1", roles={"support": "support"},
            candidates={"outer": (("Plate",), ("pickupable", "receptacle")),
                        "inner": (("Bowl",), ("pickupable", "receptacle")),
                        "content": (("Apple",), ("pickupable",))},
            edges=(("outer", "support"), ("inner", "outer"), ("content", "inner")))
        self.assertEqual(ctx.calls, [("outer_a", "support"),
                                     ("inner_a", "outer_a"),
                                     ("content_a", "inner_a")])
        self.assertEqual(plan["placement_order"],
                         ["outer->support", "inner->outer", "content->inner"])
        self.assertEqual(plan["selected_roles"]["inner"]["objectType"], "Bowl")
        self.assertEqual(ctx.roles["support"], "support")
        self.assertEqual(plan["selected_roles"]["support"]["objectType"], "CounterTop")

    def test_collision_is_recorded_and_search_continues_with_reset(self):
        ctx = FakeContext()
        # Both point placement and native PutObject fail for the first Bowl;
        # a subsequent real Bowl succeeds after the failed trials are reset.
        reset_supports = []
        plan = establish_nested(ctx, scene="FloorPlan1", roles={"support": "support"},
            candidates={"outer": (("Plate",), ("pickupable", "receptacle")),
                        "inner": (("Bowl",), ("pickupable", "receptacle")),
                        "content": (("Apple",), ("pickupable",))},
            edges=(("outer", "support"), ("inner", "outer"), ("content", "inner")),
            max_trials=12,
            after_reset=lambda current: reset_supports.append(current.roles["support"]))
        self.assertGreaterEqual(len(plan["attempts"]), 2)
        first_inner = plan["attempts"][0]["placements"][1]
        self.assertIn("native placement collision", first_inner["paths"][0]["error"])
        self.assertIn("native PutObject destination constraint", first_inner["fallback"]["error"])
        self.assertEqual(ctx.roles["inner"], "inner_b")
        self.assertTrue(reset_supports)
        self.assertTrue(all(oid == "support" for oid in reset_supports))
        self.assertEqual(ctx.roles["support"], "support")
        self.assertTrue(all(row["relation_verified_both_directions"]
                            for row in plan["attempts"][-1]["post_settle_relations"]))

    def test_fixture_without_native_put_ops_keeps_point_error_and_marks_fallback_unavailable(self):
        ctx = FakeContext()
        ctx.bind("inner", "inner_a")
        ctx.bind("outer", "outer_a")
        ctx.ops.pickup_event = None
        ctx.ops.put_event = None
        with self.assertRaises(NestedPlacementFailure) as raised:
            _place_nested(ctx, "inner", "outer")
        self.assertIn("native placement collision", str(raised.exception))
        self.assertEqual(raised.exception.attempt["fallback"]["status"], "unavailable")
        self.assertEqual(raised.exception.attempt["paths"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
