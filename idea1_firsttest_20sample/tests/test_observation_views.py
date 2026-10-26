"""Native-call fixtures for evidence-camera isolation, not Unity reproductions."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from observation_views import (DIAGNOSTIC_MAX_OBJECTS, EvidenceCameras, physics_is_paused,
                               observation_state_delta, state_diff_audit, world_state)


def small_plan(*args, **kwargs):
    return {"status": "planned", "groups": [{"group_id": "cup", "purpose": "contents_detail",
        "roles": ["Mug"], "focus": {"point": {"x": 1, "y": 1, "z": 1}},
        "candidates": [{"position": {"x": x, "y": 2, "z": 2},
                        "rotationEuler": {"x": 35, "y": 180, "z": 0}, "fov_degrees": 60}
                       for x in (0, 2)]}]}


class Session:
    def __init__(self, mutate=False, paused=False, mutate_on_unpause=False,
                 control_motion=False, move_during_pause=False):
        self.records = [{"action": "Initialize", "lastActionSuccess": True}]
        if paused:
            self.records.append({"action": "PausePhysicsAutoSim", "lastActionSuccess": True})
        self.metadata = {"objects": [{"objectId": "mug", "objectType": "Mug", "temperature": "RoomTemp",
                          "position": {"x": 1, "y": 1, "z": 1}}], "thirdPartyCameras": []}
        self.cameras = []
        self.mutate = mutate
        self.mutate_on_unpause = mutate_on_unpause
        self.control_motion = control_motion
        self.move_during_pause = move_during_pause
        if control_motion:
            self.metadata["objects"][0]["isMoving"] = True
        self.controller = SimpleNamespace(last_event=None)
        self.refresh()

    def refresh(self):
        masks = []
        for camera in self.cameras:
            mask = np.zeros((60, 80), dtype=bool)
            if camera["position"]["x"] == 2:
                mask[20:40, 25:45] = True
            masks.append({"mug": mask})
        self.controller.last_event = SimpleNamespace(
            metadata=self.snapshot(), third_party_camera_frames=[np.zeros((60, 80, 3), dtype=np.uint8) for _ in masks],
            third_party_instance_masks=masks,
            # This primary-camera trap must not approve the first candidate.
            instance_detections2D={"mug": (0, 0, 79, 59)})

    def snapshot(self):
        return copy.deepcopy(self.metadata)

    def step(self, action, **kwargs):
        if action == "PausePhysicsAutoSim":
            if self.control_motion:
                self.metadata["objects"][0]["isMoving"] = False
            if self.move_during_pause:
                self.metadata["objects"][0]["position"]["x"] += 0.01
        elif action == "AddThirdPartyCamera":
            self.cameras.append(copy.deepcopy(kwargs))
        elif action == "UpdateThirdPartyCamera":
            self.cameras[kwargs["thirdPartyCameraId"]] = copy.deepcopy(kwargs)
            if self.mutate:
                self.metadata["objects"][0]["temperature"] = "Hot"
        elif action == "UnpausePhysicsAutoSim":
            if self.mutate_on_unpause:
                self.metadata["objects"][0]["temperature"] = "Hot"
            if self.control_motion:
                self.metadata["objects"][0]["isMoving"] = True
        self.metadata["thirdPartyCameras"] = [{"thirdPartyCameraId": i, **c} for i,c in enumerate(self.cameras)]
        row = {"action": action, "lastActionSuccess": True, "kwargs": kwargs}
        self.records.append(row)
        self.refresh()
        return SimpleNamespace(record=row, metadata=self.snapshot(), event=self.controller.last_event)


class ObserverTests(unittest.TestCase):
    def test_motion_flags_are_exempt_only_for_physics_control(self):
        before = world_state({"objects": [{"objectId": "mug", "isMoving": True}]})
        after = world_state({"objects": [{"objectId": "mug", "isMoving": False}]})
        self.assertEqual(observation_state_delta(before, after, phase="pause"), ([], ["mug"]))
        self.assertEqual(observation_state_delta(before, after, phase="unpause"), ([], ["mug"]))
        self.assertEqual(observation_state_delta(before, after, phase="update_camera_candidate"), (["mug"], []))

    @patch("observation_views.plan_views", small_plan)
    def test_pause_motion_flags_rebase_without_hiding_camera_changes(self):
        session = Session(control_motion=True)
        observer = EvidenceCameras(session, family="coffee")
        with tempfile.TemporaryDirectory() as tmp:
            report = observer.capture(session.snapshot(), {"Mug": "mug"}, Path(tmp) / "rgb", "control")
            self.assertEqual(len(report["views"]), 1)
        self.assertFalse(report["world_state_changed"])
        self.assertTrue(report["raw_metadata_changed"])
        audit = report["state_diff_audit"]
        self.assertEqual(audit["first_changed_action"]["phase"], "pause")
        self.assertIsNone(audit["first_rejected_action"])
        self.assertEqual(audit["action_checks"][0]["control_motion_flag_changes"], ["mug"])
        self.assertTrue(all(not check["guard_changed_entities"] for check in audit["action_checks"]))

    @patch("observation_views.plan_views", small_plan)
    def test_pause_geometry_change_still_rejected(self):
        session = Session(control_motion=True, move_during_pause=True)
        observer = EvidenceCameras(session, family="coffee")
        with tempfile.TemporaryDirectory() as tmp:
            report = observer.capture(session.snapshot(), {"Mug": "mug"}, Path(tmp) / "rgb", "moved")
        self.assertTrue(report["world_state_changed"])
        self.assertEqual(report["views"], [])
        self.assertEqual(report["state_diff_audit"]["first_rejected_action"]["phase"], "pause")
        self.assertFalse(any(row["action"] == "AddThirdPartyCamera" for row in session.records))

    def test_world_guard_keeps_motion_state_even_without_position_change(self):
        before = {"objects": [{"objectId": "mug", "isMoving": True}]}
        after = {"objects": [{"objectId": "mug", "isMoving": False}]}
        self.assertNotEqual(world_state(before), world_state(after))

    @patch("observation_views.plan_views", small_plan)
    def test_uses_third_party_mask_and_does_not_teleport_or_move_agent(self):
        session = Session()
        observer = EvidenceCameras(session, family="coffee")
        before = world_state(session.snapshot())
        with tempfile.TemporaryDirectory() as tmp:
            report = observer.capture(session.snapshot(), {"Mug": "mug"}, Path(tmp), "before")
            self.assertEqual(len(report["views"]), 1)
            self.assertEqual(report["views"][0]["pose"]["position"]["x"], 2)
            self.assertFalse(report["world_state_changed"])
            self.assertEqual(before, world_state(session.snapshot()))
            self.assertFalse(physics_is_paused(session.records))
            self.assertFalse(any(r["action"] in {"TeleportFull", "PickupObject", "OpenObject"} for r in session.records))
            count = len(session.records)
            observer.capture(session.snapshot(), {"Mug": "mug"}, Path(tmp), "after")
            self.assertEqual(len(session.records), count)  # cached, no camera action

    @patch("observation_views.plan_views", small_plan)
    def test_respects_existing_experimental_pause(self):
        session = Session(paused=True)
        observer = EvidenceCameras(session, family="coffee")
        with tempfile.TemporaryDirectory() as tmp:
            observer.capture(session.snapshot(), {"Mug": "mug"}, Path(tmp), "paused")
        self.assertTrue(physics_is_paused(session.records))
        self.assertFalse(any(r["action"] == "UnpausePhysicsAutoSim" for r in session.records))

    @patch("observation_views.plan_views", small_plan)
    def test_native_state_drift_invalidates_photographic_intervention(self):
        session = Session(mutate=True)
        observer = EvidenceCameras(session, family="coffee")
        with tempfile.TemporaryDirectory() as tmp:
            rgb = Path(tmp) / "rgb"
            report = observer.capture(session.snapshot(), {"Mug": "mug"}, rgb, "changed")
            self.assertTrue(report.get("diagnostic_metadata_directory"))
            diagnostic = Path(report["diagnostic_metadata_directory"])
            self.assertTrue((diagnostic / "before.json").is_file())
            self.assertTrue((diagnostic / "update_camera_candidate_after.json").is_file())
            self.assertTrue(report.get("diagnostic_frames"))
            self.assertTrue(all(not f["approved_evidence"] for f in report["diagnostic_frames"]))
            self.assertFalse(list(rgb.glob("changed_view_*.png")))
        self.assertTrue(report["world_state_changed"])
        self.assertEqual(report["views"], [])
        self.assertTrue(observer.contaminated)
        self.assertIn("mug", report["changed_objects"])
        self.assertFalse(physics_is_paused(session.records))
        audit = report["state_diff_audit"]
        self.assertEqual(audit["first_changed_action"]["phase"], "update_camera_candidate")
        self.assertEqual(audit["first_changed_action"]["action"], "UpdateThirdPartyCamera")
        first = next(row for row in audit["action_checks"] if row["changed_entity_count"])
        self.assertEqual(first["changes"][0]["object_id"], "mug")
        self.assertEqual(first["changes"][0]["selected_target_roles"], ["Mug"])
        self.assertFalse(first["changes"][0]["unrelated_object"])
        self.assertEqual(first["changes"][0]["fields"]["temperature"],
                         {"before": "RoomTemp", "after": "Hot"})
        self.assertEqual(audit["action_checks"][-1]["phase"], "unpause")
        self.assertEqual(report["views"], [])

    @patch("observation_views.plan_views", small_plan)
    def test_restore_drift_quarantines_pngs_already_written(self):
        session = Session(mutate_on_unpause=True)
        observer = EvidenceCameras(session, family="coffee")
        with tempfile.TemporaryDirectory() as tmp:
            rgb = Path(tmp) / "rgb"
            report = observer.capture(session.snapshot(), {"Mug": "mug"}, rgb, "restore")
            self.assertEqual(report["views"], [])
            self.assertTrue(report["world_state_changed"])
            self.assertEqual(report["state_diff_audit"]["first_changed_action"]["phase"], "unpause")
            self.assertFalse(list(rgb.glob("restore_view_*.png")))
            invalidated = [f for f in report["diagnostic_frames"]
                           if f["purpose"] == "invalidated_after_restore"]
            self.assertEqual(len(invalidated), 1)
            self.assertTrue(Path(invalidated[0]["path"]).is_file())
            self.assertFalse(invalidated[0]["approved_evidence"])

    def test_state_diff_audit_identifies_added_unrelated_object_and_bounds_entries(self):
        before = world_state({"objects": [{"objectId": "mug", "position": {"x": 0}}]})
        after = world_state({"objects": [{"objectId": "mug", "position": {"x": 1}},
                                          {"objectId": "apple", "isMoving": True}]})
        audit = state_diff_audit(before, after, {"Mug": "mug"}, phase="add_camera_candidate",
                                 action="AddThirdPartyCamera", action_index=7,
                                 action_kwargs={"position": {"x": 0, "y": 2, "z": 1}})
        self.assertEqual(audit["action_index"], 7)
        self.assertEqual(audit["phase"], "add_camera_candidate")
        mug = next(row for row in audit["changes"] if row["object_id"] == "mug")
        apple = next(row for row in audit["changes"] if row["object_id"] == "apple")
        self.assertEqual(mug["fields"]["position"]["before"]["x"], 0.0)
        self.assertEqual(mug["fields"]["position"]["after"]["x"], 1.0)
        self.assertFalse(mug["unrelated_object"])
        self.assertTrue(apple["unrelated_object"])
        self.assertEqual(apple["status"], "added")

        many_before = world_state({"objects": []})
        many_after = world_state({"objects": [{"objectId": f"obj-{i}"} for i in range(50)]})
        bounded = state_diff_audit(many_before, many_after, {}, phase="test", action="Pass",
                                   action_index=8)
        self.assertEqual(len(bounded["changes"]), DIAGNOSTIC_MAX_OBJECTS)
        self.assertTrue(bounded["truncated"])
        self.assertEqual(bounded["changed_entity_count"], 50)
        self.assertEqual(bounded["changed_entity_key_count"], 50)
        self.assertEqual(len(bounded["changed_entities"]), DIAGNOSTIC_MAX_OBJECTS)


if __name__ == "__main__":
    unittest.main()
