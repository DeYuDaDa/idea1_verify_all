"""Add only the missing H01/H02 native inventory during private setup.

This helper deliberately uses CreateObjectAtLocation at bounded, metadata-derived
positions. Unlike InitialRandomSpawn, it does not reposition the scene's other
pickupable objects. Every addition is accepted only when the native receipt and
the post-action metadata both show a new, distinct object with the required
capabilities.
"""
from __future__ import annotations

import random
from typing import Any, Iterable


GROUP_REQUIREMENTS = {
    "H01": {"Mug": 2},
    "H02": {"Plate": 2},
}
REQUIRED_CAPABILITIES = {
    "Mug": ("canFillWithLiquid",),
    "Plate": ("pickupable", "receptacle"),
}
def _objects(metadata: Any) -> list[dict]:
    return [row for row in (metadata or {}).get("objects", []) if isinstance(row, dict)]


def _by_id(metadata: Any) -> dict[str, dict]:
    return {str(row["objectId"]): row for row in _objects(metadata)
            if row.get("objectId") is not None}


def _aabb(obj: dict) -> tuple[dict, dict] | None:
    box = obj.get("axisAlignedBoundingBox") or {}
    center, size = box.get("center"), box.get("size")
    if not isinstance(center, dict) or not isinstance(size, dict):
        return None
    try:
        return ({key: float(center[key]) for key in ("x", "y", "z")},
                {key: float(size[key]) for key in ("x", "y", "z")})
    except (KeyError, TypeError, ValueError):
        return None


def _type_rows(metadata: Any, object_type: str) -> list[dict]:
    unique = {}
    for row in _objects(metadata):
        oid = row.get("objectId")
        if row.get("objectType") == object_type and isinstance(oid, str):
            unique[oid] = row
    return list(unique.values())


def _capable_rows(metadata: Any, object_type: str) -> list[dict]:
    required = REQUIRED_CAPABILITIES[object_type]
    return [row for row in _type_rows(metadata, object_type)
            if all(row.get(cap) is True for cap in required)]


