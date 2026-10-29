"""Mock contracts for H01-1; these do not establish Unity contact/visibility."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hard_h01 import H01Natural, camera_delta, checkpoint_plan, liquid, parked, tilt
from hard_scenarios import HardConstructionError


class CupFixture:
    def __init__(self, directory, *, contact=True, spill=True):
        self.out = Path(directory)
        self.directory = self.out
        (self.out / "frames").mkdir(exist_ok=True)
        (self.out / "frames/fake.png").write_bytes(b"fixture-image-only-not-unity")
        self.roles = {"A": "a", "B": "b", "M": "m", "Faucet": "f", "SinkBasin": "s"}
        self.waypoints = {"A_park": {"objectId": "pa"}, "B_park": {"objectId": "pb"}}
        self.objects = {
            "a": {"objectId": "a", "position": {"x": 0., "y": 1., "z": 0.},
                  "rotation": {"x": 0., "y": 0., "z": 0.}, "isFilledWithLiquid": False,
                  "fillLiquid": None, "isPickedUp": False, "parentReceptacles": ["pa"]},
            "b": {"objectId": "b", "position": {"x": 1., "y": 1., "z": 0.},
                  "rotation": {"x": 0., "y": 0., "z": 0.}, "isFilledWithLiquid": False,
                  "fillLiquid": None, "isPickedUp": False, "parentReceptacles": ["pb"]},
            "m": {"objectId": "m", "isToggled": False, "receptacleObjectIds": []},
            "f": {"objectId": "f", "isToggled": False, "position": {"x": 0., "y": 1.1, "z": .2}},
            "s": {"objectId": "s", "position": {"x": 0., "y": .8, "z": .2}},
            "pa": {"objectId": "pa", "receptacleObjectIds": ["a"]},
            "pb": {"objectId": "pb", "receptacleObjectIds": ["b"]},
        }
        self.contact = contact
        self.spill = spill
        self.held = []
        self.records = []
        self.events = []
        self.checks = []
        self.public_phase = False
        self.navigation_attempts = []
        self.agent = {"position": {"x": 0., "y": .9, "z": 0.}, "rotation": {"y": 0}, "cameraHorizon": 0}
        self.session = self
        self.trace = self
        self.ops = self
        self.initial_identity_regions = []

    def obj(self, alias):
        return copy.deepcopy(self.objects[self.roles.get(alias, alias)])

    def snapshot(self):
        return {"objects": copy.deepcopy(list(self.objects.values())), "inventoryObjects": self.inventory(),
                "agent": copy.deepcopy(self.agent)}

    def inventory(self):
        return [{"objectId": oid} for oid in self.held]

    def phase(self, label, public=False, kind="history"):
        self.public_phase = public

    def require(self, value, message):
        if not value:
            raise HardConstructionError(message)

    def check(self, name, passed, detail):
        self.checks.append({"name": name, "passed": passed, "detail": detail})

    def capture_current(self, label):
        result = {"global_step": len(self.events), "frame_status": "captured",
                  "frames": [{"view_id": "agent", "path": "frames/fake.png"}], "capture_label": label}
        self.events.append(result)
        return result

    def navigate_to(self, role, purpose):
        return None

    def pickup_event(self, oid, look_first=False):
        self.held = [oid]
        self.objects[oid]["isPickedUp"] = True
        self.objects[oid]["parentReceptacles"] = []
        return self.step("PickupObject", objectId=oid)

    def put_event(self, oid, parent):
        self.held = []
        self.objects[oid]["isPickedUp"] = False
        self.objects[oid]["parentReceptacles"] = [parent]
        self.objects[parent]["receptacleObjectIds"] = [oid]
        return self.step("PutObject", objectId=parent)

    def step(self, action, **kwargs):
        row = {"index": len(self.records), "action": action, "kwargs": kwargs, "lastActionSuccess": True}
        self.records.append(row)
        if action.startswith("ToggleObject"):
            self.objects[kwargs["objectId"]]["isToggled"] = action == "ToggleObjectOn"
        if self.held:
            obj = self.objects[self.held[0]]
            if action == "MoveHeldObject":
                for axis, key in (("x", "right"), ("y", "up"), ("z", "ahead")):
                    obj["position"][axis] += kwargs[key]
            if action == "RotateHeldObject":
                # Match the pinned float-overload semantics: native deltas.
                obj["rotation"]["x"] += kwargs["pitch"]
                obj["rotation"]["y"] += kwargs["yaw"]
                obj["rotation"]["z"] = (obj["rotation"]["z"] - kwargs["roll"]) % 360
                if self.spill and tilt(obj) > 90:
                    obj.update(isFilledWithLiquid=False, fillLiquid=None)
            if self.contact and self.objects["f"]["isToggled"] and obj["position"]["z"] >= .18:
                obj.update(isFilledWithLiquid=True, fillLiquid="water")
        metadata = self.snapshot()
        if action == "GetReachablePositions":
            metadata["actionReturn"] = copy.deepcopy(getattr(self, "reachable_positions", []))
        return SimpleNamespace(record=row, metadata=metadata)


class H01NaturalTests(unittest.TestCase):
    def test_world_to_camera_translation_and_actual_spill_tilt(self):
        args = camera_delta({"x": 0, "y": 0, "z": 1}, {"rotation": {"y": 90}, "cameraHorizon": 0})
        self.assertAlmostEqual(args["right"], -1.)
        self.assertAlmostEqual(args["ahead"], 0., places=6)
        self.assertAlmostEqual(tilt({"rotation": {"x": 0, "y": 80, "z": 100}}), 100.)

    def test_missing_liquid_metadata_is_not_an_empty_cup(self):
        self.assertIsNone(liquid({}))
        self.assertIsNone(liquid({"isFilledWithLiquid": False, "fillLiquid": "water"}))

    def test_countertop_ancestor_cannot_certify_outside_machine_parking(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            ctx.objects["a"]["parentReceptacles"] = ["pa", "m"]
            self.assertFalse(parked(ctx, "A"))

    def test_plan_order_and_unexecuted_failure_tail(self):
        rows = checkpoint_plan()
        ids = [row["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLess(ids.index("T02-W06"), ids.index("T03-D01"))
        self.assertLess(ids.index("T04-D04"), ids.index("T05-W01"))
        with tempfile.TemporaryDirectory() as temp:
            story = H01Natural(CupFixture(temp))
            story.begin("T01-W01")
            with self.assertRaises(HardConstructionError):
                story.finish([("A应有水", "Water", "Empty")])
            self.assertEqual(story.active["status"], "failed")
            self.assertEqual(next(r for r in story.ctx.h01_checkpoints if r["id"] == "T02-W01")["status"], "not_executed")
            self.assertTrue((Path(temp) / "h01_checkpoints.json").is_file())

    def test_natural_water_history_has_no_direct_liquid_setter(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            story = H01Natural(ctx)
            story.calibrations["A"] = {"goal_center": {"x": 0., "y": 1., "z": .2}}
            story.water("A", "T01")
            self.assertEqual(liquid(ctx.obj("A")), "Water")
            self.assertEqual(liquid(ctx.obj("B")), "Empty")
            actions = [r["action"] for r in ctx.records]
            self.assertIn("MoveHeldObject", actions)
            self.assertIn("ToggleObjectOn", actions)
            self.assertIn("ToggleObjectOff", actions)
            self.assertNotIn("FillObjectWithLiquid", actions)
            self.assertNotIn("EmptyLiquidFromObject", actions)
            self.assertTrue(all(r["status"] == "passed" for r in ctx.h01_checkpoints if r["id"].startswith("T01")))

    def test_source_on_and_sink_geometry_without_contact_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp, contact=False)
            story = H01Natural(ctx)
            story.calibrations["A"] = {"goal_center": {"x": 0., "y": 1., "z": .2}}
            with self.assertRaisesRegex(HardConstructionError, "T01-W04"):
                story.water("A", "T01")
            self.assertEqual(story.active["status"], "failed")
            self.assertNotIn("FillObjectWithLiquid", [r["action"] for r in ctx.records])

    def test_actual_tilt_empties_and_upright_preserves_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            ctx.objects["a"].update(isFilledWithLiquid=True, fillLiquid="water")
            story = H01Natural(ctx)
            story.expected_liquids["A"] = "Water"
            story.spill("A", "T03")
            self.assertEqual(liquid(ctx.obj("A")), "Empty")
            self.assertLess(tilt(ctx.obj("A")), 15)
            self.assertNotIn("EmptyLiquidFromObject", [r["action"] for r in ctx.records])
            rolls = [r["kwargs"]["roll"] for r in ctx.records if r["action"] == "RotateHeldObject"]
            self.assertEqual(rolls, [20] * 5 + [-20] * 5)
            self.assertEqual(story.pending_spill_rolls["A"], [])
            self.assertTrue(all(r["status"] == "passed" for r in ctx.h01_checkpoints if r["id"].startswith("T03")))

    def test_tilt_without_native_liquid_effect_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp, spill=False)
            ctx.objects["a"].update(isFilledWithLiquid=True, fillLiquid="water")
            story = H01Natural(ctx)
            story.expected_liquids["A"] = "Water"
            with self.assertRaisesRegex(HardConstructionError, "no direct empty fallback"):
                story.spill("A", "T03")

    def test_calibration_does_not_repeat_dry_contact_control(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            story = H01Natural(ctx)
            story.calibrate_water("A")
            actions = [r["action"] for r in ctx.records]
            self.assertLess(actions.index("ToggleObjectOn"), actions.index("MoveHeldObject"))
            self.assertEqual(actions.count("ToggleObjectOn"), 1)
            self.assertEqual(story.calibrations["A"]["status"], "verified")
            self.assertFalse(story.calibrations["A"]["dry_control_repeated"])
            self.assertNotIn("dry_control_passed", story.calibrations["A"]["trials"][0])

    def test_primary_spill_restore_failure_is_not_masked_by_water_path_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            story = H01Natural(ctx)
            with patch.object(story, "upright", side_effect=HardConstructionError("primary restoration failed")):
                with self.assertRaisesRegex(HardConstructionError, "primary restoration failed"):
                    story.calibrate_water("A")
            self.assertEqual(story.calibrations["A"]["trials"][0]["stage"], "spill_and_restore")
            self.assertEqual(ctx.records[-1]["action"], "RotateHeldObject")
            self.assertIn("primary restoration failed", story.calibrations["A"]["trials"][0]["error"])

    def test_unrelated_cup_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            story = H01Natural(ctx)
            story.baseline("A")
            ctx.objects["b"].update(isFilledWithLiquid=True, fillLiquid="coffee")
            with self.assertRaisesRegex(HardConstructionError, "Inactive cup"):
                story.guard()

    def test_first_pickup_anchor_only_applies_to_h01_1(self):
        from hard_export import public_roles
        from hard_scenarios import _h01
        with patch("hard_h01.run_h01_1", return_value="natural") as run:
            self.assertEqual(_h01(object(), 1), "natural")
            run.assert_called_once()
        ordinary = SimpleNamespace(group_id="H01", roles={"A": "a", "B": "b", "M": "m", "Faucet": "f"})
        self.assertEqual(public_roles(ordinary), ["A", "B", "M"])
        ordinary.h01_natural = True
        self.assertEqual(public_roles(ordinary), ["A", "B", "M", "Faucet"])

    def test_missing_checkpoint_image_cannot_pass_on_metadata_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            story = H01Natural(ctx)
            (Path(temp) / "frames/fake.png").unlink()
            story.begin("C01")
            with self.assertRaisesRegex(HardConstructionError, "C01"):
                story.finish([("元数据成立", True, True)])
            self.assertFalse(story.active["facts"][-1]["passed"])

    def test_checkpoint_gold_and_native_ids_stay_outside_model_input(self):
        import json
        from hard_export import export_case
        from test_hard_pipeline import TraceFixture, fixture_context
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trace = TraceFixture(root / "audit_traces/H05-1")
            ctx = fixture_context()
            ctx.h01_checkpoints = [{"id": "C01", "state": {"secret": "private-checkpoint-native-id"},
                                    "expected_answer": "private-checkpoint-gold"}]
            export_case(ctx, trace, root, SimpleNamespace(case_id="H05-1"))
            text = (root / "data/input/H05-1_V.json").read_text(encoding="utf-8")
            self.assertNotIn("private-checkpoint-native-id", text)
            self.assertNotIn("private-checkpoint-gold", text)
            self.assertNotIn("checkpoints", json.loads(text)["model_input"])

    def test_visible_faucet_requires_closer_native_stance_before_hand_motion(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            ctx.reachable_positions = [{"x": x, "y": .9, "z": 0.} for x in (0., -.25, -.5)]
            walked = []

            def walk(point):
                delta = point["x"] - ctx.agent["position"]["x"]
                ctx.objects["a"]["position"]["x"] += delta
                ctx.agent["position"] = copy.deepcopy(point)
                walked.append(copy.deepcopy(point))

            ctx.navigator = SimpleNamespace(_walk=walk, _aim=lambda obj: None, action_count=0)
            story = H01Natural(ctx)
            story.begin("C03-A")
            story.pickup("A")
            goal = {"x": -1., "y": 1., "z": 0.}
            position = story.approach_water("A", [goal])
            self.assertEqual(position["x"], -.5)
            self.assertTrue(walked)
            evidence = ctx.navigation_attempts[-1]
            self.assertGreater(evidence["initial_hand_distances_m"][0], evidence["hand_budget_m"])
            self.assertLessEqual(evidence["attempts"][-1]["actual_hand_distances_m"][0], evidence["hand_budget_m"])
            self.assertEqual(evidence["hand_budget_m"], .85)
            self.assertEqual(evidence["status"], "walked_within_hand_budget")
            self.assertNotIn("MoveHeldObject", [r["action"] for r in ctx.records])

    def test_public_water_approach_reuses_verified_standing_position(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = CupFixture(temp)
            ctx.reachable_positions = [{"x": x, "y": .9, "z": 0.} for x in (0., -.25, -.5)]

            def walk(point):
                ctx.objects["a"]["position"]["x"] += point["x"] - ctx.agent["position"]["x"]
                ctx.agent["position"] = copy.deepcopy(point)

            ctx.navigator = SimpleNamespace(_walk=walk, _aim=lambda obj: None, action_count=0)
            story = H01Natural(ctx)
            story.begin("T01-W02")
            story.pickup("A")
            preferred = {"x": -.25, "y": .9, "z": 0.}
            result = story.approach_water("A", [{"x": .2, "y": 1., "z": 0.}], preferred=preferred)
            self.assertEqual(result, preferred)
            self.assertEqual(ctx.navigation_attempts[-1]["preferred_verified_position"], preferred)


if __name__ == "__main__":
    unittest.main()
