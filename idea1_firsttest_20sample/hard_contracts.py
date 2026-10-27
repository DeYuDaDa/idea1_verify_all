"""Instance-level mechanism contract checks; never creates model labels or Gold."""
from __future__ import annotations

from typing import Any


_EPS_M = 0.02


def _objects(snapshot: dict) -> dict[str, dict]:
    return {o["objectId"]: o for o in snapshot.get("objects", []) if o.get("objectId")}


def _role_obj(ctx: Any, snapshot: dict, alias: str) -> dict | None:
    return _objects(snapshot).get(getattr(ctx, "roles", {}).get(alias, alias))


def _temp(obj: dict | None):
    if not obj:
        return None
    return obj.get("temperature") if obj.get("temperature") is not None else obj.get("ObjectTemperature")


def _liquid(obj: dict | None):
    if not obj:
        return None
    if obj.get("isFilledWithLiquid") is False and obj.get("fillLiquid") in (None, ""):
        return "Empty"
    if obj.get("isFilledWithLiquid") is True:
        return {"water": "Water", "coffee": "Coffee"}.get(str(obj.get("fillLiquid") or "").lower())
    return None


def _relation(child_id: str, parent_id: str, rows: dict[str, dict]) -> bool | None:
    child, parent = rows.get(child_id), rows.get(parent_id)
    if child is None or parent is None:
        return None
    parents = child.get("parentReceptacles")
    children = parent.get("receptacleObjectIds")
    if not isinstance(parents, list) and not isinstance(children, list):
        return None
    return parent_id in (parents or []) or child_id in (children or [])


def _descendants(root_id: str, rows: dict[str, dict]) -> set[str] | None:
    """Return graph-reachable contents from native parent/child metadata."""
    if root_id not in rows:
        return None
    result, frontier = set(), [root_id]
    while frontier:
        parent_id = frontier.pop()
        parent = rows.get(parent_id)
        if parent is None:
            return None
        if parent.get("receptacle") is not True:
            return None
        children = parent.get("receptacleObjectIds")
        if not isinstance(children, list):
            return None
        candidates = set(children)
        for child_id, child in rows.items():
            parents = child.get("parentReceptacles")
            if isinstance(parents, list) and parent_id in parents:
                candidates.add(child_id)
        for child_id in candidates - result - {root_id}:
            if child_id not in rows:
                return None
            result.add(child_id)
            is_receptacle = rows[child_id].get("receptacle")
            if not isinstance(is_receptacle, bool):
                return None
            if is_receptacle:
                frontier.append(child_id)
    return result


def _displaced(before: dict | None, after: dict | None) -> bool | None:
    p, q = (before or {}).get("position"), (after or {}).get("position")
    if not isinstance(p, dict) or not isinstance(q, dict):
        return None
    try:
        distance = sum((float(p[k]) - float(q[k])) ** 2 for k in ("x", "y", "z")) ** 0.5
    except (KeyError, TypeError, ValueError):
        return None
    return distance > _EPS_M


def _check(name: str, passed: bool, detail: dict, *, status: str | None = None) -> dict:
    row = {"name": name, "passed": bool(passed), "detail": detail}
    if status:
        row["status"] = status
    return row


def _unavailable(name: str, reason: str, detail: dict | None = None) -> dict:
    return _check(name, False, {"reason": reason, **(detail or {})}, status="unavailable")


def _event_receipt(ctx: Any) -> list[dict]:
    event = getattr(ctx, "target_event", {}) or {}
    return [_check("target_event_native_success", event.get("success") is True,
                   {"target_event": event})]


