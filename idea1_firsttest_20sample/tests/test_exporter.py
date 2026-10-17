import json
import tempfile
import unittest
from pathlib import Path

import exporter


class ExporterTests(unittest.TestCase):
    def test_metadata_diff_is_gold_and_capability_absence_is_not_assessed(self):
        facts = exporter._build_facts(
            {"objects": [{"objectId": "Bowl", "isDirty": True, "parentReceptacles": ["Z", "A"]}]},
            {"objects": [{"objectId": "Bowl", "isDirty": True, "parentReceptacles": ["A", "Z"]}]},
            ["Bowl"], "ToggleObjectOn", set(), set(), {},
        )
        dirty = next(f for f in facts if f["predicate"] == "isDirty")
        receptacles = next(f for f in facts if f["predicate"] == "parentReceptacles")
        cooked = next(f for f in facts if f["predicate"] == "isCooked")
        self.assertFalse(dirty["changed"])
        self.assertEqual(dirty["before"], {"state": "value", "value": True})
        self.assertEqual(receptacles["comparison_status"], "equal")
        self.assertEqual(cooked["before"]["state"], "not_applicable")
        self.assertFalse(cooked["assessed"])

    def test_position_uses_one_centimeter_epsilon_and_keeps_raw_values(self):
        facts = exporter._build_facts(
            {"objects": [{"objectId": "Cup", "position": {"x": 0, "y": 0, "z": 0}}]},
            {"objects": [{"objectId": "Cup", "position": {"x": 0.005, "y": 0, "z": 0}}]},
            ["Cup"], "PutObject", set(), set(), {},
        )
        position = next(f for f in facts if f["predicate"] == "position")
        self.assertFalse(position["changed"])
        self.assertEqual(position["after"]["value"]["x"], 0.005)

    def test_event_kwargs_and_explicit_evaluated_action_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = exporter.export_case(
                tmp, "M01", "A", {"questions": ["What changed?"]},
                {"objects": [{"objectId": "Microwave_1", "isToggled": False}]},
                {"objects": [{"objectId": "Microwave_1", "isToggled": True}]},
                ["Microwave_1"], ["Microwave_1"],
                [{"action": "Pass", "lastActionSuccess": True, "kwargs": {"objectId": "wrong"}}],
                {"evaluated_action": {"action": "ToggleObjectOn", "kwargs": {"objectId": "Microwave_1"}, "lastActionSuccess": True}},
            )
            hidden = json.loads(Path(result["hidden_gold_path"]).read_text(encoding="utf-8"))
            self.assertEqual(hidden["action_name"], "ToggleObjectOn")
            self.assertIn("Microwave_1", hidden["action_targets"])

    def test_public_gold_key_and_hidden_path_rejected_but_question_text_allowed(self):
        self.assertEqual(exporter._scan_for_public_leaks({"question": "What is the gold color?"}), [])
        self.assertTrue(exporter._scan_for_public_leaks({"sub_object": {"ground_truth": "x"}}))
        self.assertEqual(exporter._scan_for_public_leaks({"frames": [{"path": "data/media/a.png"}]}), [])

    def test_default_knowability_and_unclassified_effect(self):
        facts = exporter._build_facts(
            {"objects": [{"objectId": "X", "mass": 1}]},
            {"objects": [{"objectId": "X", "mass": 2}]},
            ["X"], "ToggleObjectOn", {"X"}, set(), {},
        )
        mass = next(f for f in facts if f["predicate"] == "mass")
        self.assertEqual(mass["knowability"], "not_assessed")
        self.assertEqual(mass["directness"], "unclassified")
        self.assertEqual(mass["verification_status"], "not_verified_candidate")

    def test_capability_false_gates_plate_but_mapped_burner_toggle_is_retained(self):
        unassessed_facts = exporter._build_facts(
            {"objects": [{"objectId": "Cup_1", "isFilledWithLiquid": False}]},
            {"objects": [{"objectId": "Cup_1", "isFilledWithLiquid": False}]},
            ["Cup_1"], "Pass", set(), set(), {},
        )
        unassessed = next(f for f in unassessed_facts if f["predicate"] == "isFilledWithLiquid")
        self.assertEqual(unassessed["after"], {"state": "value", "value": False})
        self.assertFalse(unassessed["assessed"])

        plate_facts = exporter._build_facts(
            {"objects": [{"objectId": "Plate_1", "canFillWithLiquid": False, "isFilledWithLiquid": False}]},
            {"objects": [{"objectId": "Plate_1", "canFillWithLiquid": False, "isFilledWithLiquid": False}]},
            ["Plate_1"], "Pass", set(), set(), {},
        )
        filled = next(f for f in plate_facts if f["predicate"] == "isFilledWithLiquid")
        self.assertEqual(filled["after"]["state"], "not_applicable")

        burner_facts = exporter._build_facts(
            {"objects": [{"objectId": "StoveBurner|coords", "toggleable": False, "isToggled": False}]},
            {"objects": [{"objectId": "StoveBurner|coords", "toggleable": False, "isToggled": True}]},
            ["StoveBurner|coords"], "ToggleObjectOn", set(), set(),
            {"indirect_fields": {"StoveBurner|coords": ["isToggled"]}},
        )
        toggled = next(f for f in burner_facts if f["predicate"] == "isToggled")
        self.assertEqual(toggled["after"], {"state": "value", "value": True})
        self.assertTrue(toggled["changed"])

    def test_query_targets_use_aliases_and_change_status(self):
        facts = exporter._build_facts(
            {"objects": [{"objectId": "Potato|p", "parentReceptacles": []}]},
            {"objects": [{"objectId": "Potato|p", "parentReceptacles": ["Microwave|m"], "position": {"x": 1, "y": 0, "z": 0}}]},
            ["Potato|p"], "Pass", set(), set(), {"knowability": {"Potato|p": {"position": "knowable", "parentReceptacles": "knowable"}}},
        )
        answers = exporter._query_targets({"questions": [
            {"fact_id": "Potato|p.parentReceptacles", "predicate": "parentReceptacles"},
            {"fact_id": "Potato|p.position", "predicate": "position", "answer_mode": "change_status"},
        ]}, {"role_bindings": {"Potato_1": "Potato|p", "Microwave_1": "Microwave|m"}}, facts)
        self.assertEqual(answers[0]["expected_answer"], ["Microwave_1"])
        self.assertEqual(answers[1]["expected_answer"], "unknown")

    def test_empty_fill_liquid_none_and_empty_string_are_equivalent(self):
        facts = exporter._build_facts(
            {"objects": [{"objectId": "Mug_1", "canFillWithLiquid": True, "isFilledWithLiquid": False, "fillLiquid": None}]},
            {"objects": [{"objectId": "Mug_1", "canFillWithLiquid": True, "isFilledWithLiquid": False, "fillLiquid": ""}]},
            ["Mug_1"], "Pass", set(), set(), {},
        )
        liquid = next(f for f in facts if f["predicate"] == "fillLiquid")
        self.assertFalse(liquid["changed"])
        self.assertIsNone(liquid["after"]["value"])


if __name__ == "__main__":
    unittest.main()
