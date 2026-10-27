import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hard_scene_survey import scene_candidates, survey_scenes


class HardSurveyTests(unittest.TestCase):
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
