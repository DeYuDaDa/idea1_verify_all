"""Small native camera/agent steps for hard-group capture; no image interpolation."""
from __future__ import annotations

from collections import deque
import math

from interactions import Interactions
from runtime import ActionFailure


class NavigationUnavailable(RuntimeError):
    pass


def xyz(row):
    row = row.get("position", row)
    return {k: float(row[k]) for k in ("x", "y", "z")}


def floor_distance(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def focus_position(obj):
    return xyz((obj.get("axisAlignedBoundingBox") or {}).get("center") or obj)


def distance_to_bounds(point, obj):
    box = obj.get("axisAlignedBoundingBox") or {}
    if box.get("center") and box.get("size"):
        center, size = box["center"], box["size"]
        return math.hypot(*(max(0., abs(point[k] - float(center[k])) - float(size[k]) / 2)
                            for k in ("x", "z")))
    return floor_distance(point, focus_position(obj))


def shortest_grid_route(points, start, goal, spacing=0.25, blocked=()):
    """Four-neighbour route on native reachable positions, with no teleport edges."""
    points = [xyz(p) for p in points]
    if not points:
        return None
    key = lambda p: (round(p["x"], 3), round(p["z"], 3))
    nodes = {key(p): p for p in points}
    first = min(nodes, key=lambda k: floor_distance(nodes[k], start))
    last = min(nodes, key=lambda k: floor_distance(nodes[k], goal))
    if floor_distance(nodes[first], start) > spacing * 0.8 or floor_distance(nodes[last], goal) > spacing * 0.8:
        return None
    blocked = {frozenset(edge) for edge in blocked}
    previous = {first: None}
    queue = deque([first])
    while queue:
        current = queue.popleft()
        if current == last:
            path = []
            while current is not None:
                path.append(nodes[current])
                current = previous[current]
            return list(reversed(path))
        for dx, dz in ((spacing, 0), (-spacing, 0), (0, spacing), (0, -spacing)):
            neighbour = (round(current[0] + dx, 3), round(current[1] + dz, 3))
            if (neighbour in nodes and neighbour not in previous
                    and frozenset((current, neighbour)) not in blocked):
                previous[neighbour] = current
                queue.append(neighbour)
    return None


class NativeNavigator:
    def __init__(self, ctx, *, move_step=0.1, angle_step=10.0, look_step=5.0, max_actions=480):
        self.ctx = ctx
        self.session = ctx.session
        self.move_step = move_step
        self.angle_step = angle_step
        self.look_step = look_step
        self.max_actions = max_actions
        self.action_count = 0
        self.last_result = None

    def _step(self, action, **kwargs):
        self.action_count += 1
        if self.action_count > self.max_actions:
            raise NavigationUnavailable("Bounded native navigation action budget exhausted")
        self.last_result = self.session.step(action, raise_on_failure=True, **kwargs)
        if self.last_result.record.get("lastActionSuccess") is not True:
            raise NavigationUnavailable(f"Native navigation success was not confirmed: {action}")
        return self.last_result

    def _agent(self):
        return self.session.snapshot()["agent"]

    def _rotate(self, yaw):
        for _ in range(38):
            current = float(self._agent().get("rotation", {}).get("y", 0))
            delta = (yaw - current + 180) % 360 - 180
            if abs(delta) < 0.15:
                return
            self._step("RotateRight" if delta > 0 else "RotateLeft",
                       degrees=min(self.angle_step, abs(delta)))
        raise NavigationUnavailable("Native rotation did not reach requested yaw")

    def _look(self, horizon):
        horizon = min(60.0, max(-30.0, horizon))
        for _ in range(21):
            delta = horizon - float(self._agent().get("cameraHorizon", 0))
            if abs(delta) < 0.15:
                return
            self._step("LookDown" if delta > 0 else "LookUp",
                       degrees=min(self.look_step, abs(delta)))
        raise NavigationUnavailable("Native look did not reach requested horizon")

    def _walk(self, point):
        for _ in range(10):
            current = xyz(self._agent())
            remaining = floor_distance(current, point)
            if remaining <= 0.025:
                return
            yaw = math.degrees(math.atan2(point["x"] - current["x"], point["z"] - current["z"])) % 360
            self._rotate(yaw)
            self._step("MoveAhead", moveMagnitude=min(self.move_step, remaining))
            actual = xyz(self._agent())
            if floor_distance(current, actual) < 0.005:
                raise NavigationUnavailable("MoveAhead reported no measurable movement")
        raise NavigationUnavailable("Native movement did not reach the next route point")

    def _aim(self, obj):
        current = self.session.snapshot()
        target = (obj.get("axisAlignedBoundingBox") or {}).get("center") or obj["position"]
        camera = current.get("cameraPosition")
        if not camera:
            camera = {**xyz(current["agent"]), "y": float(current["agent"]["position"]["y"]) + 0.675}
        dx, dz = float(target["x"]) - camera["x"], float(target["z"]) - camera["z"]
        self._rotate(math.degrees(math.atan2(dx, dz)) % 360)
        self._look(math.degrees(math.atan2(camera["y"] - float(target["y"]), max(math.hypot(dx, dz), 1e-6))))

    def _visible(self, object_id):
        event = self.session.controller.last_event
        obj = self.ctx.obj(object_id)
        if obj.get("objectType") in {"CounterTop", "DiningTable", "KitchenIsland"}:
            # A large destination surface normally extends past image edges.
            # This is only an approach check, not object identity approval.
            masks = getattr(event, "instance_masks", None)
            if masks is not None:
                mask = masks.get(object_id)
                if mask is not None and getattr(mask, "size", 0):
                    return float(mask.sum()) / float(mask.size) >= 0.001
        # Rendered bbox checks, not only metadata.visible or object distance.
        from runtime import StepResult
        result = StepResult(event, self.session.snapshot(), {})
        return Interactions._rendered_target_bbox(result, object_id) is not None

    def _near(self, obj):
        measured = obj.get("distance")
        if isinstance(measured, (int, float)):
            return float(measured) <= 1.45
        return distance_to_bounds(xyz(self._agent()), obj) <= 1.25

    def navigate(self, object_id, purpose="inspect"):
        self.action_count = 0
        start_index = len(self.session.records)
        diagnostic = {"object_id": object_id, "purpose": purpose, "start_action_index": start_index,
                      "held_before": self.session.inventory(), "method": "native_grid_walk",
                      "move_step_m": self.move_step, "turn_step_degrees": self.angle_step,
                      "synthetic_frames": False, "attempts": []}
        self.ctx.navigation_attempts.append(diagnostic)
        try:
            obj = self.ctx.obj(object_id)
            self._aim(obj)
            if self._near(self.ctx.obj(object_id)) and self._visible(object_id):
                diagnostic["status"] = "already_near_and_visible"
                return self.last_result
            positions_result = self._step("GetReachablePositions")
            positions = positions_result.metadata.get("actionReturn") or []
            poses = []
            try:
                pose_result = self._step("GetInteractablePoses", objectId=object_id)
                poses = pose_result.metadata.get("actionReturn") or []
            except (ActionFailure, ValueError, TypeError) as exc:
                diagnostic["pose_query_error"] = str(exc)
            candidates = []
            for raw in poses or positions:
                point = xyz(raw)
                distance = distance_to_bounds(point, obj)
                if (poses and distance <= 1.5) or (not poses and 0.4 <= distance <= 1.45):
                    candidates.append(point)
            current = xyz(self._agent())
            candidates.sort(key=lambda p: (floor_distance(p, current) + abs(distance_to_bounds(p, obj) - 0.8), p["x"], p["z"]))
            seen = set()
            for point in candidates:
                signature = (round(point["x"], 3), round(point["z"], 3))
                if signature in seen:
                    continue
                seen.add(signature)
                if len(seen) > 8:
                    break
                route = shortest_grid_route(positions, xyz(self._agent()), point)
                attempt = {"destination": point, "route_points": len(route) if route else 0}
                diagnostic["attempts"].append(attempt)
                if not route:
                    attempt["error"] = "No connected native route"
                    continue
                try:
                    for waypoint in route:
                        self._walk(waypoint)
                    self._aim(self.ctx.obj(object_id))
                    if self._near(self.ctx.obj(object_id)) and self._visible(object_id):
                        diagnostic["status"] = "arrived_and_visible"
                        return self.last_result
                    attempt["error"] = "Target absent from rendered first-person view"
                except (ActionFailure, NavigationUnavailable) as exc:
                    attempt["error"] = f"{type(exc).__name__}: {exc}"
            raise NavigationUnavailable(f"Cannot establish a native first-person approach to {object_id}")
        except Exception as exc:
            diagnostic.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            diagnostic["end_action_index"] = len(self.session.records) - 1
            diagnostic["native_actions"] = self.action_count


class HardInteractions(Interactions):
    """Hard-group-only adapter; legacy helper behaviour stays unchanged."""
    def __init__(self, ctx, seed=17):
        super().__init__(ctx.session, seed=seed)
        self.ctx = ctx

    def look(self, object_id):
        return self.ctx.navigate_to(object_id, "inspect_before_interaction")

    def set_open(self, object_id, opened):
        if not getattr(self.ctx, "target_frozen", False):
            self.ctx.navigate_to(object_id, "before_open_close")
        return super().set_open(object_id, opened)

    def set_toggle(self, object_id, on):
        if not getattr(self.ctx, "target_frozen", False):
            self.ctx.navigate_to(object_id, "before_toggle")
        return super().set_toggle(object_id, on)

    def set_liquid(self, object_id, liquid_or_none):
        self.ctx.navigate_to(object_id, "before_liquid_change")
        return super().set_liquid(object_id, liquid_or_none)

