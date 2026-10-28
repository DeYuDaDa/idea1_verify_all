import json
import gzip
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hard_scene_survey import scene_candidates, survey_scenes


class HardSurveyTests(unittest.TestCase):
    def test_native_addition_is_recorded_and_original_inventory_is_preserved(self):
        class Controller:
            def __init__(self, scene, **kwargs):
                self.objects = [{"objectId": "Mug1", "objectType": "Mug", "canFillWithLiquid": True},
                                {"objectId": "Machine", "objectType": "CoffeeMachine"}]
            def snapshot(self):
                return {"objects": list(self.objects)}
            def stop(self):
                pass
        def prepare(session, groups, **kwargs):
            session.objects.append({"objectId": "Mug2-native", "objectType": "Mug", "canFillWithLiquid": True})
            return {"status": "added_and_verified", "action_receipts": [{"action": "CreateObjectAtLocation"}]}
        with tempfile.TemporaryDirectory() as temp, \
             patch("hard_scene_survey.ControllerSession", Controller), \
             patch("hard_scene_survey.ensure_native_inventory", side_effect=prepare) as native:
            root = Path(temp)
            result = survey_scenes([SimpleNamespace(group_id="H01", scene="FloorPlan1")], root, {}, {}, scene_limit=1)
            self.assertEqual(result["assignments"], {"H01": "FloorPlan1"})
            self.assertEqual(native.call_count, 1)
            row = result["scenes"][0]
            with gzip.open(root / row["metadata_path"], "rt") as stream:
                original = json.load(stream)
            with gzip.open(root / row["prepared_metadata_path"], "rt") as stream:
                prepared = json.load(stream)
            self.assertEqual(sum(o["objectType"] == "Mug" for o in original["objects"]), 1)
            self.assertEqual(sum(o["objectType"] == "Mug" for o in prepared["objects"]), 2)

    def test_scan_order_is_bounded_and_preserves_preferred_scene(self):
        case = SimpleNamespace(group_id="H01", scene="FloorPlan2")
        scenes = scene_candidates([case], 3)
        self.assertEqual(scenes, ["FloorPlan2", "FloorPlan1", "FloorPlan3"])

    def test_inventory_assignment_uses_native_counts_instead_of_synthesizing_a_second_mug(self):
        class Controller:
            def __init__(self, scene, **kwargs):
                self.scene = scene
            def reset(self, scene):
                self.scene = scene
            def snapshot(self):
                count = 1 if self.scene == "FloorPlan1" else 2
                return {"objects": [{"objectId": f"Mug{i}", "objectType": "Mug", "canFillWithLiquid": True}
                                    for i in range(count)] +
                                   [{"objectId": "Machine", "objectType": "CoffeeMachine"}]}
            def stop(self):
                pass
        with tempfile.TemporaryDirectory() as temp, patch("hard_scene_survey.ControllerSession", Controller):
            result = survey_scenes([SimpleNamespace(group_id="H01", scene="FloorPlan1")],
                                   Path(temp), {}, {}, scene_limit=2)
            self.assertEqual(result["assignments"], {"H01": "FloorPlan2"})
            self.assertFalse(result["scenes"][0]["checks"]["H01"]["satisfied"])
            self.assertTrue((Path(temp) / "inventory_survey/FloorPlan1.json.gz").exists())
            self.assertEqual(json.loads((Path(temp) / "inventory_survey.json").read_text())["unassigned_groups"], [])


if __name__ == "__main__":
    unittest.main()
