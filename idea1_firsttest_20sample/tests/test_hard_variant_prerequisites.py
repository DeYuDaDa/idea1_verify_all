"""Reject private prerequisites that are unrelated to a variant's public story."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hard_scenarios


class PublicStoryBoundary(Exception):
    pass


class HardVariantPrerequisiteTests(unittest.TestCase):
    def test_inside_ending_potato_does_not_require_unused_exterior_route(self):
        for variant in (1, 2, 3, 4):
            with self.subTest(variant=variant):
                ctx = SimpleNamespace(obj=lambda alias: {"isCooked": False, "temperature": "RoomTemp"},
                                      require=lambda ok, msg: self.assertTrue(ok, msg))
                # This test stops at the public-story boundary and verifies only
                # which native routes are calibrated. Checkpoint persistence,
                # snapshots and frame validation have their own tests; they need
                # a full context rather than this deliberately minimal fixture.
                checkpoint_state = {"isCooked": False, "temperature": "RoomTemp",
                                    "location": "cooling_C", "microwave.isToggled": False,
                                    "held_empty": True}
                with patch.object(hard_scenarios, "_prepare_h05_native"), \
                     patch.object(hard_scenarios, "_calibrate_forward") as calibrate, \
                     patch.object(hard_scenarios, "_relation", return_value=True), \
                     patch("hard_checkpoint.ScenarioCheckpointBook") as checkpoint_book, \
                     patch.object(hard_scenarios, "_h05_checkpoint_state", return_value=checkpoint_state), \
                     patch.object(hard_scenarios, "_start", side_effect=PublicStoryBoundary):
                    checkpoint_book.return_value.finish.return_value = {"status": "passed"}
                    with self.assertRaises(PublicStoryBoundary):
                        hard_scenarios._h05(ctx, variant)
                destinations = [call.args[3] for call in calibrate.call_args_list]
                self.assertEqual(destinations, ["Microwave"] + (["final_E"] if variant in (3, 4) else []))
                checkpoint_book.return_value.begin.assert_called_once_with("private_calibration")
                checkpoint_book.return_value.finish.assert_called_once_with([
                    {"name": name, "expected": value, "actual": value}
                    for name, value in checkpoint_state.items()
                ])

    def test_reattachment_story_has_no_private_move_and_restore_cycle(self):
        roles = {"outer": "plate", "inner": "bowl", "content": "apple"}
        def bind(alias, oid):
            roles[alias] = oid
        ctx = SimpleNamespace(roles=roles, waypoints={}, bind=bind,
                              session=SimpleNamespace(scene="FloorPlan1"))
        surfaces = [{"objectId": "support"}, {"objectId": "external"}]
        with patch.object(hard_scenarios, "_surface_candidates", return_value=surfaces), \
             patch("nested_setup.establish_nested"), \
             patch.object(hard_scenarios, "_relation", return_value=True), \
             patch.object(hard_scenarios, "_move") as move, \
             patch.object(hard_scenarios, "_native_setup_place") as restore, \
             patch.object(hard_scenarios, "_start", side_effect=PublicStoryBoundary):
            with self.assertRaises(PublicStoryBoundary):
                hard_scenarios._h04(ctx, 4)
        move.assert_not_called()
        restore.assert_not_called()


if __name__ == "__main__":
    unittest.main()
