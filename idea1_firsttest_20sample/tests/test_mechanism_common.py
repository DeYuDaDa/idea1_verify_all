"""Contract tests use fake native metadata; no controller or Unity is started."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mechanism_probe_common import (ObservationCaptureFailure, ProbeContext, ProbeUnavailable,
                                    native_temperature)


class Session:
    def __init__(self):
        self.records = [{"action": "Initialize"}]
        self.metadata = {"objects": [
            {"objectId": "mug_a", "objectType": "Mug", "canFillWithLiquid": True,
             "ObjectTemperature": "RoomTemp", "position": {"x": 1, "y": 0, "z": 0}},
            {"objectId": "mug_b", "objectType": "Mug", "canFillWithLiquid": False},
        ]}
    def snapshot(self):
        return copy.deepcopy(self.metadata)
    def step(self, action, **kwargs):
        self.records.append({"action": action, "kwargs": kwargs, "lastActionSuccess": True})
        return SimpleNamespace(record=self.records[-1], metadata=self.snapshot())


class CommonContractTests(unittest.TestCase):
    def test_native_only_mode_records_state_without_camera_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Session()
            ctx = ProbeContext(session, Path(tmp) / "trial", view_mode="none")
            def forbidden(*args):
                raise AssertionError("Native-only mode invoked an evidence camera")
            ctx.evidence_cameras.capture = forbidden
            row = ctx.capture("scene_initial")
            self.assertFalse(row["image_requested"])
            self.assertEqual(row["image_omission_reason"], "native_state_only_mode")
            self.assertNotIn("capture_error", row)
            self.assertNotIn("rgb_path", row)
            self.assertEqual(len(session.records), 1)
            self.assertFalse((ctx.out / "rgb").exists())
            self.assertTrue((ctx.out / "snapshots/0000_scene_initial.json").is_file())

    def test_capture_failure_persists_receipt_before_stopping(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ProbeContext(Session(), Path(tmp) / "trial")
            ctx.evidence_cameras = SimpleNamespace(capture=lambda *args: {
                "views": [], "world_state_changed": True, "error": "camera changed state"})
            with self.assertRaisesRegex(ObservationCaptureFailure, "camera changed state"):
                ctx.capture("scene_initial")
            self.assertEqual(len(ctx.captures), 1)
            saved = json.loads((ctx.out / "snapshots/0000_scene_initial.json").read_text())
            self.assertTrue(saved["image_requested"])
            self.assertEqual(saved["view_frames"], [])
            self.assertEqual(saved["capture_error"], "camera changed state")
            self.assertEqual(len(ctx.session.records), 1)

    def test_sparse_images_preserve_full_observation_pass_horizon(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ProbeContext(Session(), Path(tmp) / "trial", sample_steps=(0, 1, 4, 12, 36))
            capture_at = []
            def capture(label):
                capture_at.append(len(ctx.session.records) - 1)
                return {"label": label}
            ctx.capture = capture
            rows = ctx.observe(total_steps=36)
            self.assertEqual(capture_at, [0, 1, 4, 12, 36])
            self.assertEqual(len(rows), 5)
            self.assertEqual(sum(r["action"] == "Pass" for r in ctx.session.records), 36)
            # A shorter photo schedule must not shorten the native experiment.
            ctx.sample_steps = (0,)
            start = len(ctx.session.records)
            self.assertEqual(len(ctx.observe(total_steps=36)), 1)
            self.assertEqual(len(ctx.session.records) - start, 36)

    def test_real_temperature_key_and_legacy_query_spellings_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Session()
            obj = session.metadata["objects"][0]
            obj.pop("ObjectTemperature")
            obj["temperature"] = "Hot"
            ctx = ProbeContext(session, Path(tmp) / "trial")
            ctx.bind("Cup", "mug_a")
            self.assertEqual(ctx.field("Cup", "temperature"), "Hot")
            self.assertEqual(ctx.field("Cup", "ObjectTemperature"), "Hot")
            self.assertNotIn("ObjectTemperature", session.metadata["objects"][0])

    def test_missing_temperature_is_unknown_and_null_can_use_legacy_field(self):
        self.assertIsNone(native_temperature({}))
        self.assertEqual(native_temperature({"temperature": None, "ObjectTemperature": "RoomTemp"}), "RoomTemp")

    def test_native_setup_placement_failure_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ProbeContext(Session(), Path(tmp) / "trial")
            def blocked(*args):
                raise RuntimeError("Spawn area not clear")
            ctx.ops.place_initial = blocked
            with self.assertRaisesRegex(ProbeUnavailable, "Spawn area not clear"):
                ctx.move_setup("mug_a", "counter")

    def test_missing_inventory_is_unavailable_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Session()
            ctx = ProbeContext(session, Path(tmp) / "trial")
            self.assertEqual(ctx.select("Cup", "Mug", capability="canFillWithLiquid"), "mug_a")
            with self.assertRaises(ProbeUnavailable):
                ctx.select("SecondCup", "Mug", capability="canFillWithLiquid", exclude=("Cup",))
            self.assertEqual(len(session.records), 1)

    def test_capture_does_not_advance_or_mutate_native_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Session()
            ctx = ProbeContext(session, Path(tmp) / "trial")
            ctx.bind("Cup", "mug_a")
            shot = ctx.capture("before_event", image=False)
            self.assertEqual(len(session.records), 1)
            self.assertEqual(ctx.field("Cup", "temperature"), "RoomTemp")
            shot["metadata"]["objects"][0]["position"]["x"] = 99
            self.assertEqual(session.metadata["objects"][0]["position"]["x"], 1)
            self.assertEqual(shot["visual_evidence_review"], "not_assessed")
            self.assertFalse(shot["native_time_units_verified"])

    def test_failed_check_does_not_change_mechanism_to_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ProbeContext(Session(), Path(tmp) / "trial")
            row = ctx.check("calibration", False, "unknown")
            self.assertFalse(row["passed"])
            self.assertNotIn("status", row)
            with self.assertRaises(ProbeUnavailable):
                ctx.require(False, "placement unavailable")

    def test_reset_keeps_each_native_action_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            import json
            session = Session()
            ctx = ProbeContext(session, Path(tmp) / "trial")
            ctx.capture("arm_a", image=False)
            session.records.append({"action": "ToggleObjectOn"})
            session.records = [{"action": "Initialize", "scene": "new_reset"}]
            shot = ctx.capture("arm_b", image=False)
            ctx.flush()
            segments = json.loads((ctx.out / "actions_by_reset.json").read_text())
            self.assertEqual(shot["action_segment"], 1)
            self.assertEqual(segments[0][-1]["action"], "ToggleObjectOn")
            self.assertEqual(segments[1][0]["scene"], "new_reset")


if __name__ == "__main__":
    unittest.main()
