"""Prepare and natively verify the small H01/H02 inventory before public history.

AI2-THOR 5.0.0's InitialRandomSpawn duplicates scene instances through
``numDuplicatesOfType``. This native path preserves the cloned SimObjPhysics
behavior, but it also repositions existing pickupables and can rebuild IDs.
Consequently, old IDs are never used as evidence that a duplicate was added.
"""
from __future__ import annotations

from typing import Any, Iterable


GROUP_REQUIREMENTS = {
    "H01": {"Mug": 2},
    "H02": {"Plate": 2},
}
REQUIRED_CAPABILITIES = {
    "Mug": ("canFillWithLiquid",),
    "Plate": ("pickupable", "receptacle"),
}
STABILITY_PASSES = 3


def _objects(metadata: Any) -> list[dict]:
    return [row for row in (metadata or {}).get("objects", []) if isinstance(row, dict)]


def _type_rows(metadata: Any, object_type: str) -> list[dict]:
    # Count distinct current IDs, but do not compare IDs across InitialRandomSpawn:
    # the native scene setup can rebuild IDs while cloning/reparenting objects.
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


def _requirements(group_ids: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for group_id in group_ids:
        for object_type, count in GROUP_REQUIREMENTS.get(str(group_id), {}).items():
            result[object_type] = max(result.get(object_type, 0), count)
    return result


def _relation_report(metadata: Any, object_type: str) -> dict:
    """Check each object's parent link against the receptacle's child list."""
    by_id = {str(row["objectId"]): row for row in _objects(metadata)
             if row.get("objectId") is not None}
    checks = []
    for row in _type_rows(metadata, object_type):
        oid = str(row["objectId"])
        parents = row.get("parentReceptacles") or []
        reciprocal = [parent_id for parent_id in parents
                      if parent_id in by_id
                      and oid in (by_id[parent_id].get("receptacleObjectIds") or [])]
        checks.append({"object_id": oid, "parent_ids": list(parents),
                       "reciprocal_parent_ids": reciprocal,
                       "verified": bool(reciprocal)})
    links = sorted((row["object_id"], parent_id)
                   for row in checks for parent_id in row["reciprocal_parent_ids"])
    return {"checks": checks, "links": links,
            "verified": bool(checks) and all(row["verified"] for row in checks)}


def ensure_native_inventory(session: Any, group_ids: Iterable[str], *, seed: int = 17,
                            history_started: bool = False) -> dict:
    """Ensure requested H01/H02 inventory through one bounded native action.

    ``group_ids`` is usually one group. Survey and case worlds must invoke this
    independently on their own session. The function never resets the world.
    If every requested type already meets its capability-qualified target, it
    issues no native action. Otherwise, before public history, it calls
    ``InitialRandomSpawn`` once with target-total counts for only deficient
    types. This source action can reposition other scene pickupables and may
    rebuild object IDs; full snapshots and state-based checks are retained.
    """
    requested_groups = sorted({str(value) for value in group_ids})
    requirements = _requirements(requested_groups)
    effective_history_started = bool(history_started or getattr(session, "history_started", False))
    result = {"schema": "hard-native-inventory/v2", "group_ids": requested_groups,
              "required_counts": requirements, "status": "already_sufficient",
              "history_started": effective_history_started, "types": {},
              "action_receipts": [], "native_action": None,
              "native_source_contract": {
                  "action": "InitialRandomSpawn",
                  "numDuplicatesOfType_count_semantics": "target_total_count",
                  "may_reposition_existing_pickupables": True,
                  "object_ids_may_be_rebuilt": True,
              }}
    if effective_history_started:
        result["status"] = "blocked_public_history"
        result["error"] = "Native inventory additions are forbidden after public history starts"
        return result

    before = session.snapshot()
    result["scene_name"] = before.get("sceneName")
    result["before_snapshot"] = before
    result["action_index_start"] = len(getattr(session, "records", []))
    deficient = {}
    for object_type, required_count in requirements.items():
        rows = _type_rows(before, object_type)
        capable = _capable_rows(before, object_type)
        state = {"required_count": required_count,
                 "before_count": len(capable),
                 "before_ids": sorted(row["objectId"] for row in rows),
                 "before_capable_ids": sorted(row["objectId"] for row in capable),
                 "after_count": len(capable),
                 "capability_checks": {}, "relation_check": None}
        result["types"][object_type] = state
        if len(capable) < required_count:
            deficient[object_type] = required_count

    if not deficient:
        result["after_snapshot"] = before
        result["before_object_counts"] = {kind: state["before_count"]
                                           for kind, state in result["types"].items()}
        result["after_object_counts"] = dict(result["before_object_counts"])
        result["before_ids"] = {kind: state["before_capable_ids"]
                                 for kind, state in result["types"].items()}
        result["after_ids"] = dict(result["before_ids"])
        result["action_index_end"] = result["action_index_start"]
        return result

    missing_exemplars = [kind for kind in deficient if not _type_rows(before, kind)]
    no_duplicate_room = [kind for kind, target in deficient.items()
                         if len(_type_rows(before, kind)) >= target]
    if missing_exemplars or no_duplicate_room:
        result["status"] = "inventory_unavailable"
        reasons = []
        if missing_exemplars:
            reasons.append("no native exemplar exists for " + str(missing_exemplars))
        if no_duplicate_room:
            reasons.append("the target-total request cannot add a replacement for "
                           "capability-ineligible inventory in " + str(no_duplicate_room))
        result["error"] = ("InitialRandomSpawn duplicates existing scene instances; "
                            + "; ".join(reasons))
        result["after_snapshot"] = before
        _finish_counts(result, before)
        result["action_index_end"] = result["action_index_start"]
        return result

    result["status"] = "inventory_incomplete"
    result["deficient_types"] = dict(deficient)
    kwargs = {
        "randomSeed": int(seed),
        "forceVisible": True,
        "placeStationary": True,
        "numDuplicatesOfType": [
            {"objectType": object_type, "count": target_count}
            for object_type, target_count in sorted(deficient.items())
        ],
        "numPlacementAttempts": 5,
        "allowFloor": False,
        "allowMoveable": False,
    }
    try:
        native = session.step("InitialRandomSpawn", raise_on_failure=False, **kwargs)
        receipt = dict(native.record)
    except Exception as exc:
        receipt = {"action": "InitialRandomSpawn", "kwargs": kwargs,
                   "lastActionSuccess": False,
                   "errorMessage": f"{type(exc).__name__}: {exc}"}
    result["native_action"] = receipt
    result["action_receipts"].append(receipt)

    immediate = session.snapshot()
    result["immediate_after_snapshot"] = immediate
    if receipt.get("lastActionSuccess") is not True:
        result["error"] = "InitialRandomSpawn did not report native success"
        result["after_snapshot"] = immediate
        _finish_counts(result, immediate)
        result["action_index_end"] = len(getattr(session, "records", []))
        return result

    # InitialRandomSpawn may report success even when one or more objects could
    # not be placed. Let the native scene settle briefly, then independently
    # require count, capability and reciprocal relation evidence.
    settle_receipts = []
    for _ in range(STABILITY_PASSES):
        try:
            settle = session.step("Pass", raise_on_failure=False)
            settle_receipt = dict(settle.record)
            settle_receipts.append(settle_receipt)
            result["action_receipts"].append(settle_receipt)
        except Exception as exc:
            settle_receipt = {"action": "Pass", "lastActionSuccess": False,
                              "errorMessage": f"{type(exc).__name__}: {exc}"}
            settle_receipts.append(settle_receipt)
            result["action_receipts"].append(settle_receipt)
            break
    after = session.snapshot()
    result["after_snapshot"] = after
    result["settle_pass_count"] = len(settle_receipts)
    result["status"] = "added_and_verified"
    for object_type, required_count in requirements.items():
        rows = _type_rows(after, object_type)
        capable = _capable_rows(after, object_type)
        state = result["types"][object_type]
        state["after_count"] = len(capable)
        state["after_ids"] = sorted(row["objectId"] for row in capable)
        state["capability_checks"] = {
            str(row.get("objectId")): {
                cap: row.get(cap) is True for cap in REQUIRED_CAPABILITIES[object_type]
            } for row in rows
        }
        relation = _relation_report(after, object_type)
        immediate_relation = _relation_report(immediate, object_type)
        relation_stable = (len(settle_receipts) == STABILITY_PASSES
                           and all(row.get("lastActionSuccess") is True
                                   for row in settle_receipts)
                           and immediate_relation["verified"] and relation["verified"]
                           and immediate_relation["links"] == relation["links"])
        state["relation_check"] = {"immediate": immediate_relation,
                                   "after_settle": relation,
                                   "stable": relation_stable,
                                   "verified": relation["verified"] and relation_stable}
        state["count_verified"] = len(capable) >= required_count
        state["capabilities_verified"] = (len(rows) == len(capable)
                                           and len(capable) >= required_count)
        state["stability_verified"] = relation_stable
        state["complete"] = (state["count_verified"]
                             and state["capabilities_verified"]
                             and state["relation_check"]["verified"])
        if not state["complete"]:
            result["status"] = "inventory_incomplete"
            state["error"] = (
                f"Post-action count/capability/relation validation failed for {object_type}: "
                f"capable={len(capable)}, required={required_count}, "
                f"relations_verified={relation['verified']}"
            )

    _finish_counts(result, after)
    result["action_index_end"] = len(getattr(session, "records", []))
    if result["status"] != "added_and_verified":
        result["error"] = "Native inventory failed one or more independent post-action checks"
    return result


def _finish_counts(result: dict, metadata: Any) -> None:
    result["after_object_counts"] = {
        kind: len(_capable_rows(metadata, kind)) for kind in result["required_counts"]
    }
    result["after_ids"] = {
        kind: sorted(row["objectId"] for row in _capable_rows(metadata, kind))
        for kind in result["required_counts"]
    }
    result["before_object_counts"] = {
        kind: state["before_count"] for kind, state in result["types"].items()
    }
    result["before_ids"] = {
        kind: state["before_capable_ids"] for kind, state in result["types"].items()
    }
    for kind, state in result["types"].items():
        rows = _capable_rows(metadata, kind)
        state["after_count"] = len(rows)
        state["after_ids"] = sorted(row["objectId"] for row in rows)


__all__ = ["ensure_native_inventory"]
