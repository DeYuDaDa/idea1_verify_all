"""Pure checks for false mechanism labels; these fixtures never run Unity."""
import copy
import unittest
from types import SimpleNamespace

from mechanism_probe import registry
from mechanism_rechecks import (RELATIONS, comparison_summary, evaluate_motion,
                                evaluate_thermal, expected_follow, transfer_bundle_external)
from mechanism_probe_common import ProbeUnavailable


def body(x=0, z=0, oid="a"):
    return {"objectId": oid, "position": {"x": x, "y": 0, "z": z}, "parentReceptacles": []}


class RecheckTests(unittest.TestCase):
    def test_bundle_put_retries_another_native_surface_without_repicking_or_teleporting(self):
        ctx = BundleContext()
        transfer_bundle_external(ctx)
        puts = [r for r in ctx.session.records if r["action"] == "PutObject"]
        self.assertEqual([r["kwargs"]["objectId"] for r in puts], ["bad", "bad", "good"])
        self.assertEqual(ctx.pickups, 1)
        self.assertEqual(ctx.roles["external"], "good")
        self.assertTrue(ctx.checks[-1]["passed"])

    def test_failed_bundle_put_losing_inventory_stops_before_retry(self):
        ctx = BundleContext(lose_inventory=True)
        with self.assertRaisesRegex(ProbeUnavailable, "lost held bowl"):
            transfer_bundle_external(ctx)
        self.assertEqual(sum(r["action"] == "PutObject" for r in ctx.session.records), 1)

    def test_suite_does_not_expand_original_45_or_omit_any_recheck_arm(self):
        self.assertEqual(len(registry()), 45)
        self.assertEqual(len(registry("rechecks")), 12)
        ids = [c.case_id for c in registry("rechecks")]
        self.assertEqual(len(set(ids)), 12)
        self.assertEqual(sum(k.startswith("R1_") for k in ids), 8)
        self.assertEqual(sum(k.startswith("R2_") for k in ids), 4)

    def test_four_relation_patterns_and_no_pickup_are_distinguished(self):
        before = {r: body(oid=r) for r in ("outer", "inner", "content")}
        for configuration in RELATIONS:
            expected = expected_follow(configuration)
            sample = {r: body(1 if expected[r] else 0, oid=r) for r in before}
            self.assertTrue(evaluate_motion(before, [sample], configuration, True)["passed"])
            self.assertTrue(evaluate_motion(before, [before], configuration, False)["passed"])
            self.assertFalse(evaluate_motion(before, [sample], configuration, False)["passed"])

    def test_equal_distance_in_wrong_direction_does_not_count_as_following(self):
        before = {r: body() for r in ("outer", "inner", "content")}
        sample = {"outer": body(1), "inner": body(z=1), "content": body(1)}
        self.assertFalse(evaluate_motion(before, [sample], "intact", True)["passed"])

    def test_missing_position_and_stationary_outer_cannot_pass(self):
        before = {r: body() for r in ("outer", "inner", "content")}
        self.assertFalse(evaluate_motion(before, [before], "intact", True)["passed"])
        invalid = copy.deepcopy(before)
        invalid["content"] = {}
        self.assertFalse(evaluate_motion(before, [invalid], "intact", False)["passed"])

    def test_all_four_thermal_outcomes_keep_change_separate_from_retention(self):
        for cooked in (False, True):
            for inside in (False, True):
                before = {"temperature": "RoomTemp", "isCooked": cooked}
                after = {"temperature": "Hot" if inside else "RoomTemp", "isCooked": True if inside else cooked}
                result = evaluate_thermal(before, [after], cooked, inside)
                self.assertEqual(result["status"], "observed_supported")
                self.assertEqual(result["cooked_value_changed"], inside and not cooked)

    def test_outside_heating_and_lost_cooked_fact_are_visible_counterexamples(self):
        result = evaluate_thermal({"temperature": "RoomTemp", "isCooked": True},
                                  [{"temperature": "Hot", "isCooked": False}], True, False)
        self.assertEqual(result["status"], "observed_counterexample")
        self.assertFalse(result["temperature_matches"])
        self.assertFalse(result["cooked_matches"])

    def test_no_inside_exposure_or_unknown_state_stays_inconclusive(self):
        before = {"temperature": "RoomTemp", "isCooked": False}
        self.assertEqual(evaluate_thermal(before, [before], False, True)["status"], "inconclusive")
        self.assertEqual(evaluate_thermal(before, [{}], False, False)["status"], "inconclusive")

    def test_incomplete_and_unmatched_controls_do_not_certify_r1(self):
        self.assertFalse(comparison_summary([])["groups"]["R1"]["whole_pattern_supported"])
        rows = []
        for configuration in RELATIONS:
            for arm in ("pickup", "control"):
                baseline = {r: body(0 if arm == "pickup" else 1, oid=r) for r in ("outer", "inner", "content")}
                rows.append({"case_id": f"R1_{configuration}_{arm}", "status": "observed_supported",
                             "checks": [{"name": "r1_motion_pattern", "detail": {"baseline": baseline}}]})
        result = comparison_summary(rows)["groups"]["R1"]
        self.assertTrue(result["all_attempted"])
        self.assertFalse(result["whole_pattern_supported"])


class BundleContext:
    """Injected native responses only; not a simulator reproduction."""
    def __init__(self, lose_inventory=False):
        self.roles = {"support": "support", "outer": "plate", "inner": "bowl", "content": "apple"}
        self.objects = {k: {**body(x, oid=k), "objectType": "CounterTop", "receptacle": True}
                        for k, x in (("support", 0), ("bad", 10), ("good", 5))}
        self.objects.update({k: {**body(oid=k), "objectType": k} for k in ("plate", "bowl", "apple")})
        self.objects["bowl"]["receptacleObjectIds"] = ["apple"]
        self.held, self.pickups, self.checks = [], 0, []
        self.lose_inventory = lose_inventory
        self.session = SimpleNamespace(records=[], inventory=lambda: self.held,
                                       snapshot=lambda: {"objects": list(self.objects.values())})
        self.ops = SimpleNamespace(seed=17, pickup_event=self.pickup)
    def pickup(self, oid, look_first=False):
        self.pickups += 1
        self.held = [{"objectId": oid}]
    def obj(self, role):
        return self.objects[self.roles.get(role, role)]
    def bind(self, role, oid):
        self.roles[role] = oid
    def require(self, condition, message):
        if not condition:
            raise ProbeUnavailable(message)
    def capture(self, *args, **kwargs):
        pass
    def check(self, name, passed, detail):
        self.checks.append({"name": name, "passed": passed, "detail": detail})
    def step(self, action, **kwargs):
        record = {"action": action, "kwargs": kwargs, "lastActionSuccess": True}
        self.session.records.append(record)
        if action == "PutObject" and kwargs["objectId"] == "bad":
            record["lastActionSuccess"] = False
            if self.lose_inventory:
                self.held = []
            raise RuntimeError("No valid positions to place object found")
        if action == "PutObject":
            self.objects["bowl"]["parentReceptacles"] = ["good"]
            self.objects["apple"]["parentReceptacles"] = ["bowl", "good"]
            self.objects["good"]["receptacleObjectIds"] = ["bowl", "apple"]
            self.held = []
        return SimpleNamespace(record=record)


if __name__ == "__main__":
    unittest.main()
