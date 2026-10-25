"""Cross-module completeness and epistemic-boundary checks; no live simulator."""
import json
import unittest
from pathlib import Path

from mechanism_probe import FACTS, FAMILY_SCENES, registry, summarise


class RegistryTests(unittest.TestCase):
    def test_capture_failure_is_reported_separately_from_completed_probe_loop(self):
        case = registry()[0]
        row = {"fact_id": case.fact_id, "case_id": case.case_id, "scene": "FloorPlan1",
               "status": "inconclusive", "visual_capture_status": "capture_incomplete",
               "native_measurement_valid": False}
        report = summarise([row], [case], {})
        self.assertEqual(report["capture_failure_attempts"], 1)
        self.assertEqual(report["invalid_native_measurements"], 1)
        self.assertTrue(report["has_capture_or_measurement_failure"])
        self.assertEqual(report["status_counts"], {"inconclusive": 1})

    def test_every_registered_experiment_has_a_real_scene_family(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())
        cases = registry()
        self.assertEqual({c.fact_id for c in cases}, set(FACTS))
        for case in cases:
            family = FAMILY_SCENES.get(case.family, case.family)
            self.assertIn(family, config["scene_candidates"], case.case_id)

    def test_a_positive_observation_does_not_certify_a_global_fact_or_hard_group(self):
        case = registry()[0]
        report = summarise([{"fact_id": case.fact_id, "case_id": case.case_id,
                             "scene": "FloorPlan1", "status": "observed_supported"}], [case], {})
        self.assertFalse(report["facts"][case.fact_id]["global_mechanism_confirmed"])
        self.assertFalse(report["hard_groups_automatically_approved"])
        self.assertEqual(report["visual_evidence_review"], "not_assessed")

    def test_conditional_design_references_registered_cases_without_approving_them(self):
        plan = json.loads((Path(__file__).resolve().parents[1] / "hard_group_plan.json").read_text(encoding="utf-8"))
        ids = {c.case_id for c in registry()}
        for group in plan["groups"]:
            self.assertEqual(group["status"], "conditional_unverified")
            refs = plan["current_probe_refs"][group["group_id"]]
            self.assertFalse(set(refs["case_ids"]) - ids, group["group_id"])
            self.assertTrue(refs["remaining_conditions"], group["group_id"])


if __name__ == "__main__":
    unittest.main()
