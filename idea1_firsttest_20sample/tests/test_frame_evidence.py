import unittest
from types import SimpleNamespace

from frame_evidence import describe_frame


class FrameEvidenceTests(unittest.TestCase):
    def test_visible_object_and_bbox_do_not_certify_state(self):
        event = SimpleNamespace(frame=SimpleNamespace(shape=(480, 640, 3)),
                                instance_detections2D={"laptop": (200, 200, 300, 300)},
                                instance_masks={})
        metadata = {"lastAction": "BreakObject", "lastActionSuccess": True,
                    "objects": [{"objectId": "laptop", "assetId": "asset1",
                                 "visible": True, "isBroken": True}]}
        result = describe_frame(event, metadata, {"Laptop_1": "laptop"},
                                stage="event_immediate", relative_path="data/media/a.png",
                                png_sha256="a" * 64, capture_action_index=7)
        role = result["roles"]["Laptop_1"]
        self.assertTrue(role["metadata_visible"])
        self.assertIsNotNone(role["camera_sanity_bbox"])
        self.assertEqual(role["state_readability"], "not_assessed")
        self.assertTrue(role["native_state"]["isBroken"])
        self.assertEqual(result["capture_action_index"], 7)

    def test_offscreen_roles_remain_explicit_and_capture_is_read_only(self):
        event = SimpleNamespace(frame=SimpleNamespace(shape=(480, 640, 3)),
                                instance_detections2D={}, instance_masks={})
        metadata = {"objects": [{"objectId": "apple", "visible": False,
                                 "position": {"x": 1, "y": 0, "z": 0}}]}
        result = describe_frame(event, metadata, {"Apple_1": "apple"},
                                stage="before_event", relative_path="data/media/a.png",
                                png_sha256="b" * 64, capture_action_index=0)
        role = result["roles"]["Apple_1"]
        self.assertFalse(role["metadata_visible"])
        self.assertIsNone(role["bbox_xywh"])
        self.assertIsNone(role["mask_pixels"])
        role["native_state"]["position"]["x"] = 999
        self.assertEqual(metadata["objects"][0]["position"]["x"], 1)


if __name__ == "__main__":
    unittest.main()
