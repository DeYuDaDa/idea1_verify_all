import math
import unittest
from collections.abc import Mapping

from interactions import Interactions
from runtime import ControllerSession, StepResult


class CameraGeometryTests(unittest.TestCase):
    def session(self, metadata, points):
        session = ControllerSession.__new__(ControllerSession)
        session.snapshot = lambda result=None: metadata
        session.reachable_positions = lambda **kwargs: points
        session.safe_teleport = lambda point, **kwargs: StepResult(
            event=None, metadata={}, record={"point": dict(point), **kwargs}
        )
        return session

    def test_uses_live_camera_offset_and_bounds_center(self):
        metadata = {
            "cameraPosition": {"x": 0, "y": 0.901, "z": 0},
            "agent": {"position": {"x": 0, "y": 0.901, "z": 0}},
        }
        point = {"x": 0.0, "y": 0.901, "z": 0.0}
        obj = {
            "position": {"x": 1.0, "y": 0.0, "z": 0.0},
            "axisAlignedBoundingBox": {"center": {"x": 1.0, "y": 1.3, "z": 0.0}},
        }
        result = self.session(metadata, [point]).face_object(obj, min_distance=0.6, max_distance=1.2)
        self.assertAlmostEqual(result.record["rotation_y"], 90.0)
        expected = math.degrees(math.atan2(0.901 - 1.3, 1.0))
        self.assertAlmostEqual(result.record["horizon"], expected)

    def test_fallback_offset_only_when_camera_metadata_missing(self):
        metadata = {"agent": {"position": {"x": 0, "y": 0.9, "z": 0}}}
        point = {"x": 0.0, "y": 0.9, "z": 0.0}
        obj = {"position": {"x": 0.0, "y": 0.9, "z": 1.0}}
        result = self.session(metadata, [point]).face_object(obj, min_distance=0.5, max_distance=1.5)
        expected = math.degrees(math.atan2(0.9 + 0.675 - 0.9, 1.0))
        self.assertAlmostEqual(result.record["horizon"], expected)

    def test_rendered_bbox_must_have_area_and_clear_image_edges(self):
        class Frame:
            shape = (240, 320, 3)

        class Event:
            frame = Frame()
            instance_detections2D = {
                "center": {"x": 90, "y": 70, "width": 80, "height": 60},
                "edge": {"x": 0, "y": 70, "width": 80, "height": 60},
                "tiny": {"x": 90, "y": 70, "width": 2, "height": 2},
            }

        for object_id, expected in (("center", True), ("edge", False), ("tiny", False)):
            result = StepResult(event=Event(), metadata={}, record={})
            self.assertEqual(Interactions._rendered_target_bbox(result, object_id) is not None, expected)

    def test_look_deduplicates_nested_positions_and_ignores_visible_metadata(self):
        class Frame:
            shape = (240, 320, 3)

        class Event:
            frame = Frame()
            instance_masks = {}

            def __init__(self, detected):
                self.instance_detections2D = ({"Target|1": {
                    "x": 80, "y": 60, "width": 100, "height": 80
                }} if detected else {})

        class FakeSession:
            def __init__(self):
                self.records = []
                self.positions = []

            def inventory(self):
                return []

            def snapshot(self):
                return {"objects": [{"objectId": "Target|1", "objectType": "Laptop",
                                     "visible": True}]}

            def step(self, action, **kwargs):
                poses = [
                    {"position": {"x": 1, "y": 0.9, "z": 0}, "rotation": 0},
                    {"position": {"x": 1.0001, "y": 0.9, "z": 0}, "rotation": 90},
                    {"position": {"x": 2, "y": 0.9, "z": 0}, "rotation": 180},
                ]
                record = {"action": action, "lastActionSuccess": True}
                self.records.append(record)
                return StepResult(Event(False), {"actionReturn": poses}, record)

            def face_object(self, obj, *, position=None):
                self.positions.append(position)
                detected = position is not None and position["x"] == 2.0
                record = {"action": "TeleportFull", "lastActionSuccess": True}
                self.records.append(record)
                return StepResult(Event(detected), {"objects": [{"objectId": "Target|1",
                                     "visible": True}]}, record)

        session = FakeSession()
        result = Interactions(session).look("Target|1")
        self.assertEqual(len(session.positions), 2)  # duplicate XYZ pose was removed
        self.assertEqual(session.positions[-1]["x"], 2.0)
        self.assertEqual(result.record["look_pose_candidate"], 2)

        class InvisibleSession(FakeSession):
            def face_object(self, obj, *, position=None):
                self.positions.append(position)
                record = {"action": "TeleportFull", "lastActionSuccess": True}
                self.records.append(record)
                return StepResult(Event(False), {"objects": [{"objectId": "Target|1",
                                     "visible": True}]}, record)

        with self.assertRaisesRegex(RuntimeError, "rendered view"):
            Interactions(InvisibleSession()).look("Target|1")

    def test_rendered_mask_bbox_can_validate_look(self):
        class Axis:
            def __init__(self, values):
                self.values = values

            def __len__(self):
                return len(self.values)

            def min(self):
                return min(self.values)

            def max(self):
                return max(self.values)

        class Mask:
            ndim = 2
            shape = (240, 320)

            def nonzero(self):
                return Axis([60, 130]), Axis([70, 150])

        class Frame:
            shape = (240, 320, 3)

        class Event:
            frame = Frame()
            instance_detections2D = {}
            instance_masks = {"Target|1": Mask()}

        class FakeSession:
            records = []

            def inventory(self):
                return []

            def snapshot(self):
                return {"objects": [{"objectId": "Target|1", "visible": False}]}

            def step(self, action, **kwargs):
                record = {"action": action, "lastActionSuccess": True}
                self.records.append(record)
                return StepResult(Event(), {"actionReturn": []}, record)

            def face_object(self, obj, *, position=None):
                record = {"action": "TeleportFull", "lastActionSuccess": True}
                self.records.append(record)
                return StepResult(Event(), {}, record)

        result = Interactions(FakeSession()).look("Target|1")
        self.assertEqual(result.record["look_pose_candidate"], "geometric")

    def test_lazy_mapping_and_array_like_detection_bbox(self):
        class LazyMap(Mapping):
            def __init__(self, values):
                self.values = values

            def __getitem__(self, key):
                return self.values[key]

            def __iter__(self):
                return iter(self.values)

            def __len__(self):
                return len(self.values)

        class ArrayLike:
            def __init__(self, values):
                self.values = values

            def __len__(self):
                return len(self.values)

            def __getitem__(self, index):
                return self.values[index]

        class Frame:
            shape = (240, 320, 3)

        class DetectionEvent:
            frame = Frame()
            instance_detections2D = LazyMap({"Target|1": ArrayLike((40, 50, 120, 110))})
            instance_masks = LazyMap({})

        result = StepResult(event=DetectionEvent(), metadata={}, record={})
        bbox = Interactions._rendered_target_bbox(result, "Target|1")
        self.assertEqual(bbox, {"x": 40.0, "y": 50.0, "width": 81.0, "height": 61.0})

    def test_lazy_mapping_instance_masks_are_read_without_metadata_visible(self):
        class LazyMap(Mapping):
            def __init__(self, values):
                self.values = values

            def __getitem__(self, key):
                return self.values[key]

            def __iter__(self):
                return iter(self.values)

            def __len__(self):
                return len(self.values)

        class Axis:
            def __init__(self, values):
                self.values = values

            def __len__(self):
                return len(self.values)

            def min(self):
                return min(self.values)

            def max(self):
                return max(self.values)

        class Mask:
            ndim = 2
            shape = (240, 320)

            def nonzero(self):
                return Axis([60, 130]), Axis([70, 150])

        class Frame:
            shape = (240, 320, 3)

        class Event:
            frame = Frame()
            instance_detections2D = LazyMap({})
            instance_masks = LazyMap({"Target|1": Mask()})

        result = StepResult(event=Event(), metadata={"visible": True}, record={})
        self.assertEqual(
            Interactions._rendered_target_bbox(result, "Target|1"),
            {"x": 70.0, "y": 60.0, "width": 81.0, "height": 71.0},
        )


if __name__ == "__main__":
    unittest.main()
