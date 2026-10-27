"""Mock-only camera preflight checks; no AI2-THOR process is started."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hard_camera import (CameraPreflightError, _constrain_candidates_to_room, _microwave_contents_candidates,
                         _overview_candidates, _role_envelope, audit_fixed_views,
                         configure_evidence_cameras)


def object_row(object_id, object_type, x, y=1.0, z=1.0):
    return {"objectId": object_id, "objectType": object_type,
            "position": {"x": x, "y": y, "z": z},
            "axisAlignedBoundingBox": {"center": {"x": x, "y": y, "z": z},
                                       "size": {"x": .3, "y": .3, "z": .3}}}


class CameraSession:
    def __init__(self, mutate=False):
        self.metadata = {"objects": [object_row("machine", "CoffeeMachine", 1.0),
                                     object_row("mug", "Mug", 1.2)],
                         "agent": {"position": {"x": 0, "y": 0, "z": 0},
                                   "rotation": {"x": 0, "y": 0, "z": 0}},
                         "inventoryObjects": [], "thirdPartyCameras": []}
        self.cameras = []
        self.records = []
        self.mutate = mutate
        self.mutate_once = False
        self.controller = SimpleNamespace(last_event=None)
        self.refresh()

    def snapshot(self):
        import copy
        return copy.deepcopy(self.metadata)

    def refresh(self):
        masks = []
        frames = []
        for _camera in self.cameras:
            frames.append(np.zeros((40, 60, 3), dtype=np.uint8))
            masks.append({"machine": np.ones((40, 60), dtype=bool),
                          "mug": np.ones((40, 60), dtype=bool)})
        self.metadata["thirdPartyCameras"] = [
            {"thirdPartyCameraId": index, **camera} for index, camera in enumerate(self.cameras)]
        self.controller.last_event = SimpleNamespace(
            metadata=self.snapshot(), third_party_camera_frames=frames,
            third_party_instance_masks=masks,
            frame=np.zeros((40, 60, 3), dtype=np.uint8))

    def step(self, action, *, raise_on_failure=False, **kwargs):
        if action == "AddThirdPartyCamera":
            self.cameras.append(dict(kwargs))
        elif action == "UpdateThirdPartyCamera":
            camera_id = kwargs["thirdPartyCameraId"]
            self.cameras[camera_id] = dict(kwargs)
            if self.mutate and not self.mutate_once:
                self.metadata["objects"][1]["position"]["x"] += .1
                self.mutate_once = True
        else:
            raise AssertionError(f"unexpected native action: {action}")
        index = len(self.records)
        self.refresh()
        record = {"index": index, "action": action, "kwargs": kwargs,
                  "lastActionSuccess": True, "errorMessage": ""}
        self.records.append(record)
        return SimpleNamespace(record=record, metadata=self.snapshot(), event=self.controller.last_event)


class Context:
    hard_group = "H01"
    public_history_started = False
    roles = {"CoffeeMachine": "machine", "Mug": "mug"}
    waypoints = {"Mug": [{"position": {"x": 2.0, "y": 1.0, "z": 1.0}}]}

    def __init__(self, session):
        self.session = session

    def obj(self, alias):
        object_id = self.roles[alias]
        return next(row for row in self.session.snapshot()["objects"] if row["objectId"] == object_id)


class Trace:
    def __init__(self):
        self._cameras = []
        self.events = []

    def set_cameras(self, cameras):
        self._cameras = cameras


class HardCameraTests(unittest.TestCase):
    def test_far_debug_camera_is_constrained_inside_measured_room_bounds(self):
        bounds = {"center": {"x": 0., "y": 1.25, "z": 0.},
                  "size": {"x": 5., "y": 2.7, "z": 5.5}}
        pose = {"position": {"x": 8., "y": 5., "z": -8.},
                "aim_point": {"x": 0., "y": 1., "z": 0.}}
        result = _constrain_candidates_to_room([pose], bounds)[0]
        self.assertLess(result["position"]["x"], 2.5)
        self.assertGreater(result["position"]["z"], -2.75)
        self.assertLess(result["position"]["y"], 2.6)
        self.assertTrue(result["room_bbox_constrained"])
        self.assertEqual(pose["position"]["x"], 8.)

    def test_overview_and_h05_detail_candidates_use_geometry_not_labels(self):
        roles = {
            "Microwave": object_row("microwave", "Microwave", 0.0, 1.8, -2.0),
            "Z": object_row("potato", "Potato", -1.4, 0.95, -2.1),
        }
        roles["Z"]["axisAlignedBoundingBox"]["size"] = {"x": 1.2, "y": 1.4, "z": 3.2}
        envelope = _role_envelope(roles, ["Microwave", "Z"])
        candidates = _overview_candidates(envelope)
        self.assertEqual(len(candidates), 6)
        self.assertTrue(all(candidate["fov_degrees"] > 70 for candidate in candidates))
        self.assertTrue(all(candidate["envelope"]["role_aliases"] == ["Microwave", "Z"]
                            for candidate in candidates))
        detail = _microwave_contents_candidates(roles, "Z", "Microwave")
        self.assertEqual(len(detail), 6)
        self.assertTrue(any("high" in row["candidate_id"] for row in detail))
        self.assertTrue(any("side" in row["candidate_id"] for row in detail))
        self.assertTrue(any("openfront" in row["candidate_id"] for row in detail))
        self.assertTrue(all(row["semantic_readability"] == "not_assessed" for row in detail))

    def test_geometry_preflight_adds_fixed_cameras_and_reports_mask_only_coverage(self):
        session = CameraSession()
        ctx = Context(session)
        trace = Trace()
        with tempfile.TemporaryDirectory() as temporary:
            report = configure_evidence_cameras(ctx, trace, temporary)
            self.assertEqual(report["status"], "screened")
            self.assertEqual(report["family"], "coffee_machine")
            self.assertLessEqual(len(report["poses"]), 3)
            self.assertEqual(report["selected_views"][0]["purpose"], "distant_room_overview")
            self.assertGreater(report["selected_views"][0]["camera_distance_to_aim_m"], 4.0)
            self.assertTrue(all(action["action"] in {"AddThirdPartyCamera", "UpdateThirdPartyCamera"}
                                for action in report["camera_actions"]))
            self.assertTrue(all(not action["guard_changed_entities"] for action in report["camera_actions"]))
            self.assertEqual(report["union_mask_coverage"]["missing_roles"], [])
            self.assertTrue(report["geometry_only_screening_not_semantic_approval"])
            self.assertEqual(report["semantic_readability"], "not_assessed")
            self.assertTrue(all(Path(path).is_file() for path in report["rgb_files"]))
            self.assertEqual(len(trace._cameras), len(report["selected_views"]))
            self.assertTrue(all(row["semantic_readability"] == "not_assessed"
                                for row in report["role_coverage_diagnostics"]))
            self.assertTrue(Path(temporary, "camera_preflight.json").is_file())

    def test_physical_state_change_raises_and_stops_camera_trials(self):
        session = CameraSession(mutate=True)
        ctx = Context(session)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(CameraPreflightError) as caught:
                configure_evidence_cameras(ctx, Trace(), temporary)
            self.assertTrue(caught.exception.report["world_state_changed"])
            self.assertTrue(caught.exception.report["changed_objects"])
            self.assertEqual(len(session.records), 2)  # Add then first Update triggers guard
            self.assertTrue(Path(temporary, "camera_preflight.json").is_file())

    def test_public_history_guard_and_audit_send_no_native_actions(self):
        session = CameraSession()
        ctx = Context(session)
        ctx.public_history_started = True
        trace = Trace()
        with tempfile.TemporaryDirectory() as temporary:
            rejected = configure_evidence_cameras(ctx, trace, temporary)
            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(session.records, [])
            ctx.public_history_started = False
            before = len(session.records)
            audit = audit_fixed_views(ctx, trace, "public_history")
            self.assertEqual(audit["native_actions_sent"], 0)
            self.assertEqual(len(session.records), before)
            self.assertEqual(audit["status"], "unavailable")

    def test_identical_rgb_with_changed_position_is_diagnostic_only(self):
        session = CameraSession()
        ctx = Context(session)
        trace = Trace()
        trace._cameras = [{"camera_id": 0, "view_id": "fixed_0", "purpose": "joint"}]
        event = session.controller.last_event
        event.instance_masks = {"machine": np.ones((40, 60), dtype=bool)}
        event.third_party_camera_frames = [np.zeros((40, 60, 3), dtype=np.uint8)]
        event.third_party_instance_masks = [{"mug": np.ones((40, 60), dtype=bool)}]
        trace.events = [
            {"global_step": 1, "phase_label": "history", "new_event_received": True,
             "frame_status": "captured", "metadata_gzip": "metadata/one.json.gz",
             "frames": [{"view_id": "agent", "pixel_sha256": "agent_same"},
                        {"view_id": "fixed_0", "pixel_sha256": "same"}]},
            {"global_step": 2, "phase_label": "history", "new_event_received": True,
             "frame_status": "captured", "metadata_gzip": "metadata/two.json.gz",
             "frames": [{"view_id": "agent", "pixel_sha256": "agent_same"},
                        {"view_id": "fixed_0", "pixel_sha256": "same"}]},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            trace.directory = Path(temporary)
            (Path(temporary) / "metadata").mkdir()
            first = session.snapshot()
            second = session.snapshot()
            second["objects"][1]["position"]["x"] += .5
            for name, metadata in (("one.json.gz", first), ("two.json.gz", second)):
                with gzip.open(Path(temporary) / "metadata" / name, "wt", encoding="utf-8") as stream:
                    json.dump(metadata, stream)
            session.metadata = second
            session.refresh()
            session.controller.last_event.instance_masks = {"machine": np.ones((40, 60), dtype=bool)}
            session.controller.last_event.third_party_camera_frames = [np.zeros((40, 60, 3), dtype=np.uint8)]
            session.controller.last_event.third_party_instance_masks = [{"mug": np.ones((40, 60), dtype=bool)}]
            report = audit_fixed_views(ctx, trace, "history")
        self.assertTrue(report["position_changed_while_all_fixed_rgb_identical"])
        self.assertTrue(report["position_changed_while_all_rgb_identical"])
        self.assertEqual(report["agent_plus_fixed_view_union_coverage"]["status"], "covered")
        self.assertEqual(report["role_state_snapshot"]["Mug"]["position"]["x"], 1.7)
        self.assertEqual(report["position_changed_roles"], ["Mug"])
        self.assertTrue(report["diagnostic_not_universal_error"])
        self.assertEqual(report["semantic_readability"], "not_assessed")
        self.assertIsNotNone(event)


if __name__ == "__main__":
    unittest.main()
