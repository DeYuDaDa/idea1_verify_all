"""Bounded, native-only setup helpers for nested-relation probes.

This module never creates objects or edits metadata. Each failed candidate trial
is retained in the native action ledger, then the real scene is reset before a
new combination is attempted.
"""
from __future__ import annotations

from itertools import product
from typing import Any

from mechanism_probe_common import ProbeUnavailable


class NestedPlacementFailure(ProbeUnavailable):
    """A failed edge together with both native placement-path records."""
    def __init__(self, message: str, attempt: dict[str, Any]):
        super().__init__(message)
        self.attempt = attempt


def _size(obj: dict[str, Any]) -> tuple[float, float, float] | None:
    box = obj.get("axisAlignedBoundingBox") or {}
    size = box.get("size") or {}
    try:
        return tuple(float(size[k]) for k in ("x", "y", "z"))
    except (KeyError, TypeError, ValueError):
        return None


def _fits(inner: dict[str, Any], outer: dict[str, Any]) -> bool:
    a, b = _size(inner), _size(outer)
    # Missing native bounds do not authorize inventing dimensions; the native
    # placement attempt remains the final capacity/collision authority.
    return a is None or b is None or (a[0] <= b[0] * 1.15 and a[2] <= b[2] * 1.15)


def _relation(ctx: Any, child: str, parent: str) -> tuple[bool, dict[str, Any]]:
    child_obj, parent_obj = ctx.obj(child), ctx.obj(parent)
    parent_ids = child_obj.get("parentReceptacles") or []
    child_ids = parent_obj.get("receptacleObjectIds") or []
    return (ctx.roles[parent] in parent_ids and ctx.roles[child] in child_ids,
            {"child_parentReceptacles": parent_ids, "parent_receptacleObjectIds": child_ids})


def _candidates(ctx: Any, types: tuple[str, ...], caps: tuple[str, ...], exclude=()) -> list[dict]:
    excluded = {ctx.roles.get(x, x) for x in exclude}
    rows = [o for o in ctx.session.snapshot().get("objects", [])
            if o.get("objectType") in types and o.get("objectId") not in excluded
            and all(o.get(cap) is True for cap in caps)]
    type_order = {name: i for i, name in enumerate(types)}
    return sorted(rows, key=lambda o: (type_order[o["objectType"]], o["objectId"]))


def _reset(ctx: Any, scene: str, trial: int) -> None:
    ctx.session.reset(scene)
    # image=False snapshots the post-reset state and causes ProbeContext.flush
    # to preserve the previous action segment without moving the camera.
    ctx.capture(f"nested_setup_trial_{trial:02d}_scene_reset", image=False)


def _place_nested(ctx: Any, child: str, parent: str) -> dict[str, Any]:
    """Try point placement, then native pickup/put exactly once for this edge."""
    child_id, parent_id = ctx.roles.get(child, child), ctx.roles.get(parent, parent)
    attempt: dict[str, Any] = {"child": child, "parent": parent, "paths": []}
    try:
        results = ctx.move_setup(child, parent)
        attempt["paths"].append({"method": "PlaceObjectAtPoint", "status": "returned",
                                 "action_records": [getattr(item, "record", None) for item in results]})
        related, evidence = _relation(ctx, child, parent)
        attempt["paths"][-1].update({"relation_verified_both_directions": related,
                                     "native_relation": evidence})
        if related:
            attempt["selected_method"] = "PlaceObjectAtPoint"
            return attempt
        attempt["paths"][-1]["failure"] = "placement returned without both native relation directions"
    except (ProbeUnavailable, RuntimeError, ValueError, LookupError) as exc:
        attempt["paths"].append({"method": "PlaceObjectAtPoint", "status": "failed",
                                 "error": f"{type(exc).__name__}: {exc}"})

    pickup = getattr(ctx.ops, "pickup_event", None)
    put = getattr(ctx.ops, "put_event", None)
    if not callable(pickup) or not callable(put):
        attempt["fallback"] = {"status": "unavailable", "reason": "native pickup_event/put_event methods absent"}
        raise NestedPlacementFailure(f"F10 placement paths exhausted for {child}->{parent}: "
                                     f"{attempt['paths'][-1].get('error', attempt['paths'][-1].get('failure'))}; "
                                     "native PutObject fallback unavailable", attempt)

    inventory = ctx.session.inventory()
    attempt["fallback_inventory_before"] = copy_inventory = [
        item.get("objectId") if isinstance(item, dict) else item for item in inventory]
    if inventory:
        attempt["fallback"] = {"status": "unavailable", "reason": "agent inventory is not empty",
                                "inventory": copy_inventory}
        raise NestedPlacementFailure(f"F10 native PutObject fallback requires empty inventory: {copy_inventory!r}", attempt)
    child_obj, parent_obj = ctx.obj(child), ctx.obj(parent)
    if child_obj.get("pickupable") is not True or parent_obj.get("receptacle") is not True:
        attempt["fallback"] = {"status": "unavailable", "reason": "native capability precondition missing",
                                "child_pickupable": child_obj.get("pickupable"),
                                "parent_receptacle": parent_obj.get("receptacle")}
        raise NestedPlacementFailure(f"F10 native PutObject fallback capability precondition failed for {child}->{parent}", attempt)

    fallback: dict[str, Any] = {"status": "attempted", "pickup": None, "put": None}
    attempt["fallback"] = fallback
    try:
        pickup_result = pickup(child_id, look_first=False)
        fallback["pickup"] = getattr(pickup_result, "record", None)
        put_result = put(child_id, parent_id)
        fallback["put"] = getattr(put_result, "record", None)
        related, evidence = _relation(ctx, child, parent)
        fallback["relation_verified_both_directions"] = related
        fallback["native_relation"] = evidence
        if not related:
            raise ProbeUnavailable(f"Native PutObject did not establish both relation directions for {child}->{parent}")
        fallback["status"] = "succeeded"
        attempt["selected_method"] = "PickupObject+PutObject"
        return attempt
    except (ProbeUnavailable, RuntimeError, ValueError, LookupError) as exc:
        fallback["status"] = "failed"
        fallback["error"] = f"{type(exc).__name__}: {exc}"
        raise NestedPlacementFailure(f"F10 placement and native PutObject fallback failed for {child}->{parent}: "
                                     f"point_path={attempt['paths'][-1]!r}; fallback={fallback!r}", attempt) from exc


