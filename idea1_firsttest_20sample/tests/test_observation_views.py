"""Native-call fixtures for evidence-camera isolation, not Unity reproductions."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from observation_views import EvidenceCameras, world_state, physics_is_paused


def small_plan(*args, **kwargs):
    return {"status": "planned", "groups": [{"group_id": "cup", "purpose": "contents_detail",
        "roles": ["Mug"], "focus": {"point": {"x": 1, "y": 1, "z": 1}},
        "candidates": [{"position": {"x": x, "y": 2, "z": 2},
                        "rotationEuler": {"x": 35, "y": 180, "z": 0}, "fov_degrees": 60}
                       for x in (0, 2)]}]}


class Session:
    def __init__(self, mutate=False, paused=False):
        self.records = [{"action": "Initialize", "lastActionSuccess": True}]
        if paused:
            self.records.append({"action": "PausePhysicsAutoSim", "lastActionSuccess": True})
        self.metadata = {"objects": [{"objectId": "mug", "objectType": "Mug", "temperature": "RoomTemp",
                          "position": {"x": 1, "y": 1, "z": 1}}], "thirdPartyCameras": []}
        self.cameras = []
        self.mutate = mutate
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
        if action == "AddThirdPartyCamera":
            self.cameras.append(copy.deepcopy(kwargs))
        elif action == "UpdateThirdPartyCamera":
            self.cameras[kwargs["thirdPartyCameraId"]] = copy.deepcopy(kwargs)
            if self.mutate:
                self.metadata["objects"][0]["temperature"] = "Hot"
        self.metadata["thirdPartyCameras"] = [{"thirdPartyCameraId": i, **c} for i,c in enumerate(self.cameras)]
        row = {"action": action, "lastActionSuccess": True, "kwargs": kwargs}
        self.records.append(row)
        self.refresh()
        return SimpleNamespace(record=row, metadata=self.snapshot(), event=self.controller.last_event)


class ObserverTests(unittest.TestCase):
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
            report = observer.capture(session.snapshot(), {"Mug": "mug"}, Path(tmp), "changed")
        self.assertTrue(report["world_state_changed"])
        self.assertEqual(report["views"], [])
        self.assertTrue(observer.contaminated)
        self.assertIn("mug", report["changed_objects"])
        self.assertFalse(physics_is_paused(session.records))


if __name__ == "__main__":
    unittest.main()
