import unittest

import validate


class ValidateTests(unittest.TestCase):
    def test_position_selected_actual_flip_must_exist(self):
        def sample(changed, value):
            return {
                "action_name": "ToggleObjectOn", "action_targets": ["Microwave_1"],
                "evaluated_action": {"action": "ToggleObjectOn", "kwargs": {"objectId": "Microwave_1"}, "lastActionSuccess": True},
                "before_metadata": {"objects": [{"objectId": "Potato", "parentReceptacles": [value]}]},
                "after_metadata": {"objects": [{"objectId": "Potato", "parentReceptacles": [value]}]},
                "extra": {"selected_pair_fact_keys": ["Potato.isCooked"], "role_bindings": {"potato": "Potato_1"}, "initial_control_audited": True,
                          "observation_audit": {"event_target_visible": True, "required_frames_present": True},
                          "scenario_checks": [{"name": "precondition", "passed": True}]},
                "actual_facts_diff": [{"subject": "Potato", "predicate": "isCooked", "changed": changed,
                                       "before": {"state": "value", "value": False}, "after": {"state": "value", "value": bool(changed)}}],
            }

        a, b = sample(False, "Microwave_1"), sample(False, "CounterTop_1")
        a["extra"]["selected_pair_fact_keys"] = b["extra"]["selected_pair_fact_keys"] = ["Potato.isCooked"]
        report = validate._pair_result({"pair_id": "M01", "strict_minimal_pair": True}, a, b)
        self.assertEqual(report["actual_flip_status"], "fail")
        self.assertIn("selected_mechanism_target_did_not_flip", report["failures"])

    def test_m03_requires_preservation_in_each_variant(self):
        base = {
            "action_name": "ToggleObjectOn", "action_targets": ["Microwave_1"],
            "evaluated_action": {"action": "ToggleObjectOn", "kwargs": {"objectId": "Microwave_1"}, "lastActionSuccess": True},
            "before_metadata": {"objects": [{"objectId": "Bowl", "isDirty": True}]},
            "after_metadata": {"objects": [{"objectId": "Bowl", "isDirty": True}]},
            "extra": {"role_bindings": {"bowl": "Bowl_1"}, "initial_control_audited": True,
                      "observation_audit": {"event_target_visible": True, "required_frames_present": True},
                      "scenario_checks": [{"name": "precondition", "passed": True}]},
            "actual_facts_diff": [{"subject": "Bowl", "predicate": "isDirty", "changed": False,
                                   "before": {"state": "value", "value": True}, "after": {"state": "value", "value": True}}],
        }
        a, b = dict(base), dict(base)
        a["actual_facts_diff"] = [dict(base["actual_facts_diff"][0])]
        b["actual_facts_diff"] = [dict(base["actual_facts_diff"][0])]
        b["actual_facts_diff"][0]["before"] = {"state": "value", "value": False}
        b["actual_facts_diff"][0]["after"] = {"state": "value", "value": True}
        b["actual_facts_diff"][0]["changed"] = True
        report = validate._pair_result({"pair_id": "M03", "strict_minimal_pair": True}, a, b)
        self.assertEqual(report["preservation_status"], "fail")
        self.assertIn("M03_dirty_value_not_preserved_in_both_variants", report["failures"])

    def test_public_hidden_paths_are_rejected(self):
        self.assertTrue(validate._public_path_issues({"path": "hidden_gold/M01_A.json"}, __import__("pathlib").Path(".")))

    def test_m03_preservation_resolves_real_bowl_object_ids(self):
        def sample(dirty):
            return {
                "scene_name": "FloorPlan1", "action_name": "ToggleObjectOn", "action_targets": ["Microwave|m"],
                "evaluated_action": {"action": "ToggleObjectOn", "kwargs": {"objectId": "Microwave|m"}, "lastActionSuccess": True},
                "before_metadata": {"objects": [{"objectId": "Bowl|x=1", "objectType": "Bowl", "isDirty": dirty}]},
                "after_metadata": {"objects": [{"objectId": "Bowl|x=1", "objectType": "Bowl", "isDirty": dirty}]},
                "extra": {"role_bindings": {"Bowl_1": "Bowl|x=1"}, "observation_audit": {"event_target_visible": True, "required_frames_present": True},
                          "scenario_checks": [{"passed": True}]},
                "_public_model_input": {"questions": [{"question": "is it dirty?"}]},
                "actual_facts_diff": [{"fact_id": "Bowl|x=1.isDirty", "subject": "Bowl|x=1", "predicate": "isDirty", "changed": False,
                                       "before": {"state": "value", "value": dirty}, "after": {"state": "value", "value": dirty}}],
            }
        report = validate._pair_result({"pair_id": "M03", "strict_minimal_pair": True}, sample(True), sample(False))
        self.assertEqual(report["preservation_status"], "pass")
        self.assertNotIn("M03_dirty_value_not_preserved_in_both_variants", report["failures"])
        b = sample(False)
        b["scene_name"] = "FloorPlan2"
        mismatched = validate._pair_result({"pair_id": "M03", "strict_minimal_pair": True}, sample(True), b)
        self.assertEqual(mismatched["scene_role_status"], "fail")
        self.assertIn("scene_or_role_bindings_mismatch", mismatched["failures"])

    def test_evaluated_failure_is_not_masked_by_later_pass_log(self):
        hidden = {
            "evaluated_action": {"action": "ToggleObjectOn", "lastActionSuccess": False},
            "action_log": [{"action": "ToggleObjectOn", "lastActionSuccess": False}, {"action": "Pass", "lastActionSuccess": True}],
        }
        self.assertIs(validate._action_success(hidden), False)


if __name__ == "__main__":
    unittest.main()
