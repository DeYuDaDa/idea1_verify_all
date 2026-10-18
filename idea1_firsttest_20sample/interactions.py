"""Auditable, metadata-checked AI2-THOR interaction helpers.

This module is intentionally thin: all simulator operations go through the
provided ControllerSession.step ledger, and a failed native action is never
reported as a successful helper result.
"""
from __future__ import annotations

import copy
from collections import Counter
import time
from typing import Any

from runtime import ActionFailure, ControllerSession, StepResult


class Interactions:
    def __init__(self, session: ControllerSession, seed: int = 17):
        self.session = session
        self.seed = int(seed)

    def _step(self, action: str, **kwargs: Any) -> StepResult:
        result = self.session.step(action, raise_on_failure=True, **kwargs)
        # Some Controller.step errors are raised by runtime; also reject absent
        # success flags, since they cannot establish that a desired state held.
        if result.record.get("lastActionSuccess") is not True:
            raise ActionFailure(result)
        return result

    def obj(self, object_id: str) -> dict[str, Any]:
        for item in self.session.snapshot().get("objects", []):
            if item.get("objectId") == object_id:
                return copy.deepcopy(item)
        raise LookupError(f"No object with objectId {object_id!r}")

    def find(self, object_type: str, optional: bool = False) -> dict[str, Any] | None:
        item = self.session.find_object(object_type)
        if item is None and not optional:
            raise LookupError(f"No object of type {object_type!r}")
        return item

    def _require_capability(self, object_id: str, capability: str) -> dict[str, Any]:
        obj = self.obj(object_id)
        if obj.get(capability) is not True:
            raise ValueError(f"{object_id!r} does not report {capability}=True")
        return obj

    def _noop(self, note: str) -> StepResult:
        """Return a genuine Pass event and explicitly annotate why setup skipped."""
        result = self._step("Pass")
        result.record["setup_noopnote"] = note
        if self.session.records:
            self.session.records[-1]["setup_noopnote"] = note
        return result

    def set_toggle(self, object_id: str, on: bool) -> StepResult:
        obj = self._require_capability(object_id, "toggleable")
        if obj.get("isToggled") is on:
            return self._noop(f"setup skipped: isToggled already {on}")
        result = self._step("ToggleObjectOn" if on else "ToggleObjectOff", objectId=object_id, forceAction=True)
        if self.obj(object_id).get("isToggled") is not on:
            raise RuntimeError(f"Toggle action succeeded but isToggled did not become {on}")
        return result

    def set_open(self, object_id: str, opened: bool) -> StepResult:
        obj = self._require_capability(object_id, "openable")
        if obj.get("isOpen") is opened:
            return self._noop(f"setup skipped: isOpen already {opened}")
        result = self._step("OpenObject" if opened else "CloseObject", objectId=object_id, forceAction=True)
        if self.obj(object_id).get("isOpen") is not opened:
            raise RuntimeError(f"Open/close action succeeded but isOpen did not become {opened}")
        return result

    def set_dirty(self, object_id: str, dirty: bool) -> StepResult:
        obj = self._require_capability(object_id, "dirtyable")
        if obj.get("isDirty") is dirty:
            return self._noop(f"setup skipped: isDirty already {dirty}")
        result = self._step("DirtyObject" if dirty else "CleanObject", objectId=object_id, forceAction=True)
        if self.obj(object_id).get("isDirty") is not dirty:
            raise RuntimeError(f"Dirty/clean action succeeded but isDirty did not become {dirty}")
        return result

    def set_cooked(self, object_id: str, cooked: bool = True) -> StepResult:
        obj = self._require_capability(object_id, "cookable")
        if cooked is not True:
            raise NotImplementedError("AI2-THOR has CookObject but no native uncook action")
        if obj.get("isCooked") is True:
            return self._noop("setup skipped: isCooked already True")
        result = self._step("CookObject", objectId=object_id, forceAction=True)
        if self.obj(object_id).get("isCooked") is not True:
            raise RuntimeError("CookObject succeeded but metadata does not confirm isCooked=True")
        return result

    def set_liquid(self, object_id: str, liquid_or_none: str | None) -> StepResult:
        obj = self._require_capability(object_id, "canFillWithLiquid")
        if liquid_or_none is None:
            if obj.get("isFilledWithLiquid") is False:
                if obj.get("fillLiquid") not in (None, ""):
                    raise RuntimeError("Metadata reports unfilled but contains a liquid value")
                return self._noop("setup skipped: isFilledWithLiquid already False")
            result = self._step("EmptyLiquidFromObject", objectId=object_id, forceAction=True)
        else:
            if liquid_or_none not in {"coffee", "wine", "water"}:
                raise ValueError("fill liquid must be one of: coffee, wine, water")
            if obj.get("isFilledWithLiquid") is True and str(obj.get("fillLiquid") or "").lower() == liquid_or_none:
                return self._noop(f"setup skipped: already filled with {liquid_or_none}")
            result = self._step("FillObjectWithLiquid", objectId=object_id, fillLiquid=liquid_or_none, forceAction=True)
        after = self.obj(object_id)
        expected_filled = liquid_or_none is not None
        if after.get("isFilledWithLiquid") is not expected_filled:
            raise RuntimeError("Liquid action succeeded but metadata does not match requested liquid state")
        if expected_filled and str(after.get("fillLiquid") or "").lower() != liquid_or_none:
            raise RuntimeError("Liquid action succeeded but metadata reports a different fill liquid")
        if not expected_filled and after.get("fillLiquid") not in (None, ""):
            raise RuntimeError("Liquid action reports an unfilled object with a nonempty liquid")
        return result

    def room_temperature(self, object_id: str, *, timeout_seconds: float = 15.0,
                         poll_seconds: float = 0.5) -> list[StepResult]:
        """Wait for natural temperature decay; there is no direct temperature setter."""
        if timeout_seconds < 0 or poll_seconds <= 0:
            raise ValueError("timeout_seconds must be >= 0 and poll_seconds > 0")
        steps: list[StepResult] = []
        deadline = time.monotonic() + timeout_seconds
        while True:
            if self.obj(object_id).get("ObjectTemperature") == "RoomTemp":
                return steps
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{object_id!r} did not naturally decay to RoomTemp")
            # Pass has no documented duration argument in iTHOR; simulator
            # time advances through native action execution.
            steps.append(self._step("Pass"))
            time.sleep(min(poll_seconds, max(0.0, deadline-time.monotonic())))

    @staticmethod
    def _unique_spawn_points(points: list[dict[str, Any]]) -> list[dict[str, float]]:
        """Normalize coordinates and remove exact-to-millimeter duplicates."""
        unique: list[dict[str, float]] = []
        seen: set[tuple[float, float, float]] = set()
        for point in points:
            try:
                xyz = tuple(float(point[key]) for key in ("x", "y", "z"))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Malformed spawn coordinate: {point!r}") from exc
            # The simulator may report identical positions more than once.
            key = tuple(round(value, 3) for value in xyz)
            if key in seen:
                continue
            seen.add(key)
            unique.append({"x": xyz[0], "y": xyz[1], "z": xyz[2]})
        return unique

    @staticmethod
    def _spawn_candidates(points: list[dict[str, float]], limit: int) -> list[dict[str, float]]:
        """Choose a deterministic, spatially spread subset using farthest-point sampling."""
        if limit < 1:
            raise ValueError("max_candidates must be positive")
        unique = list(points)
        if len(unique) <= limit:
            return unique

        # Start from the coordinate nearest the centroid, then repeatedly add
        # the point farthest from the selected set. Original order breaks ties.
        centroid = tuple(sum(p[axis] for p in unique) / len(unique) for axis in ("x", "y", "z"))
        first = min(
            range(len(unique)),
            key=lambda i: (sum((unique[i][axis] - centroid[n]) ** 2 for n, axis in enumerate(("x", "y", "z"))), i),
        )
        selected = [first]
        min_distance_sq = [
            sum((point[axis] - unique[first][axis]) ** 2 for axis in ("x", "y", "z"))
            for point in unique
        ]
        min_distance_sq[first] = -1.0
        while len(selected) < limit:
            nxt = max(range(len(unique)), key=lambda i: (min_distance_sq[i], -i))
            selected.append(nxt)
            center = unique[nxt]
            for i, point in enumerate(unique):
                if min_distance_sq[i] < 0:
                    continue
                distance_sq = sum((point[axis] - center[axis]) ** 2 for axis in ("x", "y", "z"))
                min_distance_sq[i] = min(min_distance_sq[i], distance_sq)
            min_distance_sq[nxt] = -1.0
        return [unique[i] for i in selected]

    def place_initial(self, object_id: str, receptacle_id: str, *, max_candidates: int = 16) -> list[StepResult]:
        """Place setup object at a bounded, spatially spread set of native spawn points."""
        if self.session.inventory():
            raise RuntimeError("place_initial requires an empty agent inventory")
        self._require_capability(object_id, "pickupable")
        self._require_capability(receptacle_id, "receptacle")
        spawn = self._step("GetSpawnCoordinatesAboveReceptacle", objectId=receptacle_id)
        all_points = spawn.metadata.get("actionReturn") or []
        if not all_points:
            raise RuntimeError(f"No valid spawn coordinates above {receptacle_id!r}")
        available_points = self._unique_spawn_points(all_points)
        points = self._spawn_candidates(available_points, max_candidates)
        failures: Counter[str] = Counter()
        examples: dict[str, str] = {}
        action_results: list[StepResult] = [spawn]
        for point in points:
            try:
                placed = self._step("PlaceObjectAtPoint", objectId=object_id, position=point)
            except ActionFailure as exc:
                message = " ".join(str(exc).split()) or type(exc).__name__
                failures[message] += 1
                examples.setdefault(message, repr(point))
                continue
            action_results.append(placed)
            action_results.extend(self.settle(steps=2))
            parent_ids = self.obj(object_id).get("parentReceptacles") or []
            children = self.obj(receptacle_id).get("receptacleObjectIds") or []
            if receptacle_id in parent_ids or object_id in children:
                return action_results
            message = "placement action succeeded but metadata relation was absent after settling"
            failures[message] += 1
            examples.setdefault(message, repr(point))
        detail = "; ".join(
            f"{count}x {message[:180]} (example point {examples[message]})"
            for message, count in failures.most_common(4)
        ) or "no placement candidates were attempted"
        omitted = len(failures) - 4
        if omitted > 0:
            detail += f"; {omitted} additional distinct error types omitted"
        budget_exhausted = len(points) < len(available_points)
        raise RuntimeError(
            f"Setup placement did not establish a metadata containment relation on {receptacle_id!r}: "
            f"tested {len(points)} of {len(available_points)} unique available spawn candidates "
            f"(max_candidates={max_candidates}, budget_exhausted={budget_exhausted}); {detail}"
        )

    def pickup_event(self, object_id: str, *, look_first: bool = True) -> StepResult:
        self._require_capability(object_id, "pickupable")
        if any(item.get("objectId") == object_id for item in self.session.inventory()):
            return self._noop("setup skipped: target already held")
        if look_first:
            self.look(object_id)
        result = self._step("PickupObject", objectId=object_id, forceAction=True)
        if not any(item.get("objectId") == object_id for item in self.session.inventory()):
            raise RuntimeError("PickupObject succeeded but inventory does not contain target")
        return result

    def put_event(self, object_id: str, receptacle_id: str) -> StepResult:
        """Evaluated PutObject only; caller must have completed pickup in setup."""
        self._require_capability(receptacle_id, "receptacle")
        if not any(item.get("objectId") == object_id for item in self.session.inventory()):
            raise RuntimeError("put_event requires the target already held; setup PickupObject before the event freeze")
        result = self._step("PutObject", objectId=receptacle_id, forceAction=True,
                            placeStationary=True, randomSeed=self.seed)
        child = self.obj(object_id)
        parent_ids = child.get("parentReceptacles") or []
        # Some scenes expose direct containment via child ids, some report the
        # receptacle only for contained objects; accept either native relation.
        if receptacle_id not in parent_ids and object_id not in (self.obj(receptacle_id).get("receptacleObjectIds") or []):
            raise RuntimeError(f"PutObject succeeded but {object_id!r} is not related to {receptacle_id!r} in metadata")
        return result

    def slice_object(self, object_id: str) -> list[str]:
        before = {item.get("objectId") for item in self.session.snapshot().get("objects", [])}
        source = self._require_capability(object_id, "sliceable")
        source_type = source.get("objectType")
        if source.get("isSliced") is True:
            self._noop("setup skipped: source already reports isSliced=True")
            return []
        self._step("SliceObject", objectId=object_id, forceAction=True)
        after = self.session.snapshot().get("objects", [])
        sliced_type = f"{source_type}Sliced"
        new_ids = [item["objectId"] for item in after if item.get("objectType") == sliced_type and item.get("objectId") not in before]
        remains = next((item for item in after if item.get("objectId") == object_id), None)
        if not new_ids and not (remains and remains.get("isSliced") is True):
            raise RuntimeError("SliceObject succeeded but neither isSliced nor new sliced IDs are reported")
        return new_ids

    def settle(self, steps: int = 5) -> list[StepResult]:
        if steps < 0:
            raise ValueError("steps must be non-negative")
        return [self._step("Pass") for _ in range(steps)]

    def look(self, object_id: str) -> StepResult:
        """Move camera to a native interactable pose; fall back to facing target."""
        if self.session.inventory():
            return self._noop("look skipped: camera teleport while holding can displace/reset held object")
        obj = self.obj(object_id)
        try:
            poses_result = self._step("GetInteractablePoses", objectId=object_id)
            poses = poses_result.metadata.get("actionReturn") or []
            if poses:
                pose = {key: poses[0][key] for key in ("x", "y", "z", "rotation", "horizon", "standing")
                        if key in poses[0]}
                return self._step("TeleportFull", **pose)
        except (ActionFailure, ValueError, TypeError):
            pass
        return self.session.face_object(obj)


__all__ = ["Interactions"]