def _validate_h01(ctx: Any, before: dict, after: dict) -> list[dict]:
    checks = _event_receipt(ctx)
    event = ctx.target_event
    target = event.get("subject")
    other = "B" if target == "A" else "A" if target == "B" else None
    if target not in {"A", "B"} or event.get("action") != "PutObject" or event.get("destination") != "M":
        return checks + [_unavailable("H01_target_identity", "target is not a Mug Put into role M")]
    machine_before, machine_after = _role_obj(ctx, before, "M"), _role_obj(ctx, after, "M")
    mug_before, mug_after = _role_obj(ctx, before, target), _role_obj(ctx, after, target)
    machine_pre_available = machine_before is not None and isinstance(machine_before.get("isToggled"), bool)
    checks.append(_check("H01_machine_precondition",
                         machine_pre_available and machine_before.get("isToggled") is True,
                         {"isToggled_before": None if machine_before is None else machine_before.get("isToggled")},
                         status=None if machine_pre_available else "unavailable"))
    if mug_before is None or mug_after is None:
        checks.append(_unavailable("H01_target_liquid", "target Mug metadata is missing"))
    else:
        old, new = _liquid(mug_before), _liquid(mug_after)
        expected = "Coffee" if old == "Empty" else old if old == "Water" else None
        known = expected is not None and new is not None
        checks.append(_check("H01_target_liquid_transition", expected is not None and new == expected,
                             {"before": old, "after": new, "conditioned_on_actual_before_state": True},
                             status=None if known else "unavailable"))
    if other:
        old_other, new_other = _liquid(_role_obj(ctx, before, other)), _liquid(_role_obj(ctx, after, other))
        checks.append(_check("H01_other_Mug_preserved", old_other is not None and new_other is not None
                             and new_other == old_other,
                             {"before": old_other, "after": new_other},
                             status=None if old_other is not None and new_other is not None else "unavailable"))
    if machine_after is None:
        checks.append(_unavailable("H01_machine_after", "post-event machine metadata is missing"))
    else:
        available = isinstance(machine_after.get("isToggled"), bool)
        checks.append(_check("H01_machine_remains_on", machine_after.get("isToggled") is True,
                             {"after": machine_after.get("isToggled")},
                             status=None if available else "unavailable"))
    return checks


def _validate_motion_group(ctx: Any, before: dict, after: dict, roles: tuple[str, ...]) -> list[dict]:
    checks = _event_receipt(ctx)
    target = (ctx.target_event or {}).get("subject")
    event = ctx.target_event or {}
    group = getattr(ctx, "group_id", "")
    valid_event = (event.get("action") == "PickupObject" and target in {"P", "Q"}
                   if group == "H02" else event.get("action") == "PickupObject" and target == "P")
    checks.append(_check("target_pickup_identity", valid_event,
                         {"group_id": group, "action": event.get("action"), "subject": target}))
    if not valid_event:
        return checks + [_unavailable("native_carrier_graph", "target pickup identity does not match this group")]
    root_id = ctx.roles.get(target)
    before_rows, after_rows = _objects(before), _objects(after)
    descendants = _descendants(root_id, before_rows) if root_id else None
    if descendants is None:
        return checks + [_unavailable("native_carrier_graph", "pre-event containment graph is incomplete")]
    expected = descendants | {root_id}
    for alias in roles:
        oid = ctx.roles.get(alias)
        if oid not in before_rows or oid not in after_rows:
            checks.append(_unavailable(f"{alias}_world_displacement", "before/after object metadata is missing"))
            continue
        changed = _displaced(before_rows[oid], after_rows[oid])
        if changed is None:
            checks.append(_unavailable(f"{alias}_world_displacement", "world position is unavailable"))
        else:
            should_move = oid in expected
            checks.append(_check(f"{alias}_world_displacement", changed is should_move,
                                 {"actual_changed": changed, "native_carrier_graph_predicts_changed": should_move,
                                  "graph_paths_are_not_claimed_unique": True}))
    return checks


