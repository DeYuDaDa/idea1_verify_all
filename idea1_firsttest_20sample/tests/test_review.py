import json
import tempfile
import unittest
from pathlib import Path

import review
import validate


class ReviewTests(unittest.TestCase):
    def _candidate(self, root):
        media = root / "data" / "media"
        media.mkdir(parents=True, exist_ok=True)
        (media / "frame.png").write_bytes(b"frame-one")
        for sample_id in ("M01_A", "M01_B"):
            public = root / "data" / "input" / f"{sample_id}.json"
            hidden = root / "hidden_gold" / f"{sample_id}.json"
            public.parent.mkdir(parents=True, exist_ok=True)
            hidden.parent.mkdir(parents=True, exist_ok=True)
            public.write_text(json.dumps({"sample_id": sample_id, "model_input": {"frames": [{"path": "data/media/frame.png"}]}}), encoding="utf-8")
            hidden.write_text(json.dumps({"sample_id": sample_id, "extra": {"initial_control_audited": False}}), encoding="utf-8")

    def test_template_defaults_to_unapproved_and_apply_writes_separate_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            form_path = Path(tmp) / "review_form.json"
            self._candidate(root)
            form = review.create_template(root, form_path)
            self.assertTrue(all(all(value is False for value in entry["checks"].values()) for entry in form["samples"]))
            self.assertTrue(all("approved" not in entry for entry in form["samples"]))
            with self.assertRaises(ValueError):
                review.apply_review(root, form_path, "Reviewer")
            for entry in form["samples"]:
                entry["checks"] = {"visual_evidence_confirmed": True, "initial_controls_confirmed": True, "knowledge_protocol_confirmed": True}
            form_path.write_text(json.dumps(form), encoding="utf-8")
            result = review.apply_review(root, form_path, "Reviewer")
            self.assertEqual(result, root / "review_records.json")
            self.assertTrue((root / "review_records.json").is_file())
            self.assertEqual(json.loads((root / "hidden_gold" / "M01_A.json").read_text(encoding="utf-8"))["extra"]["initial_control_audited"], False)
            records = json.loads((root / "review_records.json").read_text(encoding="utf-8"))
            self.assertEqual(validate._matching_review_samples(root, records), {"M01_A", "M01_B"})
            hidden_path = root / "hidden_gold" / "M01_A.json"
            hidden = json.loads(hidden_path.read_text(encoding="utf-8"))
            hidden["changed_after_review"] = True
            hidden_path.write_text(json.dumps(hidden), encoding="utf-8")
            self.assertEqual(validate._matching_review_samples(root, records), set())

    def test_metadata_flag_alone_is_not_a_review_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            self._candidate(root)
            hidden_path = root / "hidden_gold" / "M01_A.json"
            hidden = json.loads(hidden_path.read_text(encoding="utf-8"))
            hidden["extra"]["initial_control_audited"] = True
            hidden_path.write_text(json.dumps(hidden), encoding="utf-8")
            self.assertEqual(validate._matching_review_samples(root, None), set())

    def test_stale_record_fingerprint_rejects_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            form_path = Path(tmp) / "review_form.json"
            self._candidate(root)
            form = review.create_template(root, form_path)
            for entry in form["samples"]:
                entry["checks"] = {"visual_evidence_confirmed": True, "initial_controls_confirmed": True, "knowledge_protocol_confirmed": True}
            form_path.write_text(json.dumps(form), encoding="utf-8")
            hidden_path = root / "hidden_gold" / "M01_A.json"
            hidden = json.loads(hidden_path.read_text(encoding="utf-8"))
            hidden["mutated"] = True
            hidden_path.write_text(json.dumps(hidden), encoding="utf-8")
            with self.assertRaises(ValueError):
                review.apply_review(root, form_path, "Reviewer")

    def test_image_bytes_are_part_of_the_review_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            self._candidate(root)
            before = review.sample_fingerprint(root, "M01_A")
            (root / "data" / "media" / "frame.png").write_bytes(b"frame-two")
            after = review.sample_fingerprint(root, "M01_A")
            self.assertNotEqual(before, after)

    def test_existing_review_form_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            form_path = Path(tmp) / "review_form.json"
            self._candidate(root)
            form_path.write_text("keep me", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                review.create_template(root, form_path)
            self.assertEqual(form_path.read_text(encoding="utf-8"), "keep me")


if __name__ == "__main__":
    unittest.main()
