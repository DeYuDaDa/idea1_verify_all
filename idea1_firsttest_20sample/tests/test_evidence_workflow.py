"""Focused tests for evidence packet binding and fail-closed approval criteria."""
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import evidence_workflow as ew


def png_header(width=16, height=12):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class EvidenceWorkflowTests(unittest.TestCase):
    def _export(self, root):
        (root / "data" / "input").mkdir(parents=True)
        (root / "data" / "media").mkdir(parents=True)
        (root / "hidden_gold").mkdir()
        # Identical RGB bytes deliberately create an informational duplicate warning.
        frame_bytes = png_header()
        for sid in ("M01_A", "M01_B"):
            for suffix in ("before", "after"):
                image = root / "data" / "media" / f"{sid}_{suffix}.png"
                image.write_bytes(frame_bytes)
            public = {
                "sample_id": sid,
                "model_input": {
                    "protocol": "oracle_history_and_declared_rules_with_observed_event",
                    "protocol_note": "Publicly supplied history and rules.",
                    "objects": [{"alias": "Mug_1"}],
                    "frames": [
                        {"stage": "before_event", "path": f"data/media/{sid}_before.png"},
                        {"stage": "event_settled", "path": f"data/media/{sid}_after.png"},
                    ],
                    "history": [{"stage": "immediately_before_event", "facts": [
                        {"subject": "Mug_1", "predicate": "temperature", "value": "RoomTemp"}
                    ]}],
                    "rules": ["The device heats an eligible object inside it."],
                    "event": {"action": "ToggleObjectOn", "subject": "Microwave_1", "success": True},
                    "questions": [
                        {"fact_id": "Mug_1.temperature", "subject": "Mug_1", "predicate": "temperature", "question": "Temperature?", "answer_mode": "current_value"},
                        {"fact_id": "Mug_1.isCooked", "subject": "Mug_1", "predicate": "isCooked", "question": "Cooked?", "answer_mode": "current_value"},
                        {"fact_id": "Mug_1.isDirty", "subject": "Mug_1", "predicate": "isDirty", "question": "Dirty?", "answer_mode": "current_value"},
                    ],
                },
            }
            (root / "data" / "input" / f"{sid}.json").write_text(json.dumps(public), encoding="utf-8")
            (root / "hidden_gold" / f"{sid}.json").write_text(json.dumps({"sample_id": sid, "secret": "must not enter packet"}), encoding="utf-8")

    def _packet(self, root, parent):
        output = parent / "packet"
        ew.prepare(root, output)
        form_path = output / "review_form.json"
        form = json.loads(form_path.read_text(encoding="utf-8"))
        form["reviewer"] = "Reviewer A"
        for sample in form["samples"]:
            frame_paths = [f["path"] for f in sample["frames"]]
            sample["questions"][0].update({
                "mode": "direct_visual",
                "claim_notes": {"before_condition": "Mug starts at room temperature.", "event_evidence": "The activation succeeds.", "effect_or_preservation_reason": "The object state changes after activation."},
                "evidence_refs": [{"kind": "frame", "frame_path": frame_paths[0]}, {"kind": "frame", "frame_path": frame_paths[1]}],
                "state_discriminability_review": "pass", "calibration_note": "Visible state cues are specific and legible.",
                "relevant_state_evidence_note": "The liquid-color region inside this mug visibly changes between the two referenced stages.",
                "images_readable_and_relevant": True, "no_unresolved_visual_text_conflict": True, "decision": "approve"})
            sample["questions"][1].update({
                "mode": "visual_history_and_rules",
                "claim_notes": {"before_condition": "Cooked state is not directly visible.", "event_evidence": "The supplied activation event succeeds.", "effect_or_preservation_reason": "The supplied rule supports the inference for this queried state."},
                "evidence_refs": [{"kind": "frame", "frame_path": frame_paths[0]}, {"kind": "history_fact", "history_index": 0, "fact_index": 0}, {"kind": "event", "field": "success"}, {"kind": "rule", "rule_index": 0}],
                "state_discriminability_review": "not_required_inferred", "state_discriminability_reason": "The current cooked state is inferred from supplied history, rule, and event, not claimed as visible in the image.",
                "images_readable_and_relevant": True, "no_unresolved_visual_text_conflict": True, "decision": "approve"})
            sample["questions"][2].update({
                "mode": "oracle_history_and_rules",
                "claim_notes": {"before_condition": "The public history records the initial state.", "event_evidence": "The declared event succeeded.", "effect_or_preservation_reason": "The declared rule relates the event to this fact."},
                "evidence_refs": [{"kind": "history_fact", "history_index": 0, "fact_index": 0}, {"kind": "event", "field": "action"}, {"kind": "rule", "rule_index": 0}],
                "calibration_not_required_reason": "This explicitly uses the source oracle history-and-rules protocol.",
                "images_readable_and_relevant": True, "no_unresolved_visual_text_conflict": True, "decision": "approve"})
        form_path.write_text(json.dumps(form), encoding="utf-8")
        return output, form_path, form

    def test_prepared_form_stays_pending_and_never_autoapproves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, packet = Path(tmp) / "export", Path(tmp) / "packet"
            root.mkdir()
            self._export(root)
            ew.prepare(root, packet)
            form = json.loads((packet / "review_form.json").read_text(encoding="utf-8"))
            self.assertTrue(all(q["decision"] == "pending" for s in form["samples"] for q in s["questions"]))
            self.assertFalse(ew.check(root, packet / "review_form.json")["approved"])
            self.assertFalse(any("secret" in p.read_text(encoding="utf-8") for p in packet.rglob("*.json")))

    def test_png_header_without_decodable_pixels_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            image = root / "data" / "media" / "M01_A_before.png"
            image.write_bytes(png_header()[:24])
            with self.assertRaises((ValueError, OSError, SyntaxError)):
                ew.prepare(root, Path(tmp) / "packet")

    def test_unmatched_public_and_gold_records_cannot_disappear_from_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            (root / "hidden_gold" / "M01_B.json").unlink()
            with self.assertRaisesRegex(ValueError, "sample sets differ"):
                ew.prepare(root, Path(tmp) / "packet")

    def test_all_three_evidence_modes_can_pass_with_required_proofs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            _, form_path, _ = self._packet(root, Path(tmp))
            result = ew.check(root, form_path)
            self.assertTrue(result["approved"], result["errors"])
            self.assertTrue(any("Exact duplicate RGB hash" in warning for warning in result["warnings"]))

    def test_changed_rgb_invalidates_completed_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            _, form_path, _ = self._packet(root, Path(tmp))
            (root / "data" / "media" / "M01_A_before.png").write_bytes(png_header(17, 12))
            result = ew.check(root, form_path)
            self.assertFalse(result["approved"])
            self.assertTrue(any("fingerprint" in error.lower() for error in result["errors"]))

    def test_fake_history_fact_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            _, form_path, form = self._packet(root, Path(tmp))
            form["samples"][0]["questions"][1]["evidence_refs"][1]["fact_index"] = 99
            form_path.write_text(json.dumps(form), encoding="utf-8")
            result = ew.check(root, form_path)
            self.assertFalse(result["approved"])
            self.assertTrue(any("fact_index is invalid" in error for error in result["errors"]))

    def test_direct_visual_requires_both_before_and_after_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            _, form_path, form = self._packet(root, Path(tmp))
            form["samples"][0]["questions"][0]["evidence_refs"] = [{"kind": "frame", "frame_path": "data/media/M01_A_before.png"}]
            form_path.write_text(json.dumps(form), encoding="utf-8")
            result = ew.check(root, form_path)
            self.assertFalse(result["approved"])
            self.assertTrue(any("before and after" in error for error in result["errors"]))

    def test_inferred_hidden_final_state_does_not_require_visual_discriminability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            _, form_path, form = self._packet(root, Path(tmp))
            q = form["samples"][0]["questions"][1]
            q["state_discriminability_review"] = "not_required_inferred"
            q["state_discriminability_reason"] = "The target property is hidden; its value follows from the allowed public protocol evidence."
            q["calibration_note"] = ""
            form_path.write_text(json.dumps(form), encoding="utf-8")
            self.assertTrue(ew.check(root, form_path)["approved"])

    def test_visual_history_and_rules_can_pass_without_oracle_fact_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            _, form_path, form = self._packet(root, Path(tmp))
            q = form["samples"][0]["questions"][1]
            q["evidence_refs"] = [ref for ref in q["evidence_refs"] if ref["kind"] != "history_fact"]
            form_path.write_text(json.dumps(form), encoding="utf-8")
            self.assertTrue(ew.check(root, form_path)["approved"])

    def test_same_path_cannot_supply_both_direct_visual_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "export"
            root.mkdir()
            self._export(root)
            _, form_path, form = self._packet(root, Path(tmp))
            public_path = root / "data" / "input" / "M01_A.json"
            public = json.loads(public_path.read_text(encoding="utf-8"))
            frames = public["model_input"]["frames"]
            frames[1]["path"] = frames[0]["path"]
            public_path.write_text(json.dumps(public), encoding="utf-8")
            # The changed public record also makes the saved review stale. Rebind the
            # fingerprints to isolate the cross-stage ambiguity check itself.
            form["root_fingerprint"] = __import__("hashlib").sha256(json.dumps(
                {sid: ew.sample_fingerprint(root, sid) for sid in ew._sample_ids(root)},
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            for sample in form["samples"]:
                sample["sample_fingerprint"] = ew.sample_fingerprint(root, sample["sample_id"])
            form_path.write_text(json.dumps(form), encoding="utf-8")
            result = ew.check(root, form_path)
            self.assertFalse(result["approved"])
            self.assertTrue(any("assigned to both before and after" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