def _validate_h03(ctx: Any, before: dict, after: dict) -> list[dict]:
    checks = _event_receipt(ctx)
    event = ctx.target_event or {}
    knob = event.get("subject")
    if event.get("action") != "ToggleObjectOn" or knob not in {"KA", "KB"}:
        return checks + [_unavailable("H03_target_knob", "target event is not a mapped knob activation")]
    before_rows, after_rows = _objects(before), _objects(after)
    knob_obj = _role_obj(ctx, before, knob)
    if knob_obj is None:
        return checks + [_unavailable("H03_control_mapping", "target knob metadata is missing")]
    controlled = []
    for row in knob_obj.get("controlledObjects") or []:
        controlled.append(row.get("objectId") if isinstance(row, dict) else row)
    targets = [name for name in ("BA", "BB") if ctx.roles.get(name) in controlled]
    if len(targets) != 1:
        return checks + [_unavailable("H03_control_mapping", "native controlledObjects mapping is unresolved",
                                      {"controlledObjects": controlled, "matched_roles": targets})]
    burner = targets[0]
    checks.append(_check("H03_control_mapping", True, {"knob": knob, "controlled_burner": burner}))
    burner_after = _role_obj(ctx, after, burner)
    knob_before = _role_obj(ctx, before, knob)
    knob_after = _role_obj(ctx, after, knob)
    burner_available = burner_after is not None and isinstance(burner_after.get("isToggled"), bool)
    checks.append(_check("H03_controlled_burner_turned_on",
                         burner_after is not None and burner_after.get("isToggled") is True,
                         {"burner": burner, "isToggled_after": None if burner_after is None else burner_after.get("isToggled")},
                         status=None if burner_available else "unavailable"))
    knob_available = knob_before is not None and isinstance(knob_before.get("isToggled"), bool)
    checks.append(_check("H03_target_knob_started_off",
                         knob_before is not None and knob_before.get("isToggled") is False,
                         {"knob": knob, "isToggled_before": None if knob_before is None else knob_before.get("isToggled")},
                         status=None if knob_available else "unavailable"))
    knob_after_available = knob_after is not None and isinstance(knob_after.get("isToggled"), bool)
    checks.append(_check("H03_target_knob_turned_on",
                         knob_after_available and knob_after.get("isToggled") is True,
                         {"knob": knob, "isToggled_after": None if knob_after is None else knob_after.get("isToggled")},
                         status=None if knob_after_available else "unavailable"))
    other_burner = "BB" if burner == "BA" else "BA"
    other_after = _role_obj(ctx, after, other_burner)
    other_available = other_after is not None and isinstance(other_after.get("isToggled"), bool)
    checks.append(_check("H03_unselected_burner_remained_off",
                         other_after is not None and other_after.get("isToggled") is False,
                         {"burner": other_burner,
                          "isToggled_after": None if other_after is None else other_after.get("isToggled")},
                         status=None if other_available else "unavailable"))
    for alias in ("X", "Y"):
        obj_before, obj_after = _role_obj(ctx, before, alias), _role_obj(ctx, after, alias)
        if obj_before is None or obj_after is None:
            checks.append(_unavailable(f"H03_{alias}_thermal", "container metadata is missing"))
            continue
        places = [name for name in ("BA", "BB")
                  if _relation(ctx.roles[alias], ctx.roles[name], before_rows) is True]
        if len(places) != 1:
            checks.append(_unavailable(f"H03_{alias}_thermal", "native burner parent is unavailable or ambiguous",
                                       {"matched_burners": places}))
            continue
        pre_temp, post_temp = _temp(obj_before), _temp(obj_after)
        baseline = pre_temp == "RoomTemp"
        heated = places[0] == burner
        expected_temp = "Hot" if heated else "RoomTemp"
        checks.append(_check(f"H03_{alias}_temperature",
                             baseline and post_temp == expected_temp,
                             {"native_burner": places[0], "controlled_burner": burner,
                              "before": pre_temp, "after": post_temp, "conditioned_on_native_contact": True},
                             status=None if pre_temp is not None and post_temp is not None else "unavailable"))
    return checks


