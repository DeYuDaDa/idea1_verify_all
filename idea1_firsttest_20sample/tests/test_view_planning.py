"""Pure-data fixtures for the external camera planner; no simulator involved."""
import unittest

from view_planning import plan_views


def obj(object_id, object_type, position, center=None, size=None):
    result = {"objectId": object_id, "objectType": object_type, "position": position}
    if center is not None:
        result["axisAlignedBoundingBox"] = {"center": center, "size": size or {"x": .4, "y": .4, "z": .4}}
    return result


class ViewPlanningTests(unittest.TestCase):
    def test_coffee_joint_and_detail_exclude_room_noise_and_return_pose_alternatives(self):
        roles = {
            "CoffeeMachine": obj("cm", "CoffeeMachine", {"x": 1, "y": .8, "z": 2}, {"x": 1, "y": .9, "z": 2}, {"x": .6, "y": .8, "z": .5}),
            "Mug": obj("m", "Mug", {"x": 1.25, "y": .8, "z": 2}, {"x": 1.25, "y": .9, "z": 2}, {"x": .15, "y": .2, "z": .15}),
            "Counter": obj("counter", "CounterTop", {"x": 8, "y": .5, "z": 8}, {"x": 8, "y": .5, "z": 8}, {"x": 2, "y": .8, "z": 1}),
            "Fridge": obj("fridge", "Fridge", {"x": -7, "y": 1, "z": 6}, {"x": -7, "y": 1, "z": 6}, {"x": 1, "y": 2, "z": 1}),
        }
        plan = plan_views(roles, device_family="coffee_machine")
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["focus_roles"], ["CoffeeMachine", "Mug"])
        self.assertEqual([g["purpose"] for g in plan["groups"]], ["joint_relation", "device_detail", "contents_detail"])
        candidates = plan["groups"][0]["candidates"]
        self.assertEqual(len(candidates), 4)
        self.assertGreater(len({(c["position"]["x"], c["position"]["y"], c["position"]["z"]) for c in candidates}), 1)
        self.assertGreater(len({c["rotationEuler"]["y"] for c in candidates}), 1)
        self.assertTrue(any(c["rotationEuler"]["x"] > 0 for c in candidates))
        self.assertTrue(all(c["occlusion"] == c["semantic_readability"] == "not_assessed" for c in candidates))
        self.assertTrue(all(c["fov_degrees"] == 60 for c in candidates))

    def test_sink_groups_fixture_contents_and_fixture_detail(self):
        roles = {"Sink": obj("s", "SinkBasin", {"x": 0, "y": .8, "z": 0}, {"x": 0, "y": .8, "z": 0}, {"x": .9, "y": .4, "z": .7}),
                 "Faucet": obj("f", "Faucet", {"x": 0, "y": 1.2, "z": 0}, {"x": 0, "y": 1.2, "z": 0}),
                 "Bowl": obj("b", "Bowl", {"x": .2, "y": .7, "z": 0}, {"x": .2, "y": .7, "z": 0})}
        plan = plan_views(roles, device_family="sink")
        self.assertEqual(plan["focus_roles"], ["Sink", "Faucet", "Bowl"])
        self.assertEqual({g["purpose"] for g in plan["groups"]}, {"joint_relation", "fixture_detail", "contents_detail"})
        self.assertEqual(plan["status"], "planned_with_position_fallbacks")
        self.assertIn("Faucet", plan["groups"][0]["missing_bbox_roles"])

    def test_microwave_contents_and_stove_component_relations(self):
        microwave = {"Microwave": obj("mw", "Microwave", {"x": 2, "y": 1, "z": 3}, {"x": 2, "y": 1, "z": 3}, {"x": .8, "y": 1, "z": .7}),
                     "Potato": obj("food", "Potato", {"x": 2, "y": 1, "z": 3}, {"x": 2, "y": 1, "z": 3}, {"x": .1, "y": .1, "z": .1})}
        mw_plan = plan_views(microwave, device_family="microwave")
        self.assertEqual([g["purpose"] for g in mw_plan["groups"]], ["device_contents_relation", "interior_contents_detail"])
        stove = {"Burner1": obj("b1", "StoveBurner", {"x": 0, "y": .8, "z": 0}, {"x": 0, "y": .8, "z": 0}),
                 "Burner2": obj("b2", "StoveBurner", {"x": .4, "y": .8, "z": 0}, {"x": .4, "y": .8, "z": 0}),
                 "Pot": obj("p", "Pot", {"x": .2, "y": 1, "z": 0}, {"x": .2, "y": 1, "z": 0}),
                 "Knob": obj("k", "StoveKnob", {"x": 0, "y": .9, "z": -.4}, {"x": 0, "y": .9, "z": -.4})}
        stove_plan = plan_views(stove, device_family="stove")
        self.assertEqual(stove_plan["focus_roles"], ["Burner1", "Burner2", "Pot", "Knob"])
        self.assertIn("burners_pots_knob_relation", [g["purpose"] for g in stove_plan["groups"]])
        self.assertIn("control_detail", [g["purpose"] for g in stove_plan["groups"]])

    def test_toaster_and_sliced_bread_have_joint_and_local_views(self):
        roles = {"Toaster": obj("toaster", "Toaster", {"x": 1, "y": .9, "z": 2}, {"x": 1, "y": .9, "z": 2}, {"x": .5, "y": .5, "z": .4}),
                 "Bread": obj("bread", "BreadSliced", {"x": 1.2, "y": .9, "z": 2}, {"x": 1.2, "y": .9, "z": 2}, {"x": .2, "y": .1, "z": .2})}
        plan = plan_views(roles, device_family="toaster")
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["focus_roles"], ["Toaster", "Bread"])
        self.assertEqual([g["purpose"] for g in plan["groups"]], ["device_contents_relation", "toaster_detail", "bread_detail"])

    def test_stove_does_not_drop_kettle_target(self):
        roles = {"Burner": obj("burner", "StoveBurner", {"x": 0, "y": .8, "z": 0}),
                 "Kettle": obj("kettle", "Kettle", {"x": 0, "y": 1, "z": 0})}
        plan = plan_views(roles, device_family="stove")
        self.assertIn("Kettle", plan["focus_roles"])
        self.assertIn("Kettle", next(g for g in plan["groups"] if g["purpose"] == "burner_vessel_detail")["roles"])

    def test_carried_plate_and_nested_container_keep_separate_detail_views(self):
        carry = {"CarryPlate": obj("plate", "Plate", {"x": 0, "y": 1, "z": 0}, {"x": 0, "y": 1, "z": 0}),
                 "Apple": obj("apple", "Apple", {"x": .1, "y": 1.1, "z": 0}, {"x": .1, "y": 1.1, "z": 0})}
        carry_plan = plan_views(carry, device_family="carryplate")
        self.assertEqual([g["purpose"] for g in carry_plan["groups"]], ["carried_relation", "carried_item_detail"])
        nested = {"Outer": obj("outer", "Bowl", {"x": 1, "y": .8, "z": 1}, {"x": 1, "y": .8, "z": 1}),
                  "Inner": obj("inner", "Mug", {"x": 1, "y": .9, "z": 1}, {"x": 1, "y": .9, "z": 1}),
                  "Content": obj("apple", "Apple", {"x": 1, "y": 1, "z": 1}, {"x": 1, "y": 1, "z": 1})}
        nested_plan = plan_views(nested, device_family="nested")
        self.assertEqual(nested_plan["focus_roles"], ["Outer", "Inner", "Content"])
        self.assertEqual([g["purpose"] for g in nested_plan["groups"]], ["nested_relation", "inner_contents_detail"])

    def test_observed_metadata_replans_after_held_object_position_jump(self):
        roles = {"CarryPlate": obj("plate", "Plate", {"x": 0, "y": 1, "z": 0}, {"x": 0, "y": 1, "z": 0}),
                 "Apple": obj("apple", "Apple", {"x": .1, "y": 1, "z": 0}, {"x": .1, "y": 1, "z": 0})}
        before = plan_views(roles, device_family="carryplate")
        observed = {"objects": [obj("apple", "Apple", {"x": 3, "y": 1.4, "z": -1}, {"x": 3, "y": 1.4, "z": -1})]}
        after = plan_views(roles, device_family="carryplate", observed_metadata=observed)
        self.assertIn("Apple", " ".join(after["notes"]))
        self.assertNotEqual(before["groups"][0]["focus"]["point"], after["groups"][0]["focus"]["point"])

    def test_no_roles_missing_geometry_and_oversized_region_are_explicit(self):
        self.assertEqual(plan_views({})["status"], "no_roles")
        no_geometry = plan_views({"Microwave": {"objectType": "Microwave"}}, device_family="microwave")
        self.assertEqual(no_geometry["status"], "no_geometry")
        self.assertEqual(no_geometry["groups"], [])
        far_apart = {"Microwave": obj("mw", "Microwave", {"x": 0, "y": 1, "z": 0}, {"x": 0, "y": 1, "z": 0}),
                     "Potato": obj("food", "Potato", {"x": 9, "y": 1, "z": 0}, {"x": 9, "y": 1, "z": 0})}
        plan = plan_views(far_apart, device_family="microwave")
        self.assertEqual(plan["status"], "oversized_bounds")
        self.assertTrue(any(g["purpose"] == "device_contents_relation" and g["fit_status"] == "not_fit" for g in plan["groups"]))
        self.assertTrue(any(g["purpose"] == "device_local" and g["fit_status"] == "candidate_region" for g in plan["groups"]))


if __name__ == "__main__":
    unittest.main()
