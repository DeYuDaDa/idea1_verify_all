"""Pure geometry for planning independent evidence-camera views.

This module does not call AI2-THOR and does not move an agent.  It returns
camera poses for an external renderer/controller to evaluate.  Geometric
frustum estimates are only candidate-screening hints: occlusion and semantic
readability always remain ``not_assessed`` until an image is rendered/reviewed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any


_FAMILY_PATTERNS: dict[str, tuple[tuple[str, ...], ...]] = {
    "coffee_machine": (("coffeemachine", "coffee_machine"), ("mug", "cup")),
    "toaster": (("toaster",), ("bread", "toast", "slice")),
    "sink": (("sinkbasin", "sink", "faucet", "tap"), ("bowl", "mug", "cup")),
    "microwave": (("microwave",), ("potato", "food", "contents", "content")),
    "stove": (("stoveburner", "burner", "stove", "knob"), ("pot", "pan", "kettle", "knob")),
    "carryplate": (("plate", "carryplate"), ("apple", "food")),
    "nested": (("outer", "inner", "container", "bowl", "pot", "plate", "microwave", "faucet", "sinkbasin"), ("inner", "content", "food", "apple", "mug")),
}

_DEVICE_TYPES = {"coffeemachine", "toaster", "sinkbasin", "faucet", "microwave", "stoveburner", "stoveknob"}
_ROOM_NOISE = {"countertop", "floor", "wall", "ceiling", "fridge", "refrigerator"}


def _norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def _vec3(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        xyz = {axis: float(value[axis]) for axis in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in xyz.values()):
        return None
    return xyz


def _object_identity(alias: str, obj: Mapping[str, Any]) -> str:
    return _norm(" ".join((alias, str(obj.get("objectType", "")), str(obj.get("objectId", "")))))


def _is_room_noise(alias: str, obj: Mapping[str, Any]) -> bool:
    identity = _object_identity(alias, obj)
    return any(_norm(item) in identity for item in _ROOM_NOISE)


def _resolve_family(roles: Mapping[str, Any], family: str | None) -> str | None:
    if family:
        key = _norm(family)
        aliases = {"coffeemachine": "coffee_machine", "sinkbasin": "sink", "stovetop": "stove", "nestedcontainer": "nested", "carryplateapple": "carryplate"}
        key = aliases.get(key, key)
        return key if key in _FAMILY_PATTERNS else None
    text = " ".join(_object_identity(str(alias), obj) for alias, obj in roles.items() if isinstance(obj, Mapping))
    for candidate in ("coffee_machine", "toaster", "microwave", "carryplate", "nested", "sink", "stove"):
        if any(_norm(token) in text for pattern in _FAMILY_PATTERNS[candidate] for token in pattern):
            return candidate
    return None


def _matched_roles(roles: Mapping[str, Any], family: str) -> list[str]:
    tokens = tuple(token for group in _FAMILY_PATTERNS[family] for token in group)
    matched = []
    for alias, value in roles.items():
        if not isinstance(value, Mapping) or _is_room_noise(str(alias), value):
            continue
        ident = _object_identity(str(alias), value)
        if any(_norm(token) in ident for token in tokens):
            matched.append(str(alias))
    # A role alias such as "contents" can have a generic object type; retain it
    # only when a specific device/companion also anchors this family.
    return matched


def _bounds(obj: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float]] | None:
    box = obj.get("axisAlignedBoundingBox")
    if not isinstance(box, Mapping):
        return None
    center = _vec3(box.get("center"))
    size = _vec3(box.get("size"))
    if center is not None and size is not None and all(size[a] >= 0 for a in size):
        return center, size
    # Some metadata supplies only min/max corners.
    minimum, maximum = _vec3(box.get("min")), _vec3(box.get("max"))
    if minimum is None or maximum is None or any(maximum[a] < minimum[a] for a in minimum):
        return None
    size = {a: maximum[a] - minimum[a] for a in minimum}
    center = {a: (minimum[a] + maximum[a]) / 2 for a in minimum}
    return center, size


def _focus(roles: Sequence[str], objects: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, float] | None, dict[str, Any] | None, list[str], float]:
    points: list[dict[str, float]] = []
    lows = {a: math.inf for a in ("x", "y", "z")}
    highs = {a: -math.inf for a in ("x", "y", "z")}
    missing: list[str] = []
    for alias in roles:
        obj = objects[alias]
        bounds = _bounds(obj)
        if bounds:
            center, size = bounds
            half = {a: size[a] / 2 for a in size}
        else:
            center = _vec3(obj.get("position"))
            if center is None:
                missing.append(alias)
                continue
            half = {"x": 0.12, "y": 0.12, "z": 0.12}
            missing.append(alias)
        points.append(center)
        for axis in lows:
            lows[axis] = min(lows[axis], center[axis] - half[axis])
            highs[axis] = max(highs[axis], center[axis] + half[axis])
    if not points:
        return None, None, missing, 0.0
    box = {"min": lows, "max": highs, "size": {a: highs[a] - lows[a] for a in lows}}
    point = {a: (lows[a] + highs[a]) / 2 for a in lows}
    radius = math.sqrt(sum((highs[a] - lows[a]) ** 2 for a in ("x", "z"))) / 2
    return point, box, missing, radius


def _groups(family: str, focus_roles: list[str], objects: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, list[str], list[str]]]:
    def has(alias: str, *tokens: str) -> bool:
        return any(_norm(token) in _object_identity(alias, objects[alias]) for token in tokens)

    devices = [a for a in focus_roles if has(a, "coffeemachine", "toaster", "sinkbasin", "faucet", "microwave", "stoveburner", "stoveknob", "knob")]
    contents = [a for a in focus_roles if has(a, "mug", "cup", "bowl", "potato", "food", "pot", "pan", "kettle", "apple", "bread", "toast", "slice", "contents", "content")]
    if family == "coffee_machine":
        return [("joint_relation", focus_roles, devices + contents), ("device_detail", devices or focus_roles, devices or focus_roles), ("contents_detail", contents, contents)]
    if family == "toaster":
        return [("device_contents_relation", focus_roles, devices + contents), ("toaster_detail", devices or focus_roles, devices or focus_roles), ("bread_detail", contents or focus_roles, contents or focus_roles)]
    if family == "sink":
        return [("joint_relation", focus_roles, devices + contents), ("fixture_detail", devices or focus_roles, devices or focus_roles), ("contents_detail", contents, contents)]
    if family == "microwave":
        return [("device_contents_relation", focus_roles, devices + contents), ("interior_contents_detail", contents or focus_roles, contents or focus_roles)]
    if family == "stove":
        return [("burners_pots_knob_relation", focus_roles, focus_roles), ("control_detail", [a for a in focus_roles if has(a, "knob")], [a for a in focus_roles if has(a, "knob")]), ("burner_vessel_detail", [a for a in focus_roles if not has(a, "knob")], [a for a in focus_roles if not has(a, "knob")])]
    if family == "carryplate":
        return [("carried_relation", focus_roles, focus_roles), ("carried_item_detail", contents or focus_roles, contents or focus_roles)]
    return [("nested_relation", focus_roles, focus_roles), ("inner_contents_detail", contents or focus_roles, contents or focus_roles)]


def _candidates(point: Mapping[str, float], bounds: Mapping[str, Any], radius: float, aliases: list[str], purpose: str, fov: float) -> list[dict[str, Any]]:
    # Keep viewpoints local to the relevant roles. Vary azimuth, stand-off,
    # and camera height so actual rendering can choose around occluders.
    distance = min(3.2, max(1.0, radius * 2.4 + 0.55))
    ys = (max(0.65, point["y"] + 0.28), max(0.9, point["y"] + 0.95))
    result = []
    for idx, (angle, scale, y) in enumerate(((0, 1.0, ys[0]), (90, 1.0, ys[0]), (180, 1.15, ys[1]), (270, 0.85, ys[1]))):
        rad = math.radians(angle)
        pos = {"x": point["x"] + distance * scale * math.sin(rad), "y": y,
               "z": point["z"] + distance * scale * math.cos(rad)}
        yaw = math.degrees(math.atan2(point["x"] - pos["x"], point["z"] - pos["z"])) % 360
        # Unity/AI2-THOR camera Euler X is positive when looking downward.
        pitch = math.degrees(math.atan2(pos["y"] - point["y"], math.hypot(point["x"] - pos["x"], point["z"] - pos["z"])))
        result.append({
            "candidate_id": f"{purpose}_{idx + 1}", "purpose": purpose, "target_roles": list(aliases),
            "position": pos, "rotationEuler": {"x": pitch, "y": yaw, "z": 0.0},
            "fov_degrees": float(fov), "preconditions": ["render from this external camera pose", "use object metadata from the same observed state"],
            "frustum_coverage": "not_assessed", "occlusion": "not_assessed", "semantic_readability": "not_assessed",
        })
    return result


def plan_views(
    roles: Mapping[str, Mapping[str, Any]], *, device_family: str | None = None,
    observed_metadata: Mapping[str, Any] | None = None, fov_degrees: float = 60.0,
) -> dict[str, Any]:
    """Return role-focused independent camera pose candidates without side effects.

    ``roles`` maps scenario aliases to object metadata. If ``observed_metadata``
    contains a newer ``objects`` inventory, entries with matching objectId
    replace role metadata for geometry (useful after a pickup or other motion).
    Candidates are alternatives for the same capture/action state, never a
    temporal sequence. No pose is claimed to have rendered or passed visibility.
    """
    if not isinstance(roles, Mapping) or not roles:
        return {"status": "no_roles", "family": device_family, "focus_roles": [], "groups": [], "notes": ["Supply role aliases mapped to object metadata."]}
    if not (1.0 <= float(fov_degrees) < 179.0):
        return {"status": "invalid_fov", "family": device_family, "focus_roles": [], "groups": [], "notes": ["fov_degrees must be between 1 and 179."]}
    family = _resolve_family(roles, device_family)
    if family is None:
        return {"status": "unknown_family", "family": device_family, "focus_roles": [], "groups": [], "notes": ["No supported target device family could be inferred."]}
    objects = {str(alias): dict(obj) for alias, obj in roles.items() if isinstance(obj, Mapping)}
    observed = observed_metadata or {}
    observed_objects = observed.get("objects", []) if isinstance(observed, Mapping) else []
    by_id = {str(obj.get("objectId")): obj for obj in observed_objects if isinstance(obj, Mapping) and obj.get("objectId") is not None} if isinstance(observed_objects, Sequence) and not isinstance(observed_objects, (str, bytes)) else {}
    updated_roles: list[str] = []
    for alias, obj in objects.items():
        object_id = obj.get("objectId")
        newer = by_id.get(str(object_id)) if object_id is not None else None
        if newer:
            objects[alias] = {**obj, **newer}
            if _vec3(newer.get("position")) != _vec3(obj.get("position")):
                updated_roles.append(alias)
    focus_roles = _matched_roles(objects, family)
    if not focus_roles:
        return {"status": "no_relevant_roles", "family": family, "focus_roles": [], "groups": [], "notes": ["No family-relevant device/content roles remained after filtering room-scale and unrelated objects."]}
    groups = []
    split_specs: list[tuple[str, list[str]]] = []
    all_missing: set[str] = set()
    oversized = False
    for purpose, group_roles, required_roles in _groups(family, focus_roles, objects):
        if not group_roles:
            continue
        point, aabb, missing, radius = _focus(group_roles, objects)
        all_missing.update(missing)
        if point is None or aabb is None:
            continue
        span = aabb["size"]
        too_large = max(span.values()) > 3.0
        oversized = oversized or too_large
        group = {"group_id": f"{family}_{purpose}", "purpose": purpose, "roles": list(group_roles),
                 "required_state_roles": list(dict.fromkeys(required_roles)), "focus": {"point": point, "aabb": aabb},
                 "candidates": _candidates(point, aabb, radius, list(group_roles), purpose, float(fov_degrees)),
                 "status": "not_fit" if too_large else "candidates_available",
                 "fit_status": "not_fit" if too_large else "candidate_region"}
        if missing:
            group["missing_bbox_roles"] = sorted(set(missing))
        groups.append(group)
        if too_large and len(group_roles) > 1 and ("relation" in purpose or purpose in {"joint_relation", "carried_relation", "nested_relation"}):
            identity_tokens = {"coffeemachine", "toaster", "sinkbasin", "faucet", "microwave", "stoveburner", "stoveknob", "knob"}
            device_roles = [a for a in group_roles if any(t in _object_identity(a, objects[a]) for t in identity_tokens)]
            content_roles = [a for a in group_roles if a not in device_roles]
            if device_roles:
                split_specs.append(("device_local", device_roles))
            if content_roles:
                split_specs.append(("contents_local", content_roles))
    existing_role_sets = {tuple(g["roles"]) for g in groups}
    for purpose, local_roles in split_specs:
        if tuple(local_roles) in existing_role_sets:
            continue
        point, aabb, missing, radius = _focus(local_roles, objects)
        if point is None or aabb is None:
            continue
        too_large = max(aabb["size"].values()) > 3.0
        groups.append({"group_id": f"{family}_{purpose}", "purpose": purpose, "roles": list(local_roles),
                       "required_state_roles": list(local_roles), "focus": {"point": point, "aabb": aabb},
                       "candidates": _candidates(point, aabb, radius, local_roles, purpose, float(fov_degrees)),
                       "status": "not_fit" if too_large else "candidates_available",
                       "fit_status": "not_fit" if too_large else "candidate_region",
                       **({"missing_bbox_roles": sorted(set(missing))} if missing else {})})
        existing_role_sets.add(tuple(local_roles))
    status = ("no_geometry" if not groups else
              "oversized_bounds" if oversized else
              "planned_with_position_fallbacks" if all_missing else "planned")
    notes = ["Candidate views are alternatives for one observed state; separate groups are complementary views of that same state.",
             "Frustum fit does not establish line of sight, absence of occlusion, or semantic readability."]
    if updated_roles:
        notes.append("Geometry was replanned from observed_metadata for roles: " + ", ".join(updated_roles) + ".")
    if all_missing:
        notes.append("Position-only fallback used where axisAlignedBoundingBox was unavailable: " + ", ".join(sorted(all_missing)) + ".")
    if not groups:
        notes.append("Relevant roles had neither usable bounds nor a finite position, so no camera pose can be computed.")
    if oversized:
        notes.append("A focus union is room-scale or oversized; split the evidence region before using these candidates.")
    return {"status": status, "family": family, "focus_roles": focus_roles, "groups": groups, "notes": notes}
