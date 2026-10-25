"""Contract tests use fake native metadata; no controller or Unity is started."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mechanism_probe_common import ProbeContext, ProbeUnavailable, native_temperature


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