def establish_nested(ctx: Any, *, scene: str, roles: dict[str, str],
                     candidates: dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
                     edges: tuple[tuple[str, str], ...], max_trials: int = 12,
                     after_reset=None) -> dict:
    """Try bounded existing-object combinations, placing outer-to-inner.

    `edges` are ordered (child, parent) role pairs. Their order must run from
    the outer object's final support/location toward the innermost content.
    The `roles` map also carries semantic aliases such as source/basin.
    """
    lists = {role: _candidates(ctx, types, caps, exclude=tuple(k for k in roles if k != role))
             for role, (types, caps) in candidates.items()}
    empty = [role for role, rows in lists.items() if not rows]
    if empty:
        raise ProbeUnavailable(f"No native candidates for roles {empty}")
    combos = []
    for rows in product(*(lists[role] for role in candidates)):
        chosen = dict(zip(candidates, rows))
        if len({o["objectId"] for o in chosen.values()}) != len(chosen):
            continue
        by_role = {**roles, **{role: obj["objectId"] for role, obj in chosen.items()}}
        if all(_fits(chosen.get(child, ctx.obj(by_role[child])),
                     chosen.get(parent, ctx.obj(by_role[parent])))
               for child, parent in edges if child in by_role and parent in by_role):
            combos.append(chosen)
        if len(combos) >= max_trials:
            break
    if not combos:
        raise ProbeUnavailable("No distinct size-compatible native role combination within candidate inventory")

    failures = []
    for index, chosen in enumerate(combos, 1):
        if index > 1:
            _reset(ctx, scene, index)
            if after_reset is not None:
                after_reset(ctx)
        for role, obj in chosen.items():
            ctx.bind(role, obj["objectId"])
        attempt = {"trial": index,
                   "roles": {k: {"objectId": ctx.roles[k], "objectType": ctx.obj(k).get("objectType")}
                             for k in roles.keys() | candidates.keys()},
                   "placements": []}
        try:
            for child, parent in edges:
                if child == parent:
                    raise ProbeUnavailable(f"Invalid self containment role: {child}")
                try:
                    record = _place_nested(ctx, child, parent)
                except NestedPlacementFailure as exc:
                    attempt["placements"].append(exc.attempt)
                    ctx.check(f"nested_setup_{index:02d}_{child}_in_{parent}", False, exc.attempt)
                    raise
                attempt["placements"].append(record)
                related = record["paths"][-1].get("relation_verified_both_directions") if record.get("selected_method") == "PlaceObjectAtPoint" else record["fallback"].get("relation_verified_both_directions")
                attempt["placements"][-1]["relation_verified_both_directions"] = related
                ctx.check(f"nested_setup_{index:02d}_{child}_in_{parent}", bool(related), record)
                if not related:
                    raise ProbeUnavailable(f"Native relation not confirmed both ways: {child} -> {parent}")
            settle = ctx.ops.settle(steps=4)
            post_settle = []
            for child, parent in edges:
                related, evidence = _relation(ctx, child, parent)
                post_settle.append({"child": child, "parent": parent,
                                    "relation_verified_both_directions": related,
                                    "native_relation": evidence})
            attempt["post_settle_relations"] = post_settle
            attempt["settle_action_records"] = [getattr(item, "record", None) for item in settle]
            ctx.check(f"nested_setup_{index:02d}_full_chain_after_settle",
                      all(row["relation_verified_both_directions"] for row in post_settle), post_settle)
            if not all(row["relation_verified_both_directions"] for row in post_settle):
                raise ProbeUnavailable("Nested chain did not survive post-placement physics settling")
            ctx.check("nested_setup_candidate_search", True, {"attempts": failures + [attempt],
                                                                "candidate_trials_available": len(combos)})
            plan = {"selected_roles": attempt["roles"], "attempts": failures + [attempt],
                    "placement_order": [f"{child}->{parent}" for child, parent in edges],
                    "search_complete": True, "settle_action_records": attempt["settle_action_records"]}
            ctx.check("construction_plan", True, plan)
            return plan
        except (ProbeUnavailable, RuntimeError, ValueError, LookupError) as exc:
            attempt["failure"] = f"{type(exc).__name__}: {exc}"
            failures.append(attempt)
    ctx.check("nested_setup_candidate_search", False,
              {"attempts": failures, "candidate_trials_available": len(combos),
               "max_trials": max_trials})
    ctx.check("construction_plan", False,
              {"selected_roles": {}, "attempts": failures,
               "placement_order": [f"{child}->{parent}" for child, parent in edges],
               "search_complete": True})
    raise ProbeUnavailable(f"All {len(combos)} bounded native nested setup trials failed: {failures[-1]['failure']}")
