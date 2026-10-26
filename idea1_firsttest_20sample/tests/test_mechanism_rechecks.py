"""Pure checks for false mechanism labels; these fixtures never run Unity."""
import copy
import unittest

from mechanism_probe import registry
from mechanism_rechecks import (RELATIONS, comparison_summary, evaluate_motion,
                                evaluate_thermal, expected_follow)


def body(x=0, z=0, oid="a"):
    return {"objectId": oid, "position": {"x": x, "y": 0, "z": z}, "parentReceptacles": []}


class RecheckTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
