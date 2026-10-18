import json
import tempfile
import unittest
from pathlib import Path

import offline_run_qwen as runner


class OfflineRunnerTests(unittest.TestCase):
    def test_prompt_allowlist_anonymizes_questions_and_omits_paths_and_sample_ids(self):
        model_input = {
            "protocol": "must not be shown",
            "protocol_note": "Public protocol note",
            "objects": [{"alias": "Apple_1", "object_type": "Apple", "objectId": "Apple|secret"}],
            "history": [{"stage": "before", "facts": [
                {"subject": "Apple_1", "predicate": "parentReceptacles", "value": ["Plate_1"],
                 "fact_id": "Apple|secret.parentReceptacles"},
            ]}],
            "rules": ["Only objects supported by a carried plate move with it."],
            "event": {"action": "PickupObject", "subject": "Plate_1", "success": True,
                      "sample_id": "P20_A", "objectId": "Plate|secret"},
            "frames": [{"stage": "before_event", "path": "data/media/private-name.png"}],
            "questions": [{"fact_id": "Apple|secret.position", "subject": "Apple_1",
                           "predicate": "position", "question": "Did Apple move?",
                           "answer_mode": "change_status"}],
        }

        prompt, qid_map = runner.build_prompt(model_input)

        self.assertEqual(qid_map, {"q001": "Apple|secret.position"})
        self.assertIn('"id": "q001"', prompt)
        self.assertIn('"stage": "before_event"', prompt)
        for secret in ("P20_A", "Apple|secret", "Plate|secret", "private-name.png",
                       "must not be shown", "sample_id", "objectId", "fact_id"):
            self.assertNotIn(secret, prompt)

    def test_parser_reports_exact_json_status_and_missing_or_unexpected_ids(self):
        full = runner.parse_structured_output('{"q001":"changed","q002":["Plate_1"]}',
                                              ["q001", "q002"])
        self.assertEqual(full["format_status"], "ok")
        self.assertEqual(full["answers"]["q001"], "changed")

        partial = runner.parse_structured_output('{"q001":"preserved","extra":"x"}',
                                                 ["q001", "q002"])
        self.assertEqual(partial["format_status"], "partial")
        self.assertEqual(partial["missing_question_ids"], ["q002"])
        self.assertEqual(partial["unexpected_question_ids"], ["extra"])

        malformed = runner.parse_structured_output('Here is the answer: {"q001":"changed"}', ["q001"])
        self.assertEqual(malformed["format_status"], "json_parse_error")
        self.assertEqual(malformed["missing_question_ids"], ["q001"])

    def test_public_loader_hashes_only_input_and_confined_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "data" / "input"
            media_dir = root / "data" / "media"
            input_dir.mkdir(parents=True)
            media_dir.mkdir(parents=True)
            (root / "hidden_gold").mkdir()
            (root / "hidden_gold" / "M01_A.json").write_text("DO NOT READ", encoding="utf-8")
            (media_dir / "frame.png").write_bytes(b"fake png bytes for hashing")
            public = {
                "sample_id": "opaque_001",
                "pair_id": "M01",
                "variant": "A",
                "model_input": {
                    "protocol_note": "Use public history and event.",
                    "objects": [{"alias": "Cup_1", "object_type": "Cup"}],
                    "history": [], "rules": ["A cup remains where it is."],
                    "event": {"action": "Pass", "success": True},
                    "frames": [{"stage": "before_event", "path": "data/media/frame.png"}],
                    "questions": [{"fact_id": "Cup|1.position", "subject": "Cup_1",
                                   "predicate": "position", "question": "Did it move?",
                                   "answer_mode": "change_status"}],
                },
            }
            (input_dir / "opaque_001.json").write_text(json.dumps(public), encoding="utf-8")

            loaded = runner.load_public_samples(root, limit=1)

            self.assertEqual([sample["sample_id"] for sample in loaded], ["opaque_001"])
            self.assertEqual(loaded[0]["media"][0]["relative_path"], "data/media/frame.png")
            self.assertEqual(len(loaded[0]["source_fingerprint"]), 64)
            self.assertNotIn("hidden_gold", str(loaded[0]["source_path"]))

    def test_actual_exporter_public_record_shape_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "data" / "input"
            media_dir = root / "data" / "media"
            input_dir.mkdir(parents=True)
            media_dir.mkdir(parents=True)
            (media_dir / "frame.png").write_bytes(b"fake png bytes")
            record = {
                "sample_id": "M01_A", "pair_id": "M01", "variant": "A",
                "model_input": {
                    "protocol_note": "public", "objects": [], "history": [], "rules": [],
                    "event": {"action": "Pass"},
                    "frames": [{"stage": "before_event", "path": "data/media/frame.png"}],
                    "questions": [{"fact_id": "Apple|1.position", "subject": "Apple_1",
                                   "predicate": "position", "question": "Did it move?"}],
                },
            }
            (input_dir / "M01_A.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(runner.load_public_samples(root)[0]["sample_id"], "M01_A")

    def test_media_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "data" / "media"
            media.mkdir(parents=True)
            outside = root / "outside.png"
            outside.write_bytes(b"not allowed")
            with self.assertRaisesRegex(runner.RunnerError, "outside data/media"):
                runner._safe_media_path(root, "../outside.png", root / "data/input/x.json")

    def test_public_input_symlinks_and_unexpected_top_level_payload_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "data" / "input"
            input_dir.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text('{"sample_id":"outside","model_input":{}}', encoding="utf-8")
            try:
                (input_dir / "linked.json").symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this host")
            with self.assertRaisesRegex(runner.RunnerError, "symlinks are not allowed"):
                runner.load_public_samples(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "data" / "input"
            input_dir.mkdir(parents=True)
            (input_dir / "payload.json").write_text(
                json.dumps({"sample_id": "s1", "hidden_gold": {"answer": "leak"}, "model_input": {}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(runner.RunnerError, "Unexpected top-level keys"):
                runner.load_public_samples(root)

    def test_resume_requires_existing_prediction_hashes_to_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "predictions.jsonl"
            samples = [{"sample_id": "s1", "source_fingerprint": "a" * 64}]
            path.write_text(json.dumps({"sample_id": "s1", "source_fingerprint": "a" * 64,
                                        "status": "complete"}) + "\n", encoding="utf-8")
            self.assertEqual(runner._read_existing_predictions(path, samples), {"s1"})
            path.write_text(json.dumps({"sample_id": "s1", "source_fingerprint": "b" * 64,
                                        "status": "complete"}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(runner.RunnerError, "does not match"):
                runner._read_existing_predictions(path, samples)

    def test_partial_resume_selects_only_unfinished_samples(self):
        samples = [{"sample_id": sample_id} for sample_id in ("M01_A", "M01_B", "P20_A")]
        pending = runner.pending_samples(samples, {"M01_A", "P20_A"})
        self.assertEqual([sample["sample_id"] for sample in pending], ["M01_B"])


if __name__ == "__main__":
    unittest.main()