def _surface_candidates(metadata: Any, exemplar: dict, limit: int = 48) -> list[dict]:
    bounds = _aabb(exemplar)
    position = exemplar.get("position")
    if bounds is None or not isinstance(position, dict):
        return []
    center, size = bounds
    try:
        pivot_offset = {key: center[key] - float(position[key]) for key in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError):
        return []
    half_x, half_z = size["x"] / 2.0, size["z"] / 2.0
    step_x, step_z = max(size["x"] + 0.06, 0.16), max(size["z"] + 0.06, 0.16)
    points = []
    for surface in _objects(metadata):
        if surface.get("objectType") != "CounterTop" or surface.get("receptacle") is not True:
            continue
        surface_bounds = _aabb(surface)
        if surface_bounds is None:
            continue
        surf_center, surf_size = surface_bounds
        min_x, max_x = surf_center["x"] - surf_size["x"] / 2 + half_x + 0.025, surf_center["x"] + surf_size["x"] / 2 - half_x - 0.025
        min_z, max_z = surf_center["z"] - surf_size["z"] / 2 + half_z + 0.025, surf_center["z"] + surf_size["z"] / 2 - half_z - 0.025
        if min_x > max_x or min_z > max_z:
            continue
        xs, zs = [surf_center["x"]], [surf_center["z"]]
        offset = step_x
        while surf_center["x"] - offset >= min_x or surf_center["x"] + offset <= max_x:
            if surf_center["x"] - offset >= min_x:
                xs.append(surf_center["x"] - offset)
            if surf_center["x"] + offset <= max_x:
                xs.append(surf_center["x"] + offset)
            offset += step_x
        offset = step_z
        while surf_center["z"] - offset >= min_z or surf_center["z"] + offset <= max_z:
            if surf_center["z"] - offset >= min_z:
                zs.append(surf_center["z"] - offset)
            if surf_center["z"] + offset <= max_z:
                zs.append(surf_center["z"] + offset)
            offset += step_z
        top = surf_center["y"] + surf_size["y"] / 2.0
        y = top + size["y"] / 2.0 - pivot_offset["y"]
        for x in xs:
            for z in zs:
                if min_x - 1e-6 <= x <= max_x + 1e-6 and min_z - 1e-6 <= z <= max_z + 1e-6:
                    points.append({"position": {"x": x - pivot_offset["x"], "y": y,
                                                   "z": z - pivot_offset["z"]},
                                   "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                                   "surface_id": surface.get("objectId")})
    # Remove duplicate coordinates where multiple surfaces overlap.
    unique = {}
    for row in points:
        p = row["position"]
        unique.setdefault(tuple(round(p[k], 4) for k in ("x", "y", "z")), row)
    return list(unique.values())[:limit]


def _requirements(group_ids: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for group_id in group_ids:
        for object_type, count in GROUP_REQUIREMENTS.get(str(group_id), {}).items():
            result[object_type] = max(result.get(object_type, 0), count)
    return result


def ensure_native_inventory(session: Any, group_ids: Iterable[str], *, seed: int = 17,
                            history_started: bool = False) -> dict:
    """Ensure H01/H02 type counts with native additions before public history.

    ``group_ids`` contains H01 and/or H02. The function receives the *active
    controller session* (survey and case controllers must each call it in their
    own world) and never resets that session. Native placement is attempted
    only when metadata proves the exact type count is short.
    """
    requested_groups = sorted({str(value) for value in group_ids})
    requirements = _requirements(requested_groups)
    effective_history_started = bool(history_started or getattr(session, "history_started", False))
    result = {"schema": "hard-native-inventory/v1", "group_ids": requested_groups,
              "required_counts": requirements, "status": "already_sufficient",
              "history_started": effective_history_started, "types": {}, "action_receipts": []}
    if effective_history_started:
        result["status"] = "blocked_public_history"
        result["error"] = "Native inventory additions are forbidden after public history starts"
        return result

    before = session.snapshot()
    result["scene_name"] = before.get("sceneName")
    starting_action_index = len(getattr(session, "records", []))
    result["action_index_start"] = starting_action_index
    result["before_object_counts"] = {kind: len(_capable_rows(before, kind)) for kind in requirements}
    result["before_ids"] = {kind: sorted(row["objectId"] for row in _capable_rows(before, kind))
                             for kind in requirements}
    rng = random.Random(seed)
    any_added = False
    for object_type, required_count in requirements.items():
        if result["status"] in {"inventory_incomplete", "inventory_unavailable"}:
            break
        all_before_rows = _type_rows(before, object_type)
        before_rows = _capable_rows(before, object_type)
        state = {"required_count": required_count, "before_count": len(before_rows),
                 "before_ids": sorted(row["objectId"] for row in before_rows),
                 "added_ids": [], "attempts": [], "after_count": len(before_rows)}
        result["types"][object_type] = state
        if len(before_rows) >= required_count:
            continue
        if not all_before_rows:
            state["error"] = "Native create action requires this type to exist in the reset scene as a prefab exemplar"
            result["status"] = "inventory_unavailable"
            continue
        exemplar = (before_rows or all_before_rows)[0]
        missing = required_count - len(before_rows)
        placements = _surface_candidates(before, exemplar)
        rng.shuffle(placements)
        if not placements:
            state["error"] = "No bounded countertop/table native placement candidates fit the exemplar AABB"
            result["status"] = "inventory_unavailable"
            continue
        cursor = 0
        while len(state["added_ids"]) < missing and cursor < len(placements):
            candidate = placements[cursor]
            cursor += 1
            kwargs = {"objectType": object_type, "position": candidate["position"],
                      "rotation": candidate["rotation"], "objectVariation": 1,
                      "randomizeObjectAppearance": False, "forceAction": False}
            try:
                native = session.step("CreateObjectAtLocation", raise_on_failure=False, **kwargs)
                receipt = dict(native.record)
            except Exception as exc:
                receipt = {"action": "CreateObjectAtLocation", "kwargs": kwargs,
                           "lastActionSuccess": False,
                           "errorMessage": f"{type(exc).__name__}: {exc}"}
            post = session.snapshot()
            post_rows = _type_rows(post, object_type)
            post_by_id = {row["objectId"]: row for row in post_rows}
            # Existing ineligible objects are still old objects, not newly
            # created IDs. Count eligibility separately from provenance.
            before_ids = {row["objectId"] for row in all_before_rows}
            new_rows = [row for oid, row in post_by_id.items() if oid not in before_ids
                        and oid not in state["added_ids"]]
            receipt_check = {"record": receipt, "candidate_surface_id": candidate.get("surface_id"),
                             "new_distinct_ids": sorted(row["objectId"] for row in new_rows),
                             "post_count": len(post_rows), "capability_checks": {},
                             "status": "native_action_failed"}
            if receipt.get("lastActionSuccess") is not True:
                # A failed action that nevertheless changed inventory is kept
                # as diagnostic evidence; do not add more objects on top.
                if new_rows:
                    receipt_check["status"] = "failed_receipt_with_scene_change"
                    receipt_check["error"] = "Native action reported failure but metadata gained a distinct object"
                    state["attempts"].append(receipt_check)
                    state["error"] = receipt_check["error"]
                    result["status"] = "inventory_incomplete"
                    break
                state["attempts"].append(receipt_check)
                continue
            if len(new_rows) != 1:
                receipt_check["status"] = "unexpected_distinct_id_delta"
                receipt_check["error"] = f"Expected one new distinct {object_type} ID; observed {len(new_rows)}"
                state["attempts"].append(receipt_check)
                state["error"] = receipt_check["error"]
                result["status"] = "inventory_incomplete"
                break
            for row in new_rows:
                caps = {cap: row.get(cap) is True for cap in REQUIRED_CAPABILITIES[object_type]}
                receipt_check["capability_checks"][row["objectId"]] = caps
                if not all(caps.values()):
                    receipt_check["status"] = "created_object_ineligible"
                    receipt_check["error"] = f"New {object_type} failed native capability checks"
                    state["attempts"].append(receipt_check)
                    state["error"] = receipt_check["error"]
                    result["status"] = "inventory_incomplete"
                    break
                # Give the native containment metadata a bounded settling
                # interval, then verify both sides of the actual relation.
                settle_receipts = []
                for _ in range(4):
                    settle = session.step("Pass", raise_on_failure=False)
                    settle_receipts.append(dict(settle.record))
                    if settle.record.get("lastActionSuccess") is not True:
                        break
                receipt_check["settle_receipts"] = settle_receipts
                settled = session.snapshot()
                settled_by_id = _by_id(settled)
                actual = settled_by_id.get(row["objectId"])
                parent = settled_by_id.get(candidate.get("surface_id"))
                related = bool(actual and parent and
                               candidate["surface_id"] in (actual.get("parentReceptacles") or []) and
                               row["objectId"] in (parent.get("receptacleObjectIds") or []))
                receipt_check["post_settle_relation_verified"] = related
                if len(settle_receipts) != 4 or not all(r.get("lastActionSuccess") is True for r in settle_receipts) or not related:
                    receipt_check["status"] = "native_placement_relation_unverified"
                    receipt_check["error"] = "Four native Pass actions and bidirectional CounterTop relation were not verified"
                    state["attempts"].append(receipt_check)
                    state["error"] = receipt_check["error"]
                    result["status"] = "inventory_incomplete"
                    break
                state["added_ids"].append(row["objectId"])
                any_added = True
                receipt_check["status"] = "added_verified"
            receipt_check["verified_addition_ids"] = list(state["added_ids"])
            if not state["attempts"] or state["attempts"][-1] is not receipt_check:
                state["attempts"].append(receipt_check)
            if result["status"] == "inventory_incomplete":
                break
        after_rows = _capable_rows(session.snapshot(), object_type)
        state["after_count"] = len(after_rows)
        state["after_ids"] = sorted(row["objectId"] for row in after_rows)
        state["complete"] = (len(after_rows) >= required_count
                             and len(state["before_ids"]) + len(state["added_ids"]) >= required_count
                             and all(row_id in state["after_ids"]
                                     for row_id in state["before_ids"] + state["added_ids"]))
        if not state["complete"]:
            state["error"] = (f"Native additions yielded {len(after_rows)} distinct {object_type} objects; "
                               f"required {required_count}")
            result["status"] = "inventory_incomplete"

    result["after_object_counts"] = {kind: len(_capable_rows(session.snapshot(), kind))
                                     for kind in requirements}
    result["after_ids"] = {kind: sorted(row["objectId"] for row in _capable_rows(session.snapshot(), kind))
                            for kind in requirements}
    result["status"] = ("added_and_verified" if any_added and result["status"] == "already_sufficient"
                        else result["status"])
    if result["status"] == "already_sufficient" and any(
            result["after_object_counts"][kind] < count for kind, count in requirements.items()):
        result["status"] = "inventory_incomplete"
    result["action_receipts"] = [attempt["record"]
                                  for state in result["types"].values()
                                  for attempt in state.get("attempts", [])]
    result["action_receipts"].extend(receipt for state in result["types"].values()
                                     for attempt in state.get("attempts", [])
                                     for receipt in attempt.get("settle_receipts", []))
    result["action_index_end"] = len(getattr(session, "records", []))
    return result


__all__ = ["ensure_native_inventory"]
