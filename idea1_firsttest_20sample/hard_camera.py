"""Prehistory, fixed third-party camera preflight for the H01-H05 hard groups.

This is a screening instrument. Instance-mask pixels establish framing only;
they do not establish human readability or semantic evidence.
"""
from __future__ import annotations

import copy
import gzip
import json
import math
from pathlib import Path
from typing import Any, Mapping

from observation_views import changed_objects, mask_presence, world_state
from view_planning import plan_views


HARD_FAMILIES = {
    "H01": "coffee_machine", "H02": "carryplate", "H03": "stove",
    "H04": "nested", "H05": "microwave",
}
ROOM_NOISE_TOKENS = ("countertop", "surface", "surfaces")


class CameraPreflightError(RuntimeError):
    """Raised when a camera API action changes the guarded physical world."""

    def __init__(self, message: str, report: dict[str, Any]):
        super().__init__(message)
        self.report = report


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    return repr(value)


def _metadata(ctx: Any) -> dict[str, Any]:
    return ctx.session.snapshot()


def _role_ids(ctx: Any) -> dict[str, str]:
    raw_roles = getattr(ctx, "roles", {}) or {}
    metadata = _metadata(ctx)
    by_id = {str(row.get("objectId")): row for row in metadata.get("objects", [])
             if isinstance(row, Mapping) and row.get("objectId") is not None}
    output: dict[str, str] = {}
    for alias, value in (raw_roles.items() if isinstance(raw_roles, Mapping)
                         else ((str(value), value) for value in raw_roles)):
        obj = None
        getter = getattr(ctx, "obj", None)
        if callable(getter):
            try:
                obj = getter(alias)
            except (KeyError, LookupError, TypeError, ValueError):
                obj = None
        if not isinstance(obj, Mapping) and isinstance(value, Mapping):
            obj = value
        object_id = (obj.get("objectId") if isinstance(obj, Mapping) else
                     value.get("objectId") if isinstance(value, Mapping) else value)
        if object_id is None and isinstance(obj, Mapping):
            object_id = obj.get("id")
        if object_id is None:
            continue
        object_id = str(object_id)
        if object_id not in by_id:
            continue
        output[str(alias)] = object_id
    return output


