import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hard_export import export_case, request_text, sha_file
from hard_generate import _quarantine_partial_exports, plan, target_capture_diagnostics
from hard_scenarios import cases
from offline_run_qwen import RunnerError, _check_public_model_input


class TraceFixture:
    def __init__(self, directory):
        self.directory = directory
        (directory / "frames").mkdir(parents=True)
        (directory / "frames" / "one.png").write_bytes(b"public-image-fixture")

    def model_frames(self):
        return [{"path": "frames/one.png", "stage": "历史片段01", "view_id": "fixed_0",
                 "run_length": 4, "duplicate_count": 3, "start_step": 1, "end_step": 4,
                 "capture_group_index": 1}]


def fixture_context():
    old = {"objects": [{"objectId": "private-native-m", "objectType": "Microwave",
                        "isToggled": False, "toggleable": True},
                       {"objectId": "private-native-z", "objectType": "Potato", "cookable": True,
                        "isCooked": True, "temperature": "RoomTemp"}]}
    after = json.loads(json.dumps(old))
    after["objects"][0]["isToggled"] = True
    # Deliberately disagree with the design's cooked result. Labels must follow
    # observed metadata rather than the name H05-1 or a table in the plan.
    after["objects"][1]["isCooked"] = False
    return SimpleNamespace(group_id="H05", roles={"Microwave": "private-native-m", "Z": "private-native-z"},
        initial_metadata=old, before_target=old, after_target=after, waypoints={},
        target_event={"action": "ToggleObjectOn", "subject": "Microwave", "success": True},
        public_declarations=["完整的初态说明不能丢失"],
        initial_identity_regions=[{"alias": a, "view_id": "fixed_0", "pixel_bbox": [0, 0, 1, 1]}
                                  for a in ("Microwave", "Z")],
        questions=[{"subject": "Z", "predicate": "isCooked", "answer_mode": "boolean",
                    "question": "土豆现在熟了吗？"}])


class HardPipelineTests(unittest.TestCase):
    def test_all_twenty_candidates_are_listed_without_claiming_a_live_pass(self):
        result = plan(cases())
        self.assertEqual(len(result["cases"]), 20)
        self.assertFalse(result["simulator_started"])
        self.assertFalse(result["model_called"])
        self.assertTrue(all(c["scene"] == "FloorPlan2" for c in result["cases"] if c["group_id"] in {"H02", "H03"}))
        self.assertTrue(next(c for c in result["cases"] if c["case_id"] == "H04-4")["conditional_reparenting_unverified"])

    def test_export_freezes_all_fields_and_keeps_actual_gold_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace = TraceFixture(root / "audit_traces" / "H05-1")
            ctx = fixture_context()
            case = SimpleNamespace(case_id="H05-1")
            ids = export_case(ctx, trace, root, case)
            self.assertEqual(ids, ["H05-1_V", "H05-1_S"])
            for mode in ("V", "S"):
                path = root / "data/input" / f"H05-1_{mode}.json"
                record = json.loads(path.read_text(encoding="utf-8"))
                request = json.loads((root / "prepared_requests" / path.name).read_text(encoding="utf-8"))
                self.assertEqual(request["model_input_sha256"], sha_file(path))
                self.assertEqual(request["model_input"], record["model_input"])
                self.assertEqual(request["status"], "prepared_not_sent")
                self.assertEqual(request["request_text"].split("\n\n", 1)[1],
                                 json.dumps(record["model_input"], ensure_ascii=False, indent=2))
                self.assertNotIn("private-native-", json.dumps(record))
                self.assertNotIn("expected_answer", json.dumps(record))
                self.assertNotIn("after_target", json.dumps(record))
                gold = json.loads((root / "hidden_gold" / path.name).read_text(encoding="utf-8"))
                self.assertIs(gold["query_targets"][0]["expected_answer"], False)
                if mode == "V":
                    self.assertEqual(len(record["model_input"]["frames"]), 1)
                    self.assertEqual(record["model_input"]["frames"][0]["duplicate_count"], 3)
                    self.assertIn("完整的初态说明不能丢失", request["request_text"])
                else:
                    self.assertEqual(record["model_input"]["frames"], [])
                    self.assertEqual(record["model_input"]["history"], [])
                    state = record["model_input"]["state_before_event"]
                    self.assertTrue(any(f["subject"] == "Z" and f["predicate"] == "isCooked" and f["value"] is True
                                        for f in state))

    def test_request_serializes_future_fields_instead_of_a_legacy_allowlist(self):
        value = {"new_history_field": {"important": "must remain"}, "rules": ["rule"], "event": {"extra": True}}
        self.assertEqual(json.loads(request_text(value).split("\n\n", 1)[1]), value)

    def test_missing_native_measurement_is_not_published_as_a_gold_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace = TraceFixture(root / "audit_traces" / "H05-1")
            ctx = fixture_context()
            ctx.after_target["objects"][1].pop("isCooked")
            with self.assertRaisesRegex(RuntimeError, "Native truth unavailable"):
                export_case(ctx, trace, root, SimpleNamespace(case_id="H05-1"))
            self.assertFalse((root / "data/input/H05-1_V.json").exists())

    def test_failed_export_fragments_do_not_look_like_another_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "data/input/H05-1_V.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}", encoding="utf-8")
            private = root / "audit_traces/H05-1"
            _quarantine_partial_exports(root, "H05-1", private)
            self.assertFalse(path.exists())
            self.assertTrue((private / "unpublished_fragments/data_input/H05-1_V.json").is_file())
            self.assertEqual(list(private.rglob("data/input")), [])

    def test_legacy_model_entrypoint_refuses_to_silently_drop_hard_fields(self):
        with self.assertRaisesRegex(RunnerError, "frozen prepared_requests"):
            _check_public_model_input({"protocol": "hard-selective-V/v1"}, Path("fixture.json"))

    def test_motion_identical_rgb_is_reported_without_declaring_a_camera_failure(self):
        ctx = SimpleNamespace(group_id="H02", roles={"P": "p"}, target_event={"event_index": 2},
            before_target={"objects": [{"objectId": "p", "position": {"x": 0, "y": 0, "z": 0}}]},
            after_target={"objects": [{"objectId": "p", "position": {"x": 1, "y": 0, "z": 0}}]})
        trace = SimpleNamespace(events=[{"phase_public": True, "action_index": i, "phase_kind": kind,
            "record_kind": "native", "frames": [{"view_id": "agent", "pixel_sha256": "same"}]}
            for i, kind in ((1, "history"), (2, "target"), (3, "observation"))])
        result = target_capture_diagnostics(ctx, trace)
        self.assertTrue(result["motion_without_rgb_change_requires_review"])
        self.assertNotIn("camera_failure", result)


if __name__ == "__main__":
    unittest.main()
