"""Thin, auditable runtime wrapper for AI2-THOR 5.0.0 on Linux."""
from __future__ import annotations

import copy
import importlib.metadata
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass
class StepResult:
    """One simulator response plus its immutable-by-convention metadata snapshot."""

    event: Any
    metadata: dict[str, Any]
    record: dict[str, Any]


@dataclass
class ActionFailure(RuntimeError):
    """Raised after a failed action when ``raise_on_failure=True``."""

    result: StepResult

    def __str__(self) -> str:
        return str(self.result.record.get("errorMessage") or "AI2-THOR action failed")


class ControllerSession:
    """Own an AI2-THOR controller and keep a per-step action ledger.

    Parameters are documented in ``runtime接口说明.md``. No simulator is started
    at import time; construction starts one controller and captures its initial
    Initialize response.
    """

    def __init__(
        self,
        *,
        scene: str = "FloorPlan1",
        platform: str = "Linux64",
        width: int = 640,
        height: int = 480,
        field_of_view: float = 75,
        quality: str = "Low",
        render_depth: bool = False,
        render_instance_segmentation: bool = True,
        build_cache_dir: str | Path | None = None,
        local_executable_path: str | Path | None = None,
        commit_id: str | None = None,
        strict_version: bool = True,
        controller_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        if platform not in {"Linux64", "CloudRendering"}:
            raise ValueError("platform must be 'Linux64' or 'CloudRendering' on this runtime")
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        try:
            installed_version = importlib.metadata.version("ai2thor")
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError("Install ai2thor==5.0.0 in the active environment first") from exc
        if strict_version and installed_version != "5.0.0":
            raise RuntimeError(
                f"Expected ai2thor==5.0.0, found {installed_version!r}; "
                "pass strict_version=False only for an intentional compatibility run"
            )

        from ai2thor.controller import Controller
        from ai2thor.platform import CloudRendering, Linux64

        platform_class = {"Linux64": Linux64, "CloudRendering": CloudRendering}[platform]
        options: dict[str, Any] = dict(
            scene=scene,
            platform=platform_class,
            width=width,
            height=height,
            fieldOfView=field_of_view,
            quality=quality,
            renderDepthImage=render_depth,
            renderInstanceSegmentation=render_instance_segmentation,
            # Keep False for image-bearing events. Controller(headless=True) sets
            # renderImage=False and would suppress the RGB frame.
            headless=False,
        )
        if commit_id is not None:
            options["commit_id"] = commit_id
        if local_executable_path is not None:
            options["local_executable_path"] = str(Path(local_executable_path).expanduser().resolve())
        if controller_kwargs:
            forbidden = set(options).intersection(controller_kwargs)
            if forbidden:
                raise ValueError(f"controller_kwargs cannot override managed settings: {sorted(forbidden)}")
            options.update(controller_kwargs)

        controller_type = Controller
        if build_cache_dir is not None:
            # AI2-THOR derives releases_dir, cache_dir, logs, etc. from this
            # property. Subclassing keeps the override scoped to this controller
            # instead of changing the process-wide HOME environment variable.
            cache_root = Path(build_cache_dir).expanduser().resolve()
            cache_root.mkdir(parents=True, exist_ok=True)

            class _CachedController(Controller):
                @property
                def base_dir(self) -> str:
                    return str(cache_root)

            controller_type = _CachedController

        self.controller = controller_type(**options)
        self.scene = scene
        self.platform = platform
        self.width = width
        self.height = height
        self.field_of_view = field_of_view
        self.quality = quality
        self.render_depth = render_depth
        self.render_instance_segmentation = render_instance_segmentation
        self.installed_version = installed_version
        self.records: list[dict[str, Any]] = []
        self._record_initialization()

    def _record_initialization(self) -> None:
        event = self.controller.last_event
        metadata = copy.deepcopy(event.metadata)
        self.records.append(
            {
                "index": 0,
                "time_utc": datetime.now(timezone.utc).isoformat(),
                "action": "Initialize",
                "kwargs": {
                    "scene": self.scene,
                    "platform": self.platform,
                    "width": self.width,
                    "height": self.height,
                    "fieldOfView": self.field_of_view,
                    "quality": self.quality,
                    "renderDepthImage": self.render_depth,
                    "renderInstanceSegmentation": self.render_instance_segmentation,
                },
                "lastActionSuccess": metadata.get("lastActionSuccess"),
                "errorMessage": metadata.get("errorMessage", ""),
                "sceneName": metadata.get("sceneName"),
            }
        )

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Mapping):
            return {str(k): ControllerSession._jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [ControllerSession._jsonable(v) for v in value]
        if hasattr(value, "tolist"):
            return ControllerSession._jsonable(value.tolist())
        return repr(value)

    def step(self, action: str, *, raise_on_failure: bool = False, **kwargs: Any) -> StepResult:
        """Execute one action, ledger exact parameters and outcome, optionally raise."""
        event = None
        call_error: Exception | None = None
        try:
            event = self.controller.step(action=action, **kwargs)
        except Exception as exc:
            # Controller.step can raise after receiving a failed Unity response
            # (for example InvalidAction). Preserve that response before
            # propagating the failure to the caller.
            call_error = exc
            event = getattr(self.controller, "last_event", None)
        metadata = copy.deepcopy(event.metadata) if event is not None else {}
        error_message = metadata.get("errorMessage", "")
        if call_error is not None and not error_message:
            error_message = f"{type(call_error).__name__}: {call_error}"
        record = {
            "index": len(self.records),
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "kwargs": self._jsonable(kwargs),
            "lastActionSuccess": metadata.get("lastActionSuccess"),
            "errorMessage": error_message,
            "sceneName": metadata.get("sceneName"),
        }
        self.records.append(record)
        result = StepResult(event=event, metadata=metadata, record=copy.deepcopy(record))
        if call_error is not None or (raise_on_failure and metadata.get("lastActionSuccess") is False):
            raise ActionFailure(result)
        return result

    def snapshot(self, result: StepResult | None = None) -> dict[str, Any]:
        """Return a deep-copied metadata snapshot for before/after comparisons."""
        if result is not None:
            return copy.deepcopy(result.metadata)
        return copy.deepcopy(self.controller.last_event.metadata)

    @property
    def current_scene(self) -> str | None:
        return self.snapshot().get("sceneName")

    def inventory(self) -> list[dict[str, Any]]:
        """Return the current agent inventory, when present in metadata."""
        metadata = self.snapshot()
        return copy.deepcopy(metadata.get("inventoryObjects", metadata.get("agent", {}).get("inventoryObjects", [])))

    def reset(self, scene: str) -> StepResult:
        """Reset the real simulator; caller owns any previous case's snapshots."""
        event = self.controller.reset(
            scene=scene, renderDepthImage=self.render_depth,
            renderInstanceSegmentation=self.render_instance_segmentation,
            fieldOfView=self.field_of_view,
        )
        self.scene = scene
        self.records = []
        self._record_initialization()
        metadata = copy.deepcopy(event.metadata)
        result = StepResult(event, metadata, copy.deepcopy(self.records[-1]))
        if not metadata.get("lastActionSuccess", False):
            raise ActionFailure(result)
        return result

    def save_pngs(
        self,
        result: StepResult,
        directory: str | Path,
        *,
        stem: str,
        include_instance: bool = True,
    ) -> dict[str, str | None]:
        """Write the RGB frame and optionally the instance mask as PNG files."""
        from PIL import Image

        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "frame"
        rgb_path = out_dir / f"{safe_stem}_rgb.png"
        frame = getattr(result.event, "frame", None)
        if frame is None:
            raise RuntimeError("This event has no RGB frame; check headless/renderImage configuration")
        Image.fromarray(frame).save(rgb_path, format="PNG")

        instance_path: Path | None = None
        if include_instance:
            instance = getattr(result.event, "instance_segmentation_frame", None)
            if instance is not None:
                instance_path = out_dir / f"{safe_stem}_instance.png"
                Image.fromarray(instance).save(instance_path, format="PNG")
        return {
            "rgb": str(rgb_path),
            "instance": str(instance_path) if instance_path else None,
        }

    def reachable_positions(self, **kwargs: Any) -> list[dict[str, float]]:
        result = self.step("GetReachablePositions", **kwargs)
        if not result.record.get("lastActionSuccess"):
            return []
        value = result.metadata.get("actionReturn") or []
        return copy.deepcopy(value)

    @staticmethod
    def _distance_xz(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
        return math.hypot(float(a["x"]) - float(b["x"]), float(a["z"]) - float(b["z"]))

    def find_object(
        self,
        object_type: str,
        *,
        origin: Mapping[str, float] | None = None,
        object_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Find an object by exact type, then nearest to origin with ID tie-break."""
        metadata = self.snapshot()
        objects = [
            item for item in metadata.get("objects", [])
            if item.get("objectType") == object_type
            and (object_id is None or item.get("objectId") == object_id)
        ]
        if not objects:
            return None
        if origin is None:
            origin = metadata.get("agent", {}).get("position")
        if origin is None:
            objects.sort(key=lambda item: str(item.get("objectId", "")))
        else:
            objects.sort(
                key=lambda item: (
                    self._distance_xz(item.get("position", {}), origin),
                    str(item.get("objectId", "")),
                )
            )
        return copy.deepcopy(objects[0])

    def safe_teleport(
        self,
        position: Mapping[str, float],
        *,
        rotation_y: float | None = None,
        horizon: float | None = None,
        standing: bool | None = None,
        force_teleport: bool = False,
        reachable_tolerance: float = 0.16,
    ) -> StepResult:
        """Teleport to a reachable grid position, or explicitly force placement.

        Without force, the requested XZ point must be close to a reported
        reachable position. With force_teleport=True, ``forceAction`` is passed
        through to TeleportFull and the simulator's success flag remains the
        authority on whether placement succeeded.
        """
        current = self.snapshot().get("agent", {})
        target = {k: float(position[k]) for k in ("x", "y", "z")}
        if not force_teleport:
            reachable = self.reachable_positions()
            if not reachable:
                raise RuntimeError("GetReachablePositions returned no usable positions")
            closest = min(reachable, key=lambda p: self._distance_xz(p, target))
            distance = self._distance_xz(closest, target)
            if distance > reachable_tolerance:
                raise ValueError(
                    f"Requested point is {distance:.3f}m from the nearest reachable point; "
                    f"tolerance is {reachable_tolerance:.3f}m"
                )
            # Use the simulator-reported y as well as x/z for a safe floor pose.
            target = {k: float(closest[k]) for k in ("x", "y", "z")}
        rotation_y = float(current.get("rotation", {}).get("y", 0.0) if rotation_y is None else rotation_y)
        horizon = float(current.get("cameraHorizon", 0.0) if horizon is None else horizon)
        standing = bool(current.get("isStanding", True) if standing is None else standing)
        return self.step(
            "TeleportFull",
            position=target,
            rotation={"x": 0.0, "y": rotation_y, "z": 0.0},
            horizon=horizon,
            standing=standing,
            forceAction=bool(force_teleport),
            raise_on_failure=True,
        )

    def face_object(
        self,
        obj: Mapping[str, Any],
        *,
        min_distance: float = 0.6,
        max_distance: float = 1.6,
        camera_height_offset: float | None = None,
        position: Mapping[str, Any] | None = None,
        force_teleport: bool = False,
    ) -> StepResult:
        """Choose a reachable point and geometrically aim at the object's bounds center.

        Prefer the live camera-to-agent offset in event metadata. The explicit
        fallback is for older/synthetic metadata that omits ``cameraPosition``.
        ``position`` lets callers recalibrate a native pose without trusting its
        supplied yaw or horizon.
        """
        if not (0 <= min_distance <= max_distance):
            raise ValueError("require 0 <= min_distance <= max_distance")
        bounds = obj.get("axisAlignedBoundingBox")
        target = bounds.get("center") if isinstance(bounds, Mapping) else None
        if not isinstance(target, Mapping) or not all(k in target for k in ("x", "y", "z")):
            target = obj.get("position")
        if not isinstance(target, Mapping) or not all(k in target for k in ("x", "y", "z")):
            raise ValueError("obj must include axisAlignedBoundingBox.center or a 3D position")

        if position is None:
            positions = self.reachable_positions()
            candidates = []
            for point in positions:
                distance = self._distance_xz(point, target)
                if min_distance <= distance <= max_distance:
                    candidates.append((distance, float(point["x"]), float(point["z"]), point))
            if not candidates:
                raise RuntimeError(
                    f"No reachable position is {min_distance:.2f}-{max_distance:.2f}m from object"
                )
            band_mid = (min_distance + max_distance) / 2.0
            _, _, _, chosen = min(
                candidates,
                key=lambda row: (abs(row[0] - band_mid), row[1], row[2]),
            )
        else:
            if not all(key in position for key in ("x", "y", "z")):
                raise ValueError("position must include x, y and z")
            chosen = {key: float(position[key]) for key in ("x", "y", "z")}

        metadata = self.snapshot()
        agent = metadata.get("agent", {})
        if camera_height_offset is None:
            camera_position = metadata.get("cameraPosition")
            agent_position = agent.get("position", {})
            if (isinstance(camera_position, Mapping) and isinstance(agent_position, Mapping)
                    and "y" in camera_position and "y" in agent_position):
                camera_height_offset = float(camera_position["y"]) - float(agent_position["y"])
            else:
                camera_height_offset = 0.675
        agent_y = float(chosen["y"]) + float(camera_height_offset)
        dx = float(target["x"]) - float(chosen["x"])
        dz = float(target["z"]) - float(chosen["z"])
        yaw = math.degrees(math.atan2(dx, dz)) % 360.0
        horizontal = max(math.hypot(dx, dz), 1e-8)
        raw_horizon = math.degrees(math.atan2(agent_y - float(target["y"]), horizontal))
        # TeleportFull accepts continuous camera horizons. Keeping the computed
        # angle avoids the large floor/ceiling errors caused by 30-degree bins.
        horizon = min(60.0, max(-30.0, raw_horizon))
        return self.safe_teleport(
            chosen,
            rotation_y=yaw,
            horizon=horizon,
            force_teleport=force_teleport,
        )

    def face_nearest_object(
        self,
        object_type: str,
        *,
        object_id: str | None = None,
        min_distance: float = 0.6,
        max_distance: float = 1.6,
        force_teleport: bool = False,
    ) -> tuple[dict[str, Any], StepResult]:
        """Find a stable nearest object of the requested type and face it."""
        obj = self.find_object(object_type, object_id=object_id)
        if obj is None:
            raise LookupError(f"No object of type {object_type!r} is present")
        result = self.face_object(
            obj,
            min_distance=min_distance,
            max_distance=max_distance,
            force_teleport=force_teleport,
        )
        return obj, result

    def export_action_log(self, path: str | Path) -> Path:
        """Save action ledger JSON; metadata snapshots remain a separate concern."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.records, ensure_ascii=False, indent=2), encoding="utf-8")
        return output

    def stop(self) -> None:
        self.controller.stop()

    def __enter__(self) -> "ControllerSession":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()


__all__ = ["ActionFailure", "ControllerSession", "StepResult"]
