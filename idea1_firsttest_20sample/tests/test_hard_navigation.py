import copy
import math
import unittest
from types import SimpleNamespace

from hard_navigation import NativeNavigator, shortest_grid_route
from runtime import StepResult


class NavigationSession:
    def __init__(self):
        self.records = []
        self.metadata = {"agent": {"position": {"x": 0., "y": 0., "z": 0.},
                                  "rotation": {"y": 0.}, "cameraHorizon": 0.},
                         "cameraPosition": {"x": 0., "y": .675, "z": 0.}}
        self.controller = SimpleNamespace(last_event=None)

    def snapshot(self):
        return copy.deepcopy(self.metadata)

    def inventory(self):
        return [{"objectId": "held-apple"}]

    def step(self, action, **kwargs):
        self.records.append({"action": action, "kwargs": kwargs})
        agent = self.metadata["agent"]
        if action.startswith("Rotate"):
            agent["rotation"]["y"] += kwargs["degrees"] * (1 if action == "RotateRight" else -1)
        elif action.startswith("Look"):
            agent["cameraHorizon"] += kwargs["degrees"] * (1 if action == "LookDown" else -1)
        elif action == "MoveAhead":
            yaw = math.radians(agent["rotation"]["y"])
            agent["position"]["x"] += kwargs["moveMagnitude"] * math.sin(yaw)
            agent["position"]["z"] += kwargs["moveMagnitude"] * math.cos(yaw)
        return StepResult(None, self.snapshot(), {"lastActionSuccess": True})


class HardNavigationTests(unittest.TestCase):
    def test_grid_route_avoids_absent_nodes_instead_of_cutting_through_obstacle(self):
        points = [{"x": x, "y": 0., "z": z} for x, z in
                  ((0., 0.), (0., .25), (.25, .25), (.5, .25), (.5, 0.))]
        route = shortest_grid_route(points, points[0], points[-1])
        self.assertEqual(route, points)
        self.assertIsNone(shortest_grid_route([points[0], points[-1]], points[0], points[-1]))

    def test_camera_and_walk_use_small_real_steps_even_with_a_held_object(self):
        session = NavigationSession()
        ctx = SimpleNamespace(session=session, navigation_attempts=[])
        navigator = NativeNavigator(ctx)
        navigator._walk({"x": .25, "y": 0., "z": 0.})
        navigator._look(20.)
        self.assertAlmostEqual(session.metadata["agent"]["position"]["x"], .25)
        self.assertEqual(session.metadata["agent"]["cameraHorizon"], 20.)
        self.assertGreater(len(session.records), 10)
        for row in session.records:
            self.assertNotIn(row["action"], {"Teleport", "TeleportFull", "PlaceObjectAtPoint"})
            if row["action"] == "MoveAhead":
                self.assertLessEqual(row["kwargs"]["moveMagnitude"], .1)
            elif row["action"].startswith("Rotate"):
                self.assertLessEqual(row["kwargs"]["degrees"], 10.)
            elif row["action"].startswith("Look"):
                self.assertLessEqual(row["kwargs"]["degrees"], 5.)


if __name__ == "__main__":
    unittest.main()
