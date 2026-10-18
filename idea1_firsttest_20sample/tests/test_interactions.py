import unittest

from interactions import Interactions
from runtime import ActionFailure, StepResult


class FakeSession:
    """Small ledger-only stand-in; these tests never start AI2-THOR."""

    def __init__(self, points):
        self.points = points
        self.records = []
        self._metadata = {
            "objects": [
                {"objectId": "Apple|1", "objectType": "Apple", "pickupable": True,
                 "parentReceptacles": []},
                {"objectId": "CounterTop|1", "objectType": "CounterTop", "receptacle": True,
                 "receptacleObjectIds": []},
            ],
            "agent": {"inventoryObjects": []},
        }
        self.place_calls = 0

    def snapshot(self, result=None):
        return dict(self._metadata)

    def inventory(self):
        return []

    def step(self, action, *, raise_on_failure=False, **kwargs):
        self.records.append({"action": action, "kwargs": kwargs})
        metadata = {"lastActionSuccess": True, "errorMessage": "", "actionReturn": None}
        if action == "GetSpawnCoordinatesAboveReceptacle":
            metadata["actionReturn"] = self.points
        elif action == "PlaceObjectAtPoint":
            self.place_calls += 1
            metadata.update(lastActionSuccess=False, errorMessage="Spawn area not clear")
        event = object()
        record = {"action": action, "kwargs": kwargs,
                  "lastActionSuccess": metadata["lastActionSuccess"],
                  "errorMessage": metadata["errorMessage"]}
        result = StepResult(event=event, metadata=metadata, record=record)
        if raise_on_failure and not metadata["lastActionSuccess"]:
            raise ActionFailure(result)
        return result


class InteractionsSpawnTests(unittest.TestCase):
    def test_spawn_subset_is_bounded_spread_and_deterministic(self):
        points = [{"x": float(index), "y": 0.0, "z": float(index % 3)} for index in range(100)]
        first = Interactions._spawn_candidates(points, 8)
        second = Interactions._spawn_candidates(points, 8)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)
        self.assertLessEqual(min(point["x"] for point in first), 10.0)
        self.assertGreaterEqual(max(point["x"] for point in first), 90.0)

    def test_place_initial_stops_at_budget_and_keeps_each_native_failure(self):
        points = [{"x": float(index), "y": 1.0, "z": 0.0} for index in range(80)]
        session = FakeSession(points)
        interactions = Interactions(session)
        with self.assertRaisesRegex(RuntimeError, r"tested 7 of 80.*budget_exhausted=True"):
            interactions.place_initial("Apple|1", "CounterTop|1", max_candidates=7)
        self.assertEqual(session.place_calls, 7)
        self.assertEqual(sum(record["action"] == "PlaceObjectAtPoint" for record in session.records), 7)
        self.assertEqual(sum(record["action"] == "GetSpawnCoordinatesAboveReceptacle" for record in session.records), 1)

    def test_spawn_coordinates_are_deduplicated_before_budget_report(self):
        points = [{"x": 0.0, "y": 1.0, "z": 0.0}, {"x": 0.0001, "y": 1.0, "z": 0.0}]
        session = FakeSession(points)
        with self.assertRaisesRegex(RuntimeError, r"tested 1 of 1 unique available.*budget_exhausted=False"):
            Interactions(session).place_initial("Apple|1", "CounterTop|1", max_candidates=5)
        self.assertEqual(session.place_calls, 1)

    def test_nonpositive_candidate_budget_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "max_candidates must be positive"):
            Interactions._spawn_candidates([{"x": 0, "y": 0, "z": 0}], 0)


if __name__ == "__main__":
    unittest.main()