def _validate_h05(ctx: Any, before: dict, after: dict) -> list[dict]:
    checks = _event_receipt(ctx)
    event = ctx.target_event or {}
    if event.get("action") != "ToggleObjectOn" or event.get("subject") != "Microwave":
        return checks + [_unavailable("H05_target_event", "target event is not Microwave activation")]
    mw_before, mw_after = _role_obj(ctx, before, "Microwave"), _role_obj(ctx, after, "Microwave")
    z_before, z_after = _role_obj(ctx, before, "Z"), _role_obj(ctx, after, "Z")
    mw_baseline_available = (mw_before is not None and isinstance(mw_before.get("isToggled"), bool)
                             and isinstance(mw_before.get("isOpen"), bool))
    checks.append(_check("H05_microwave_precondition",
                         mw_before is not None and mw_before.get("isToggled") is False and mw_before.get("isOpen") is False,
                         {"isToggled_before": None if mw_before is None else mw_before.get("isToggled"),
                          "isOpen_before": None if mw_before is None else mw_before.get("isOpen")},
                         status=None if mw_baseline_available else "unavailable"))
    mw_after_available = mw_after is not None and isinstance(mw_after.get("isToggled"), bool)
    if not mw_after_available or mw_after.get("isToggled") is not True:
        checks.append(_check("H05_microwave_turned_on", mw_after_available and mw_after.get("isToggled") is True,
                             {"isToggled_after": None if mw_after is None else mw_after.get("isToggled")},
                             status=None if mw_after_available else "unavailable"))
    else:
        checks.append(_check("H05_microwave_turned_on", True, {"isToggled_after": True}))
    if z_before is None or z_after is None:
        return checks + [_unavailable("H05_potato_outcome", "Potato metadata is missing")]
    before_rows = _objects(before)
    relation = _relation(ctx.roles["Z"], ctx.roles["Microwave"], before_rows)
    if relation is None:
        checks.append(_unavailable("H05_native_inside_outside", "pre-event Microwave relation is unavailable"))
        return checks
    old_cooked, new_cooked = z_before.get("isCooked"), z_after.get("isCooked")
    old_temp, new_temp = _temp(z_before), _temp(z_after)
    if relation:
        valid = old_temp == "RoomTemp" and new_temp == "Hot" and new_cooked is True
        expected = {"temperature": "Hot", "isCooked": True}
    else:
        valid = (old_temp == "RoomTemp" and new_temp == "RoomTemp" and old_cooked is not None
                 and new_cooked is old_cooked)
        expected = {"temperature": "RoomTemp", "isCooked": old_cooked}
    checks.append(_check("H05_potato_outcome_conditioned_on_native_location", valid,
                         {"inside_before": relation, "before": {"temperature": old_temp, "isCooked": old_cooked},
                          "after": {"temperature": new_temp, "isCooked": new_cooked},
                          "conditional_expectation": expected},
                         status=None if old_temp is not None and new_temp is not None
                         and old_cooked is not None and new_cooked is not None else "unavailable"))
    return checks


def validate_instance_contract(ctx: Any) -> list[dict]:
    """Check only instance-conditional predictions against observed native state.

    False checks describe this attempted instance, never a global mechanism
    refutation. Incomplete metadata is explicitly ``unavailable``.
    """
    before, after = getattr(ctx, "before_target", None), getattr(ctx, "after_target", None)
    if not isinstance(before, dict) or not isinstance(after, dict):
        return [_unavailable("instance_metadata", "before_target/after_target snapshots are unavailable")]
    group = getattr(ctx, "group_id", "")
    if group == "H01":
        return _validate_h01(ctx, before, after)
    if group == "H02":
        return _validate_motion_group(ctx, before, after, ("P", "Q", "X"))
    if group == "H03":
        return _validate_h03(ctx, before, after)
    if group == "H04":
        return _validate_motion_group(ctx, before, after, ("P", "B", "X"))
    if group == "H05":
        return _validate_h05(ctx, before, after)
    return [_unavailable("instance_group", f"unsupported group_id {group!r}")]

