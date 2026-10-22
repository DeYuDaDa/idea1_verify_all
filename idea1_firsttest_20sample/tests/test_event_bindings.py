import unittest

from event_bindings import destination_contrast, put_binding


def native_record(*held_ids):
    return {"before_metadata": {"inventoryObjects": [{"objectId": item} for item in held_ids]}}


def native_event(destination, action="PutObject"):
    return {"action": action, "kwargs": {"objectId": destination}}


class EventBindingTests(unittest.TestCase):
    def test_native_put_reads_held_source_from_pre_event_inventory(self):
        self.assertEqual(
            put_binding(native_record("Mug|m"), native_event("CoffeeMachine|coffee")),
            ("Mug|m", "CoffeeMachine|coffee"),
        )

    def test_native_put_reads_nested_agent_inventory(self):
        record = {"before_metadata": {"agent": {"inventoryObjects": [{"objectId": "Mug|m"}]}}}
        self.assertEqual(put_binding(record, native_event("CoffeeMachine|coffee")), ("Mug|m", "CoffeeMachine|coffee"))

    def test_destination_contrast_requires_same_source_and_different_destination(self):
        a = native_record("Mug|m")
        b = native_record("Mug|m")
        self.assertTrue(destination_contrast(a, b, native_event("CoffeeMachine|c"), native_event("CounterTop|t")))
        self.assertFalse(destination_contrast(a, b, native_event("CoffeeMachine|c"), native_event("CoffeeMachine|c")))

    def test_source_change_is_not_a_destination_contrast(self):
        self.assertFalse(destination_contrast(
            native_record("Mug|m1"), native_record("Mug|m2"),
            native_event("CoffeeMachine|c"), native_event("CounterTop|t"),
        ))

    def test_missing_inventory_is_rejected_for_native_event(self):
        self.assertIsNone(put_binding({}, native_event("CoffeeMachine|c")))

    def test_ambiguous_inventory_is_rejected(self):
        self.assertIsNone(put_binding(native_record("Mug|m", "Cup|c"), native_event("CoffeeMachine|x")))

    def test_wrong_action_kind_is_rejected(self):
        self.assertIsNone(put_binding(native_record("Mug|m"), native_event("CoffeeMachine|x", action="ToggleObjectOn")))

    def test_missing_native_destination_is_rejected(self):
        self.assertIsNone(put_binding(native_record("Mug|m"), {"action": "PutObject", "kwargs": {}}))

    def test_legacy_explicit_source_and_destination_are_supported_without_inventory(self):
        event = {"action": "PutObject", "kwargs": {"objectId": "Mug|m", "receptacleObjectId": "CounterTop|t"}}
        self.assertEqual(put_binding({}, event), ("Mug|m", "CounterTop|t"))

    def test_legacy_source_must_match_available_inventory(self):
        event = {"action": "PutObject", "kwargs": {"objectId": "Mug|m", "receptacleObjectId": "CounterTop|t"}}
        self.assertEqual(put_binding(native_record("Mug|m"), event), ("Mug|m", "CounterTop|t"))
        self.assertIsNone(put_binding(native_record("Cup|c"), event))


if __name__ == "__main__":
    unittest.main()