def _role_objects(ctx: Any, role_ids: Mapping[str, str], metadata: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    by_id = {str(row.get("objectId")): row for row in metadata.get("objects", [])
             if isinstance(row, Mapping) and row.get("objectId") is not None}
    result = {}
    getter = getattr(ctx, "obj", None)
    for alias, object_id in role_ids.items():
        row = None
        if callable(getter):
            try:
                row = getter(alias)
            except (KeyError, LookupError, TypeError, ValueError):
                row = None
        # Current simulator metadata is authoritative for positions/AABBs.
        actual = by_id.get(object_id)
        if isinstance(actual, Mapping):
            result[alias] = copy.deepcopy(dict(actual))
        elif isinstance(row, Mapping):
            result[alias] = copy.deepcopy(dict(row))
    return result


def _family(ctx: Any) -> tuple[str | None, str | None]:
    for name in ("hard_group", "group_id", "scenario_id", "task_id", "family", "group"):
        value = getattr(ctx, name, None)
        if value is None:
            continue
        text = str(value).strip()
        upper = text.upper()
        for group, family in HARD_FAMILIES.items():
            if upper == group or upper.startswith(group + "-") or upper.startswith(group + "_"):
                return family, group
        normalized = text.lower().replace("-", "_").replace(" ", "_")
        if normalized in set(HARD_FAMILIES.values()):
            return normalized, None
    return None, None


def _waypoint_position(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    if all(axis in value for axis in ("x", "y", "z")):
        candidate = value
    else:
        candidate = value.get("position")
    if not isinstance(candidate, Mapping):
        return None
    try:
        point = {axis: float(candidate[axis]) for axis in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError):
        return None
    return point if all(math.isfinite(v) for v in point.values()) else None


def _waypoints_for_alias(waypoints: Any, alias: str) -> list[Any]:
    if not isinstance(waypoints, Mapping):
        return []
    values = waypoints.get(alias, [])
    if not values:
        values = [row for row in waypoints.values() if isinstance(row, Mapping)
                  and row.get("role_alias", row.get("role", row.get("object_alias"))) == alias]
    if isinstance(values, Mapping):
        return [values]
    if isinstance(values, (list, tuple)):
        return list(values)
    return []


def _waypoint_extent(value: Any) -> tuple[dict[str, float], dict[str, float]] | None:
    if not isinstance(value, Mapping):
        return None
    box = value.get("axisAlignedBoundingBox", value.get("bounds"))
    if isinstance(box, Mapping):
        center, size = box.get("center"), box.get("size")
        if isinstance(center, Mapping) and isinstance(size, Mapping):
            try:
                low = {axis: float(center[axis]) - float(size[axis]) / 2 for axis in ("x", "y", "z")}
                high = {axis: float(center[axis]) + float(size[axis]) / 2 for axis in ("x", "y", "z")}
                if all(math.isfinite(v) for v in (*low.values(), *high.values())):
                    return low, high
            except (KeyError, TypeError, ValueError):
                pass
        minimum, maximum = box.get("min"), box.get("max")
        if isinstance(minimum, Mapping) and isinstance(maximum, Mapping):
            try:
                low = {axis: float(minimum[axis]) for axis in ("x", "y", "z")}
                high = {axis: float(maximum[axis]) for axis in ("x", "y", "z")}
                if all(math.isfinite(v) for v in (*low.values(), *high.values())):
                    return low, high
            except (KeyError, TypeError, ValueError):
                pass
    point = _waypoint_position(value)
    return ({axis: value for axis, value in point.items()},
            {axis: value for axis, value in point.items()}) if point else None


def _include_waypoints(roles: Mapping[str, dict[str, Any]], *waypoint_sources: tuple[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Expand role geometry only from explicitly supplied finite waypoint data."""
    expanded = {alias: copy.deepcopy(obj) for alias, obj in roles.items()}
    used: dict[str, list[dict[str, Any]]] = {}
    for alias, obj in expanded.items():
        extents = [(source, extent) for source, waypoints in waypoint_sources
                   for row in _waypoints_for_alias(waypoints, alias)
                   if (extent := _waypoint_extent(row)) is not None]
        if not extents:
            continue
        used[alias] = [{"source": source, "min": dict(low), "max": dict(high),
                        "center": {axis: (low[axis] + high[axis]) / 2
                                   for axis in ("x", "y", "z")}}
                       for source, (low, high) in extents]
        box = obj.get("axisAlignedBoundingBox")
        if isinstance(box, Mapping) and isinstance(box.get("center"), Mapping) and isinstance(box.get("size"), Mapping):
            center, size = box["center"], box["size"]
            try:
                lows = {axis: float(center[axis]) - float(size[axis]) / 2 for axis in ("x", "y", "z")}
                highs = {axis: float(center[axis]) + float(size[axis]) / 2 for axis in ("x", "y", "z")}
            except (KeyError, TypeError, ValueError):
                lows = highs = None
        elif isinstance(box, Mapping) and isinstance(box.get("min"), Mapping) and isinstance(box.get("max"), Mapping):
            try:
                lows = {axis: float(box["min"][axis]) for axis in ("x", "y", "z")}
                highs = {axis: float(box["max"][axis]) for axis in ("x", "y", "z")}
            except (KeyError, TypeError, ValueError):
                lows = highs = None
        else:
            position = _waypoint_position({"position": obj.get("position")})
            if position is None:
                lows = highs = None
            else:
                lows = dict(position)
                highs = dict(position)
        if lows is None or highs is None:
            continue
        for _source, (waypoint_low, waypoint_high) in extents:
            for axis in ("x", "y", "z"):
                lows[axis] = min(lows[axis], waypoint_low[axis])
                highs[axis] = max(highs[axis], waypoint_high[axis])
        obj["axisAlignedBoundingBox"] = {
            "center": {axis: (lows[axis] + highs[axis]) / 2 for axis in ("x", "y", "z")},
            "size": {axis: highs[axis] - lows[axis] for axis in ("x", "y", "z")},
        }
    return expanded, used


def _is_room_noise(alias: str, object_row: Mapping[str, Any]) -> bool:
    label = (alias + " " + str(object_row.get("objectType", ""))).lower().replace("_", "")
    return any(token in label for token in ROOM_NOISE_TOKENS)


def _write_report(out_dir: Path, report: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "camera_preflight.json").write_text(
        json.dumps(_jsonable(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _event_metadata(result: Any, session: Any) -> dict[str, Any]:
    metadata = getattr(result, "metadata", None)
    return metadata if isinstance(metadata, dict) else session.snapshot()


def _camera_id(result: Any) -> int | None:
    metadata = getattr(result, "metadata", {}) or {}
    cameras = metadata.get("thirdPartyCameras") or []
    if cameras:
        row = cameras[-1]
        value = row.get("thirdPartyCameraId", row.get("cameraId"))
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    frames = getattr(getattr(result, "event", None), "third_party_camera_frames", []) or []
    return len(frames) - 1 if frames else None


def _camera_kwargs(pose: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "position": dict(pose["position"]),
        "rotation": dict(pose["rotationEuler"]),
        "fieldOfView": float(pose["fov_degrees"]),
        "nearClippingPlane": 0.03,
        "farClippingPlane": 20.0,
    }


def _current_essential_roles(ctx: Any, metadata: Mapping[str, Any], role_ids: Mapping[str, str]) -> dict[str, str]:
    by_id = {str(row.get("objectId")): row for row in metadata.get("objects", [])
             if isinstance(row, Mapping) and row.get("objectId") is not None}
    return {alias: object_id for alias, object_id in role_ids.items()
            if object_id in by_id and not _is_room_noise(alias, by_id[object_id])}


def configure_evidence_cameras(ctx: Any, trace: Any, out_dir: str | Path) -> dict[str, Any]:
    """Configure and screen fixed third-party cameras before public history.

    Only camera API actions are issued. Every action is guarded against the full
    physical world snapshot; failure retries are bounded by the planner's pose
    count and are allowed only while that guard remains unchanged.
    """
    from PIL import Image

    directory = Path(out_dir)
    candidate_dir = directory / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "status": "pending", "camera_kind": "fixed_third_party",
        "geometry_only_screening_not_semantic_approval": True,
        "semantic_readability": "not_assessed", "public_history_started": False,
        "camera_actions": [], "poses": [], "candidate_trials": [],
        "rgb_files": [], "actual_masks": [], "world_state_changed": False,
    }
    if (bool(getattr(ctx, "public_history_started", False))
            or bool(getattr(ctx, "history_started", False))
            or bool(getattr(ctx, "public_phase", False))):
        report.update(status="rejected", error="camera configuration requested after public history began")
        _write_report(directory, report)
        return report
    active_phase = getattr(trace, "_phase", {})
    context_phase = getattr(ctx, "phase", None)
    if ((isinstance(active_phase, Mapping) and active_phase.get("public"))
            or (isinstance(context_phase, Mapping) and context_phase.get("public"))):
        report.update(status="rejected", error="camera configuration requested during a public phase")
        _write_report(directory, report)
        return report
    metadata = _metadata(ctx)
    role_ids = _role_ids(ctx)
    actual_roles = _role_objects(ctx, role_ids, metadata)
    family, group = _family(ctx)
    report.update(hard_group=group, family=family, input_roles=role_ids,
                  role_geometry={alias: {"position": row.get("position"),
                                         "axisAlignedBoundingBox": row.get("axisAlignedBoundingBox")}
                                 for alias, row in actual_roles.items()},
                  waypoints=_jsonable(getattr(ctx, "waypoints", {})))
    if not actual_roles:
        report.update(status="rejected", error="no current task-role objects resolved from ctx.roles/obj(alias)")
        _write_report(directory, report)
        return report
    if family is None:
        # Try matching actual role types only when the hard group identifier is
        # absent; this remains a planner decision, not a guessed scene family.
        inferred = plan_views(actual_roles)
        family = inferred.get("family")
        report["family"] = family
    if family not in set(HARD_FAMILIES.values()):
        report.update(status="rejected", error="unsupported or unidentifiable H01-H05 camera family")
        _write_report(directory, report)
        return report

    native_waypoints = getattr(ctx, "waypoints", {}) or {}
    capture_waypoints = getattr(ctx, "capture_waypoints", {}) or {}
    planning_roles, waypoint_contributions = _include_waypoints(
        actual_roles, ("native_waypoints", native_waypoints),
        ("capture_waypoints", capture_waypoints))
    report["native_waypoints"] = _jsonable(native_waypoints)
    report["capture_waypoints"] = _jsonable(capture_waypoints)
    report["waypoint_geometry_contributions"] = waypoint_contributions
    report["capture_waypoints_status"] = "proposal_only_actual_held_pose_unknown"
    # planning_roles already came from current native metadata; omitting the
    # override preserves the separately recorded waypoint range expansion.
    plan = plan_views(planning_roles, device_family=family)
    report["plan"] = plan
    groups = [row for row in plan.get("groups", [])
              if row.get("fit_status") != "not_fit" and row.get("status") not in {"not_fit", "oversized_bounds"}][:3]
    if not groups:
        report.update(status="rejected", error=f"no usable geometry plan: {plan.get('status')}")
        _write_report(directory, report)
        return report

    phase_setter = getattr(trace, "set_phase", None)
    if callable(phase_setter):
        phase_setter("camera preflight", public=False, kind="calibration")

    session = ctx.session
    selected: list[dict[str, Any]] = []
    camera_actions = report["camera_actions"]
    changed_any: set[str] = set()

    def do_camera_action(action: str, kwargs: dict[str, Any], phase: str) -> Any:
        before_metadata = session.snapshot()
        before_state = world_state(before_metadata)
        row = {"action": action, "phase": phase, "kwargs": _jsonable(kwargs)}
        try:
            result = session.step(action, raise_on_failure=True, **kwargs)
            if result.record.get("lastActionSuccess") is not True:
                raise RuntimeError(f"native camera action did not confirm success: {action}")
            after_metadata = _event_metadata(result, session)
        except Exception as exc:
            after_metadata = session.snapshot()
            after_state = world_state(after_metadata)
            changed = changed_objects(before_state, after_state)
            row.update(success=False, error=f"{type(exc).__name__}: {exc}",
                       action_index=(session.records[-1].get("index") if session.records else None),
                       guard_changed_entities=changed)
            camera_actions.append(row)
            if changed:
                changed_any.update(changed)
                report.update(status="rejected", world_state_changed=True,
                              changed_objects=sorted(changed_any),
                              error="camera intervention altered guarded physical state")
                _write_report(directory, report)
                raise CameraPreflightError(report["error"], copy.deepcopy(report)) from exc
            raise
        after_state = world_state(after_metadata)
        changed = changed_objects(before_state, after_state)
        row.update(success=True, action_index=result.record.get("index"),
                   guard_changed_entities=changed)
        camera_actions.append(row)
        if changed:
            changed_any.update(changed)
            report.update(status="rejected", world_state_changed=True,
                          changed_objects=sorted(changed_any),
                          error="camera intervention altered guarded physical state")
            _write_report(directory, report)
            raise CameraPreflightError(report["error"], copy.deepcopy(report))
        return result

    targets = _current_essential_roles(ctx, metadata, role_ids)
    for slot, camera_group in enumerate(groups):
        group_targets = {alias: role_ids[alias] for alias in camera_group.get("roles", [])
                         if alias in role_ids and alias in targets}
        camera_id: int | None = None
        best: dict[str, Any] | None = None
        candidates = camera_group.get("candidates", [])[:4]
        for trial_index, pose in enumerate(candidates):
            kwargs = _camera_kwargs(pose)
            action = "AddThirdPartyCamera" if camera_id is None else "UpdateThirdPartyCamera"
            if camera_id is not None:
                kwargs["thirdPartyCameraId"] = camera_id
            try:
                result = do_camera_action(action, kwargs, "camera_candidate")
            except CameraPreflightError:
                raise
            except Exception as exc:
                report["candidate_trials"].append({"group_id": camera_group["group_id"],
                    "purpose": camera_group["purpose"], "candidate_id": pose.get("candidate_id"),
                    "pose": _jsonable(pose), "action": action, "error": f"{type(exc).__name__}: {exc}",
                    "retry_allowed": True, "retry_reason": "camera API failure with unchanged world state"})
                continue
            if camera_id is None:
                camera_id = _camera_id(result)
                if camera_id is None:
                    report["candidate_trials"].append({"group_id": camera_group["group_id"],
                        "candidate_id": pose.get("candidate_id"), "action": action,
                        "error": "camera action succeeded but no third-party frame/camera ID was returned",
                        "retry_allowed": True})
                    continue
            event = getattr(result, "event", None)
            frames = getattr(event, "third_party_camera_frames", None) if event is not None else None
            masks = getattr(event, "third_party_instance_masks", None) if event is not None else None
            rgb_path = None
            if frames is not None and 0 <= camera_id < len(frames) and frames[camera_id] is not None:
                rgb_path = candidate_dir / f"group_{slot:02d}_trial_{trial_index:02d}_{pose.get('candidate_id','pose')}.png"
                Image.fromarray(frames[camera_id]).save(rgb_path, format="PNG")
                report["rgb_files"].append(str(rgb_path))
            presence = mask_presence(event, camera_id, group_targets) if event is not None else {
                "status": "event_missing", "roles": {}, "present_count": 0, "score": -1.0}
            trial = {"group_id": camera_group["group_id"], "purpose": camera_group["purpose"],
                     "candidate_id": pose.get("candidate_id"), "pose": _jsonable(pose),
                     "camera_id": camera_id, "action": action, "rgb_path": str(rgb_path) if rgb_path else None,
                     "frame_status": "captured" if rgb_path else "third_party_rgb_missing",
                     "rendered_presence": presence, "mask_status": presence.get("status"),
                     "mask_objects_available": bool(masks is not None and camera_id < len(masks))}
            report["candidate_trials"].append(trial)
            report["actual_masks"].append({"camera_id": camera_id,
                "candidate_id": pose.get("candidate_id"), "presence": presence})
            score = presence.get("score", -1.0) if rgb_path else -1.0
            if best is None or score > best["score"]:
                best = {"pose": pose, "presence": presence, "score": score,
                        "camera_id": camera_id, "group": camera_group}

        if best is None or camera_id is None:
            report["poses"].append({"group_id": camera_group["group_id"],
                "purpose": camera_group["purpose"], "status": "no_successful_camera_trial"})
            continue
        final_kwargs = _camera_kwargs(best["pose"])
        final_kwargs["thirdPartyCameraId"] = camera_id
        try:
            final_result = do_camera_action("UpdateThirdPartyCamera", final_kwargs, "select_camera_pose")
        except CameraPreflightError:
            raise
        except Exception as exc:
            report["poses"].append({"group_id": camera_group["group_id"],
                "purpose": camera_group["purpose"], "status": "selected_pose_update_failed",
                "error": f"{type(exc).__name__}: {exc}"})
            continue
        event = getattr(final_result, "event", None)
        frames = getattr(event, "third_party_camera_frames", None) if event is not None else None
        selected_path = None
        if frames is not None and 0 <= camera_id < len(frames) and frames[camera_id] is not None:
            selected_path = directory / f"selected_view_{slot:02d}_{camera_group['purpose']}.png"
            Image.fromarray(frames[camera_id]).save(selected_path, format="PNG")
            report["rgb_files"].append(str(selected_path))
        presence = mask_presence(event, camera_id, targets) if event is not None else {
            "status": "event_missing", "roles": {}, "present_count": 0, "score": -1.0}
        selected.append({"camera_id": camera_id, "view_id": f"fixed_{camera_id}",
                         "purpose": camera_group["purpose"], "target_roles": targets,
                         "group_id": camera_group["group_id"], "pose": best["pose"],
                         "path": str(selected_path) if selected_path else None,
                         "rendered_presence": presence})
        report["poses"].append({"group_id": camera_group["group_id"],
            "purpose": camera_group["purpose"], "status": "selected" if selected_path else "selected_rgb_missing",
            "camera_id": camera_id, "pose": _jsonable(best["pose"]),
            "path": str(selected_path) if selected_path else None,
            "actual_masks": presence})

    trace_cameras = [{"camera_id": view["camera_id"], "view_id": view["view_id"],
                      "purpose": view["purpose"]} for view in selected]
    if trace_cameras:
        trace.set_cameras(trace_cameras)
    union_presence = {alias: False for alias in targets}
    for view in selected:
        for alias, mask_row in view["rendered_presence"].get("roles", {}).items():
            union_presence[alias] = union_presence.get(alias, False) or bool(mask_row.get("framing_presence"))
    missing = sorted(alias for alias, present in union_presence.items() if not present)
    report["essential_current_roles"] = targets
    report["union_mask_coverage"] = {"roles": union_presence, "missing_roles": missing,
                                     "status": "covered" if targets and not missing else "incomplete"}
    report["selected_views"] = selected
    if not targets:
        report.update(status="rejected", error="no essential non-room-noise task roles for mask coverage")
    elif missing:
        report.update(status="rejected", error="selected fixed-camera masks do not cover every essential current role")
    elif any(view["path"] is None for view in selected):
        report.update(status="rejected", error="selected camera RGB is unavailable")
    else:
        report.update(status="screened", error=None,
                      note="Third-party instance-mask coverage is framing-only; semantic readability remains not_assessed.")
    _write_report(directory, report)
    return report


def _read_step_metadata(trace: Any, event_row: Mapping[str, Any]) -> dict[str, Any] | None:
    relative = event_row.get("metadata_gzip")
    if not relative:
        return None
    path = Path(trace.directory) / relative
    if not path.is_file():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError):
        return None


def _agent_mask_presence(event: Any, roles: Mapping[str, str]) -> dict[str, Any]:
    masks = getattr(event, "instance_masks", None)
    if not isinstance(masks, Mapping):
        return {"status": "agent_instance_masks_unavailable", "roles": {}, "present_count": 0}
    rows = {}
    for alias, object_id in roles.items():
        mask = masks.get(object_id)
        try:
            height, width = int(mask.shape[0]), int(mask.shape[1])
            ys, xs = mask.nonzero()[:2]
            pixels = len(xs)
            bbox = None if pixels == 0 else {
                "x": int(xs.min()), "y": int(ys.min()),
                "width": int(xs.max() - xs.min() + 1),
                "height": int(ys.max() - ys.min() + 1),
            }
        except (AttributeError, IndexError, TypeError):
            height = width = pixels = 0
            bbox = None
        fraction = pixels / max(1, height * width)
        rows[alias] = {"object_id": object_id, "pixels": pixels, "fraction": fraction,
                       "bbox": bbox, "framing_presence": pixels >= 16 and fraction >= 0.00015,
                       "semantic_readability": "not_assessed"}
    return {"status": "mask_presence_only", "roles": rows,
            "present_count": sum(bool(row["framing_presence"]) for row in rows.values())}


def audit_fixed_views(ctx: Any, trace: Any, phase: str) -> dict[str, Any]:
    """Inspect current fixed-camera output without issuing any native action."""
    session = ctx.session
    rows = trace.events
    latest = rows[-1] if rows else None
    report: dict[str, Any] = {
        "phase": str(phase), "native_actions_sent": 0,
        "semantic_readability": "not_assessed", "diagnostic_not_universal_error": True,
        "status": "unavailable", "fresh_frame": False, "views": [],
    }
    if latest is None:
        report["error"] = "trace has no recorded steps"
        return report
    report["global_step"] = latest.get("global_step")
    report["trace_phase"] = latest.get("phase_label")
    report["new_event_received"] = latest.get("new_event_received")
    if not latest.get("new_event_received"):
        report["error"] = "latest native call reused a stale last_event; no new picture was captured"
        report["frame_status"] = latest.get("frame_status")
        return report
    event = getattr(session.controller, "last_event", None)
    if event is None:
        report["error"] = "current event is unavailable"
        return report
    metadata = session.snapshot()
    role_ids = _role_ids(ctx)
    essential = _current_essential_roles(ctx, metadata, role_ids)
    agent_presence = _agent_mask_presence(event, essential)
    cameras = getattr(trace, "_cameras", [])
    for camera in cameras:
        camera_id = int(camera["camera_id"])
        presence = mask_presence(event, camera_id, essential)
        report["views"].append({"camera_id": camera_id, "view_id": camera["view_id"],
                                "purpose": camera["purpose"], "rendered_presence": presence,
                                "semantic_readability": "not_assessed"})
    report["fresh_frame"] = latest.get("frame_status") == "captured"
    report["current_role_ids"] = essential
    report["agent_mask_presence"] = agent_presence
    union_coverage = {alias: bool(agent_presence.get("roles", {}).get(alias, {}).get("framing_presence"))
                      for alias in essential}
    for view in report["views"]:
        for alias, row in view["rendered_presence"].get("roles", {}).items():
            union_coverage[alias] = union_coverage.get(alias, False) or bool(row.get("framing_presence"))
    report["agent_plus_fixed_view_union_coverage"] = {
        "roles": union_coverage,
        "missing_roles": sorted(alias for alias, covered in union_coverage.items() if not covered),
        "status": "covered" if union_coverage and all(union_coverage.values()) else "incomplete",
    }
    report["role_state_snapshot"] = {
        alias: {"object_id": object_id,
                "position": copy.deepcopy(next((row.get("position") for row in metadata.get("objects", [])
                                                 if row.get("objectId") == object_id), None)),
                "parent_receptacles": copy.deepcopy(next((row.get("parentReceptacles") for row in metadata.get("objects", [])
                                                          if row.get("objectId") == object_id), None))}
        for alias, object_id in essential.items()
    }
    report["status"] = "audited" if report["views"] and report["fresh_frame"] else "incomplete"

    matching = [row for row in rows if row.get("phase_label") == str(phase)
                and row.get("new_event_received")]
    position_changed_roles: set[str] = set()
    changed_entity_history = []
    previous_world = None
    per_view_hashes: dict[str, list[str]] = {}
    for row in matching:
        current_metadata = _read_step_metadata(trace, row)
        if current_metadata is not None:
            current_world = world_state(current_metadata)
            if previous_world is not None:
                entities = changed_objects(previous_world, current_world)
                changed_entity_history.append({"global_step": row.get("global_step"),
                                               "changed_entities": entities})
                for alias, object_id in essential.items():
                    old = previous_world["objects"].get(object_id, {}).get("position")
                    new = current_world["objects"].get(object_id, {}).get("position")
                    if old != new:
                        position_changed_roles.add(alias)
            previous_world = current_world
        for frame in row.get("frames", []):
            if frame.get("pixel_sha256") and frame.get("view_id") in (
                    {"agent"} | {c["view_id"] for c in cameras}):
                per_view_hashes.setdefault(frame["view_id"], []).append(frame["pixel_sha256"])
    identical_views = sorted(view_id for view_id, hashes in per_view_hashes.items()
                             if len(hashes) >= 2 and len(set(hashes)) == 1)
    report["position_changed_roles"] = sorted(position_changed_roles)
    report["changed_entities_by_step"] = changed_entity_history
    report["identical_rgb_views_across_phase"] = identical_views
    expected_view_ids = {"agent"} | {camera["view_id"] for camera in cameras}
    report["position_changed_while_all_rgb_identical"] = bool(
        position_changed_roles and expected_view_ids
        and expected_view_ids.issubset(per_view_hashes)
        and expected_view_ids.issubset(set(identical_views)))
    # Keep the earlier key for callers that only counted registered third-party views.
    expected_fixed = {camera["view_id"] for camera in cameras}
    report["position_changed_while_all_fixed_rgb_identical"] = bool(
        position_changed_roles and expected_fixed and expected_fixed.issubset(set(identical_views)))
    report["diagnostic_note"] = (
        "An identical-frame/changed-position pattern is a diagnostic flag for review, not proof of a bad camera or universal capture failure."
    )
    return report


__all__ = ["CameraPreflightError", "configure_evidence_cameras", "audit_fixed_views"]
