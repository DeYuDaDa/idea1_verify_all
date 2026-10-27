"""Twenty conditional hard-history cases for native AI2-THOR execution.

Importing this module has no simulator side effects. All public-history changes
are ordinary native actions recorded by ``ControllerSession``. A caller may
override ``move(ctx, role, slot)`` through an optional ``group_spec`` only when
it has a calibrated native layout; the default uses verified existing
receptacles and native PickupObject/PutObject actions.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Callable


class HardConstructionError(RuntimeError):
    """The requested native state could not be constructed and verified."""


@dataclass(frozen=True)
class HardCase:
    case_id: str
    group_id: str
    family: str
    scene: str
    title: str
    run: Callable[[Any], Any]


def _phase(ctx: Any, label: str, *, public: bool = True, kind: str = "history"):
    ctx.phase(label, public=public, kind=kind)


def _waypoint_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("objectId") or value.get("object_id")
    return None


def _set_waypoint(ctx: Any, name: str, obj: dict) -> str:
    waypoint = dict(obj)
    waypoint["role_alias"] = name
    ctx.waypoints[name] = waypoint
    return str(obj["objectId"])


def _start(ctx: Any, note: str):
    ctx.public_declarations.append(note)
    ctx.start_history()


def _role(ctx: Any, alias: str, object_type: str, capability=None, *, exclude=()) -> str:
    try:
        return ctx.select(alias, object_type, capability=capability, exclude=exclude)
    except Exception as exc:
        raise HardConstructionError(f"Cannot bind existing {object_type} as {alias}: {exc}") from exc


def _move(ctx: Any, role: str, slot: str):
    """Move an existing object with native pickup/put; callback owns geometry."""
    adapter = getattr(ctx, "group_spec", None)
    move_override = adapter.get("move") if isinstance(adapter, dict) else getattr(adapter, "move", None)
    if move_override is not None:
        return move_override(ctx, role, slot)
    oid = ctx.roles[role]
    destination = ctx.roles.get(slot) or _waypoint_id(ctx.waypoints.get(slot))
    if not destination:
        raise HardConstructionError(f"No verified receptacle waypoint for {slot!r}")
    try:
        navigate = getattr(ctx, "navigate_to", None)
        if callable(navigate):
            navigate(oid, "beforepickup")
        ctx.ops.pickup_event(oid, look_first=False)
        if callable(navigate):
            navigate(destination, "beforeput")
        result = None
        attempts = []
        for offset in range(3):
            try:
                result = ctx.session.step("PutObject", objectId=destination, forceAction=True,
                                          placeStationary=True, randomSeed=ctx.ops.seed + offset,
                                          raise_on_failure=True)
                attempts.append({"seed": ctx.ops.seed + offset, "record": result.record, "error": None})
                if result.record.get("lastActionSuccess") is True:
                    break
            except Exception as exc:
                rows = getattr(ctx.session, "records", [])
                record = rows[-1] if rows else None
                attempts.append({"seed": ctx.ops.seed + offset, "record": record,
                                 "error": f"{type(exc).__name__}: {exc}"})
            # A failed native placement may have changed state. Retry only if
            # the same original object is still in the hand.
            held = any(item.get("objectId") == oid for item in ctx.session.inventory())
            if not held:
                break
        if result is None or result.record.get("lastActionSuccess") is not True:
            raise HardConstructionError(f"Native PutObject failed for {role} -> {slot}; attempts={attempts!r}")
        ctx.ops.settle(steps=4)
        child = ctx.obj(role)
        parent = ctx.obj(destination)
        related = destination in (child.get("parentReceptacles") or []) or oid in (parent.get("receptacleObjectIds") or [])
        ctx.check(f"native_move_{role}_{slot}", related,
                  {"child": child, "parent": parent, "put_attempts": attempts})
        if not related:
            raise HardConstructionError(f"Native PutObject did not establish {role} -> {slot}")
        return result
    except HardConstructionError:
        raise
    except Exception as exc:
        raise HardConstructionError(f"Native move {role} -> {slot} failed: {type(exc).__name__}: {exc}") from exc


def _surface_candidates(ctx: Any, *, exclude: tuple[str, ...] = ()) -> list[dict]:
    excluded = {ctx.roles.get(x, x) for x in exclude}
    rows = [o for o in ctx.session.snapshot().get("objects", [])
            if o.get("objectType") in {"CounterTop", "DiningTable", "KitchenIsland"}
            and o.get("receptacle") is True and o.get("objectId") not in excluded
            and isinstance(o.get("position"), dict)]
    return sorted(rows, key=lambda o: (float(o["position"].get("x", 0)),
                                        float(o["position"].get("z", 0)), o["objectId"]))


def _choose_waypoint(ctx: Any, name: str, *, exclude: tuple[str, ...] = (), far_from: str | None = None) -> str:
    existing = _waypoint_id(ctx.waypoints.get(name))
    if existing:
        return existing
    rows = _surface_candidates(ctx, exclude=exclude)
    if far_from:
        origin = ctx.obj(far_from).get("position")
        if isinstance(origin, dict):
            # Nearby candidates reduce path length and make native approach
            # feasible while the agent is carrying an object.  A farthest
            # arbitrary buffer can be unreachable from either burner.
            rows.sort(key=lambda o: math.dist(
                tuple(float(origin[k]) for k in ("x", "y", "z")),
                tuple(float(o["position"][k]) for k in ("x", "y", "z"))))
    if not rows:
        raise HardConstructionError(f"No existing native countertop/receptacle available for waypoint {name}")
    return _set_waypoint(ctx, name, rows[0])


def _choose_h03_buffer(ctx: Any) -> str:
    """Choose an existing surface close to both mapped burners."""
    rows = _surface_candidates(ctx, exclude=("BA", "BB"))
    positions = [ctx.obj(role).get("position") for role in ("BA", "BB")]
    if not rows or not all(isinstance(p, dict) for p in positions):
        raise HardConstructionError("H03 needs a native buffer and positions for both mapped burners")
    center = tuple((float(positions[0][key]) + float(positions[1][key])) / 2
                   for key in ("x", "y", "z"))
    rows.sort(key=lambda row: (math.dist(
        center, tuple(float(row["position"][key]) for key in ("x", "y", "z"))),
        str(row.get("objectId", ""))))
    return _set_waypoint(ctx, "buffer", rows[0])


def _native_setup_place(ctx: Any, role: str, slot: str):
    """Prehistory placement through the existing bounded native placement helper."""
    oid = ctx.roles[role]
    parent = ctx.roles.get(slot) or _waypoint_id(ctx.waypoints.get(slot))
    if not parent:
        raise HardConstructionError(f"Missing setup receptacle for {role} -> {slot}")
    obj = ctx.obj(role)
    if parent in (obj.get("parentReceptacles") or []):
        return
    if ctx.session.inventory():
        raise HardConstructionError("Setup placement requires empty native hand inventory")
    try:
        ctx.ops.place_initial(oid, parent)
        ctx.ops.settle(steps=4)
    except Exception as exc:
        raise HardConstructionError(f"Native prehistory placement {role} -> {slot} failed: {exc}") from exc
    if parent not in (ctx.obj(role).get("parentReceptacles") or []):
        raise HardConstructionError(f"Prehistory placement did not verify {role} -> {slot}")


def _calibrate_forward(ctx: Any, role: str, origin: str, destination: str,
                       *, restore_to: str | None = None):
    """Exercise a required native placement, then restore with setup placement."""
    if not _relation(ctx, role, origin):
        raise HardConstructionError(f"Cannot calibrate {role}: expected native origin {origin} is absent")
    _move(ctx, role, destination)
    if not _relation(ctx, role, destination):
        raise HardConstructionError(f"Calibration placement {role} -> {destination} was not verified")
    restore_to = restore_to or origin
    _native_setup_place(ctx, role, restore_to)
    if not _relation(ctx, role, restore_to):
        raise HardConstructionError(f"Setup restoration failed to restore {role} -> {restore_to}")


def _native_toggle(ctx: Any, role: str, on: bool):
    return ctx.ops.set_toggle(ctx.roles[role], on)


def _native_transfer(ctx: Any, role: str, destination: str):
    return _move(ctx, role, destination)


def _find_h03_mappings(ctx: Any) -> list[tuple[str, str]]:
    by_id = {o.get("objectId"): o for o in ctx.session.snapshot().get("objects", [])}
    pairs = []
    for knob in sorted((o for o in by_id.values() if o.get("objectType") == "StoveKnob"),
                       key=lambda row: str(row.get("objectId", ""))):
        for entry in knob.get("controlledObjects") or []:
            target_id = entry.get("objectId") if isinstance(entry, dict) else entry
            target = by_id.get(target_id)
            pair = (knob.get("objectId"), target_id)
            if target and target.get("objectType") == "StoveBurner" and pair not in pairs:
                pairs.append(pair)
    distinct = []
    for pair in pairs:
        if not any(pair[0] == old[0] or pair[1] == old[1] for old in distinct):
            distinct.append(pair)
    return distinct


def _prepare_h03_native(ctx: Any, variant: int):
    mappings = _find_h03_mappings(ctx)
    if len(mappings) < 2:
        raise HardConstructionError(f"H03 needs two distinct native knob-to-burner mappings; found {mappings!r}")
    (ka, ba), (kb, bb) = mappings[:2]
    for alias, oid in (("KA", ka), ("BA", ba), ("KB", kb), ("BB", bb)):
        ctx.bind(alias, oid)
        _set_waypoint(ctx, alias, ctx.obj(alias))
    _role(ctx, "X", "Kettle", "pickupable")
    _role(ctx, "Y", "Pot", "pickupable", exclude=("X",))
    all_knobs = [o for o in ctx.session.snapshot().get("objects", [])
                 if o.get("objectType") == "StoveKnob" and o.get("toggleable") is True]
    for knob in all_knobs:
        if knob.get("isToggled") is True:
            ctx.ops.set_toggle(knob["objectId"], False)
    ctx.require(all(ctx.obj(row["objectId"]).get("isToggled") is False for row in all_knobs),
                "H03 could not establish all native stove knobs off before history")
    _choose_h03_buffer(ctx)
    _native_setup_place(ctx, "X", "BA")
    _native_setup_place(ctx, "Y", "BB")
    for role in ("X", "Y"):
        if _temperature(ctx.obj(role)) != "RoomTemp":
            raise HardConstructionError(f"H03 needs {role} at native RoomTemp before history")
    # Calibrate the same six native moves as one swap plus restoration. This
    # includes the cross-burner placements Y->BA and X->BB that buffer-only
    # roundtrips would miss.
    _h03_native_cycle(ctx, "swap", public=False)
    _h03_native_cycle(ctx, "restore", public=False)
    ctx.require(_relation(ctx, "X", "BA") and _relation(ctx, "Y", "BB"),
                "H03 native endpoint preflight did not restore burner assignments")
    if any(_temperature(ctx.obj(role)) != "RoomTemp" for role in ("X", "Y")):
        raise HardConstructionError("H03 endpoint calibration changed a container temperature")


def _h03_native_cycle(ctx: Any, cycle: str, *, public: bool = True):
    if cycle in {"swap", "swap_again"}:
        _move(ctx, "X", "buffer")
        _move(ctx, "Y", "BA")
        _move(ctx, "X", "BB")
    elif cycle == "restore":
        _move(ctx, "Y", "buffer")
        _move(ctx, "X", "BA")
        _move(ctx, "Y", "BB")
    else:
        raise HardConstructionError(f"Unknown H03 placement cycle {cycle!r}")
    ctx.phase("H03历史换位后稳定等待（4次原生Pass）", public=public, kind="history")
    _settle(ctx, 4)
    ctx.require(not ctx.session.inventory(), f"H03 {cycle} left an object held")
    ctx.require(all(ctx.obj(k).get("isToggled") is False for k in ("KA", "KB")),
                f"H03 {cycle} requires all mapped burners off")
    ctx.require(all(_temperature(ctx.obj(role)) == "RoomTemp" for role in ("X", "Y")),
                f"H03 {cycle} failed to retain RoomTemp baselines with heat sources off")


def _relation(ctx: Any, child: str, parent: str) -> bool:
    parent_id = ctx.roles.get(parent) or _waypoint_id(ctx.waypoints.get(parent))
    child_id = ctx.roles.get(child, child)
    if not parent_id:
        return False
    child_obj = ctx.obj(child_id)
    parent_obj = ctx.obj(parent_id)
    return (parent_id in (child_obj.get("parentReceptacles") or [])
            or child_id in (parent_obj.get("receptacleObjectIds") or []))


def _distance_xz(a: dict, b: dict) -> float | None:
    pa, pb = a.get("position"), b.get("position")
    if not isinstance(pa, dict) or not isinstance(pb, dict):
        return None
    try:
        return math.dist((float(pa["x"]), float(pa["z"])), (float(pb["x"]), float(pb["z"])))
    except (KeyError, TypeError, ValueError):
        return None


def _liquid(ctx: Any, role: str, value: str | None):
    try:
        result = ctx.ops.set_liquid(ctx.roles[role], value)
        actual = ctx.obj(role)
        expected_filled = value is not None
        valid = actual.get("isFilledWithLiquid") is expected_filled
        if value is not None:
            valid = valid and str(actual.get("fillLiquid") or "").lower() == value
        else:
            valid = valid and actual.get("fillLiquid") in (None, "")
        ctx.check(f"liquid_{role}_{value or 'empty'}", valid, {"state": actual, "action": result.record})
        if not valid:
            raise HardConstructionError(f"Liquid metadata did not verify for {role}")
        return result
    except HardConstructionError:
        raise
    except Exception as exc:
        raise HardConstructionError(f"Native liquid operation for {role} failed: {exc}") from exc


def _settle(ctx: Any, steps: int = 4):
    return ctx.ops.settle(steps=steps)


def _snapshot(ctx: Any, aliases: tuple[str, ...]) -> dict:
    return {name: ctx.obj(name) for name in aliases}


def _sample_observation_window(ctx: Any, observation_passes: tuple[int, ...]) -> tuple[list[dict], int]:
    """Sample at true cumulative Pass offsets; Pass 0 is the immediate state."""
    started = time.monotonic()
    samples = []
    if not observation_passes:
        total = 4
        ctx.phase("target observation settle window before Pass 1-4", public=True, kind="observation")
        _settle(ctx, steps=total)
        samples.append({"pass": total, "elapsed_wall_seconds": time.monotonic() - started,
                        "metadata": _snapshot(ctx, tuple(ctx.roles))})
        return samples, total

    offsets = sorted({0, *(int(n) for n in observation_passes if int(n) >= 0)})
    ctx.phase("target immediate observation at Pass 0", public=True, kind="observation")
    samples.append({"pass": 0, "elapsed_wall_seconds": time.monotonic() - started,
                    "metadata": _snapshot(ctx, tuple(ctx.roles))})
    last_pass = 0
    for target_pass in (offset for offset in offsets if offset > 0):
        ctx.phase(f"target observation advancing from Pass {last_pass} to Pass {target_pass}",
                  public=True, kind="observation")
        while last_pass < target_pass:
            ctx.step("Pass")
            last_pass += 1
        samples.append({"pass": target_pass, "elapsed_wall_seconds": time.monotonic() - started,
                        "metadata": _snapshot(ctx, tuple(ctx.roles))})
    return samples, last_pass


def _target_event(ctx: Any, action: str, subject: str, destination: str | None = None,
                  *, observation_passes: tuple[int, ...] = ()):
    """Record truthful target event fields, including failures and native receipt."""
    # Keep all bound roles so displacement and location queries can be derived
    # against the same event boundary, including non-target carried contents.
    # Navigation is a native pre-event operation.  Complete it before freezing
    # the event-time state so navigation-induced motion cannot leak into the
    # measured target boundary.
    navigate = getattr(ctx, "navigate_to", None)
    if callable(navigate):
        phases = getattr(ctx, "executed_phases", None)
        target_label = None
        if phases and phases[-1].get("kind") == "target":
            target_label = phases[-1].get("label")
            ctx.phase("目标事件前原生接近", public=True, kind="history")
        if action == "PutObject" and destination is not None:
            navigate(ctx.roles[destination], "beforeput")
        elif action == "PickupObject":
            navigate(ctx.roles[subject], "beforepickup")
        elif action == "ToggleObjectOn":
            navigate(ctx.roles[subject], "beforeinteract")
        if target_label is not None:
            ctx.phase(target_label, public=True, kind="target")
    before = ctx.session.snapshot()
    ctx.before_target = before
    ctx.before_target_roles = _snapshot(ctx, tuple(ctx.roles))
    row = {"action": action, "subject": subject, "destination": destination,
           "attempted": True, "success": False, "native_action_success": False,
           "postcondition_verified": False, "record": None, "error": None}
    ctx.target_frozen = True
    try:
        try:
            if action == "PutObject":
                result = ctx.ops.put_event(ctx.roles[subject], ctx.roles[destination])
            elif action == "PickupObject":
                result = ctx.ops.pickup_event(ctx.roles[subject], look_first=False)
            elif action == "ToggleObjectOn":
                result = ctx.ops.set_toggle(ctx.roles[subject], True)
            else:
                raise ValueError(f"Unsupported target event action {action}")
            row["record"] = result.record
            row["success"] = result.record.get("lastActionSuccess") is True
            row["native_action_success"] = row["success"]
            row["postcondition_verified"] = True
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            records = getattr(ctx.session, "records", [])
            if records:
                last = records[-1]
                expected_object = ctx.roles.get(destination) if action == "PutObject" else ctx.roles.get(subject)
                kwargs = last.get("kwargs") if isinstance(last.get("kwargs"), dict) else {}
                if last.get("action") == action and kwargs.get("objectId") == expected_object:
                    row["record"] = last
                    row["native_action_success"] = last.get("lastActionSuccess") is True
                    # The operation wrapper raised (often because native
                    # success was followed by a failed relation check), so the
                    # target construction remains failed even with a receipt.
                    row["success"] = False
    finally:
        ctx.target_frozen = False
    samples, total_passes = _sample_observation_window(ctx, observation_passes)
    ctx.after_target = ctx.session.snapshot()
    ctx.after_target_roles = _snapshot(ctx, tuple(ctx.roles))
    row["observed_after"] = ctx.after_target
    row["observation_samples"] = samples
    row["observation_total_passes"] = total_passes
    row["event_index"] = (row.get("record") or {}).get("index")
    ctx.target_event = row
    ctx.check("target_event_success", row["success"], row)
    return row


def _questions(ctx: Any, rows: list[dict]):
    # These are public question specifications only. Gold labels are derived by
    # the exporter from real metadata; no plan expectation is inserted here.
    ctx.questions.extend(rows)


def _q(subject: str, predicate: str, answer_mode: str, question: str):
    return {"subject": subject, "predicate": predicate,
            "answer_mode": answer_mode, "question": question}


def _h01(ctx: Any, variant: int):
    _role(ctx, "A", "Mug", "canFillWithLiquid")
    _role(ctx, "B", "Mug", "canFillWithLiquid", exclude=("A",))
    _role(ctx, "M", "CoffeeMachine")
    _phase(ctx, "H01 prehistory slot and identity calibration", public=False, kind="setup")
    slots = _surface_candidates(ctx)
    if len(slots) < 2:
        raise HardConstructionError("H01 needs two distinct existing external parking receptacles")
    _set_waypoint(ctx, "A_park", slots[0])
    _set_waypoint(ctx, "B_park", slots[1])
    _native_setup_place(ctx, "A", "A_park")
    _native_setup_place(ctx, "B", "B_park")
    _native_toggle(ctx, "M", False)
    _calibrate_forward(ctx, "A", "A_park", "M")
    _calibrate_forward(ctx, "B", "B_park", "M")
    _liquid(ctx, "A", None)
    _liquid(ctx, "B", None)
    ctx.initial_metadata = ctx.session.snapshot()
    _start(ctx, "公开规则：咖啡机接触时，空杯是否变为咖啡须由本次实际结果验证；杯中液体状态不从隐藏标签推断。")
    _phase(ctx, "H01 initial identity and empty baseline")
    # Each variant follows the complete, visible interleaving from the plan.
    if variant == 1:
        sequence = (("A", "water"), ("B", "water"), ("A", None), ("B", None), ("B", "water"))
        target = "A"
    elif variant == 2:
        sequence = (("B", "water"), ("A", "water"), ("B", None), ("A", None), ("A", "water"))
        target = "A"
    elif variant == 3:
        sequence = (("B", "water"), ("A", "water"), ("B", None), ("A", None), ("A", "water"))
        target = "B"
    else:
        sequence = (("A", "water"), ("B", "water"), ("A", None), ("B", None), ("B", "water"))
        target = "B"
    for index, (role, liquid) in enumerate(sequence, 1):
        _phase(ctx, f"H01 history liquid operation {index}: {role} -> {liquid or 'empty'}")
        _liquid(ctx, role, liquid)
        _settle(ctx, 1)
    _phase(ctx, "H01 machine enabled before target")
    ctx.ops.set_toggle(ctx.roles["M"], True)
    _phase(ctx, f"H01 pickup target {target}")
    navigate = getattr(ctx, "navigate_to", None)
    if callable(navigate):
        navigate(ctx.roles[target], "beforepickup")
    ctx.ops.pickup_event(ctx.roles[target], look_first=False)
    planned_before = {"A": "Empty", "B": "Water"} if variant in (1, 4) else {"A": "Water", "B": "Empty"}
    for role, value in planned_before.items():
        actual = derive_answer({"subject": role, "predicate": "liquid"}, ctx.session.snapshot(), ctx)
        ctx.require(actual == value, f"H01 history/pickup lost the intended event-time liquid condition for {role}: {actual}")
    _phase(ctx, f"H01 target PutObject {target} into M", kind="target")
    _target_event(ctx, "PutObject", target, "M")
    _questions(ctx, [
        _q("A", "liquid", "enum:Empty|Water|Coffee", "A 杯现在是空的、装水还是装咖啡？"),
        _q("B", "liquid", "enum:Empty|Water|Coffee", "B 杯现在是空的、装水还是装咖啡？"),
        _q("A", "location", "semantic_location", "A 杯现在在哪里？"),
        _q("B", "location", "semantic_location", "B 杯现在在哪里？"),
        _q("M", "isToggled", "boolean", "咖啡机现在开启了吗？"),
    ])


def _h02(ctx: Any, variant: int):
    _role(ctx, "P", "Plate", ("pickupable", "receptacle"))
    _role(ctx, "Q", "Plate", ("pickupable", "receptacle"), exclude=("P",))
    _role(ctx, "X", "Apple", "pickupable")
    surfaces = _surface_candidates(ctx)
    if len(surfaces) < 4:
        raise HardConstructionError("H02 requires native left, right, apple-staging, and plate-buffer receptacles")
    for name, row in zip(("left", "right", "apple_staging", "plate_buffer"), surfaces[:4]):
        _set_waypoint(ctx, name, row)
    _native_setup_place(ctx, "P", "left")
    _native_setup_place(ctx, "Q", "right")
    _native_setup_place(ctx, "X", "P")
    initial_left = _distance_xz(ctx.obj("P"), ctx.waypoints["left"])
    initial_right = _distance_xz(ctx.obj("Q"), ctx.waypoints["right"])
    p_position, q_position = ctx.obj("P").get("position", {}), ctx.obj("Q").get("position", {})
    initial_order_ok = (initial_left is not None and initial_right is not None
                        and float(p_position.get("x", math.inf)) < float(q_position.get("x", -math.inf))
                        and _relation(ctx, "X", "P"))
    ctx.check("h02_initial_identity_and_support", initial_order_ok,
              {"P_to_left": initial_left, "Q_to_right": initial_right,
               "P": ctx.obj("P"), "Q": ctx.obj("Q"), "X": ctx.obj("X")})
    ctx.require(initial_order_ok, "H02 initial plate positions or Apple-on-P relation are not verified")
    _phase(ctx, "H02 prehistory slot and identity calibration", public=False, kind="setup")
    # Preflight the actual ordered native construction for this variant, then
    # use setup placements to restore the baseline. Do not test a placement
    # onto a plate while that destination still contains the other plate.
    for role, slot in (("X", "Q"), ("X", "P"), ("X", "apple_staging"),
                       ("P", "plate_buffer"), ("Q", "left"), ("P", "right")):
        _move(ctx, role, slot)
    _move(ctx, "X", "P" if variant in (1, 4) else "Q")
    _native_setup_place(ctx, "X", "apple_staging")
    _native_setup_place(ctx, "P", "plate_buffer")
    _native_setup_place(ctx, "Q", "right")
    _native_setup_place(ctx, "P", "left")
    _native_setup_place(ctx, "X", "P")
    ctx.require(_relation(ctx, "X", "P") and _relation(ctx, "P", "left")
                and _relation(ctx, "Q", "right")
                and float(ctx.obj("P")["position"]["x"]) < float(ctx.obj("Q")["position"]["x"]),
                "H02 prehistory endpoint calibration did not restore the initial placements")
    _start(ctx, "公开身份规则：P、Q 沿用初始物体身份；左、右位置变化不能重命名物体。")
    _phase(ctx, "H02 initial native placement")
    ctx.initial_metadata = ctx.session.snapshot()
    for role, slot in (("X", "Q"), ("X", "P"), ("X", "apple_staging"),
                       ("P", "plate_buffer"), ("Q", "left"), ("P", "right")):
        _phase(ctx, f"H02 history move {role} -> {slot}")
        _move(ctx, role, slot)
    p_right = _distance_xz(ctx.obj("P"), ctx.waypoints["right"])
    p_left = _distance_xz(ctx.obj("P"), ctx.waypoints["left"])
    q_left = _distance_xz(ctx.obj("Q"), ctx.waypoints["left"])
    q_right = _distance_xz(ctx.obj("Q"), ctx.waypoints["right"])
    swapped_positions_ok = (None not in (p_right, p_left, q_left, q_right)
                            and p_right < p_left and q_left < q_right
                            and _relation(ctx, "P", "right") and _relation(ctx, "Q", "left"))
    ctx.check("h02_actual_plate_swap_positions", swapped_positions_ok,
              {"P_to_right": p_right, "P_to_left": p_left,
               "Q_to_left": q_left, "Q_to_right": q_right})
    ctx.require(swapped_positions_ok, "H02 native placements did not establish the intended spatial swap")
    apple_parent = "P" if variant in (1, 4) else "Q"
    target = "P" if variant in (1, 2) else "Q"
    _phase(ctx, f"H02 return Apple to {apple_parent}")
    _move(ctx, "X", apple_parent)
    ctx.require(_relation(ctx, "X", apple_parent), f"H02 final Apple support by {apple_parent} was not verified")
    _phase(ctx, f"H02 target PickupObject {target}", kind="target")
    _target_event(ctx, "PickupObject", target)
    _questions(ctx, [_q(r, "world_position_changed", "boolean", f"{r} 是否因最后一次拿起而改变了世界位置？")
                     for r in ("P", "Q", "X")])


def _h03(ctx: Any, variant: int):
    # Fixed scene/layout are delegated to calibrated binding, not inferred from
    # object names or left/right positions.
    _prepare_h03_native(ctx, variant)
    _start(ctx, "公开声明：两容器初始室温；炉头—旋钮对应关系按本实例校准记录。")
    _phase(ctx, "H03 verify controls, room-temperature baselines, and all burners off")
    ctx.public_declarations.append("BA/BB 与 KA/KB 的映射使用本实例校准记录；不能按名称或空间位置猜测。")
    ctx.require(all(_temperature(ctx.obj(r)) == "RoomTemp" for r in ("X", "Y")),
                "H03 prehistory requires both containers at RoomTemp")
    ctx.initial_metadata = ctx.session.snapshot()
    swapped_last = variant in (2, 4)
    for cycle in ("swap", "restore") + (("swap_again",) if swapped_last else ()):
        _phase(ctx, f"H03 history placement cycle {cycle}")
        _h03_native_cycle(ctx, cycle)
    expected_slots = (("X", "BB"), ("Y", "BA")) if swapped_last else (("X", "BA"), ("Y", "BB"))
    for child, burner in expected_slots:
        ctx.require(_relation(ctx, child, burner), f"H03 final placement {child} on mapped burner {burner} not verified")
    knob = "KA" if variant in (1, 2) else "KB"
    _phase(ctx, f"H03 target ToggleObjectOn {knob}", kind="target")
    _target_event(ctx, "ToggleObjectOn", knob, observation_passes=(0, 1, 4, 12, 36, 72))
    rows = [_q(knob, "isToggled", "boolean", f"{knob} 现在开启了吗？"),
            _q("BA", "isToggled", "boolean", "炉头 BA 现在开启了吗？"),
            _q("BB", "isToggled", "boolean", "炉头 BB 现在开启了吗？")]
    for role in ("X", "Y"):
        rows.append(_q(role, "temperature", "enum:Hot|Cold|RoomTemp", f"{role} 现在是什么温度？"))
    for role in ("X", "Y"):
        rows.append(_q(role, "location", "semantic_location", f"{role} 现在位于哪个炉头或周转位置？"))
    _questions(ctx, rows)


def _h04(ctx: Any, variant: int):
    # Setup is intentionally completed before public history; nested_setup
    # retains native placement receipts and fails closed if an edge is absent.
    surfaces = _surface_candidates(ctx)
    if len(surfaces) < 2:
        raise HardConstructionError("H04 requires an existing support surface and a distinct external surface")
    ctx.bind("support", surfaces[0]["objectId"])
    _set_waypoint(ctx, "h04_external", surfaces[1])
    try:
        from nested_setup import establish_nested
        establish_nested(ctx, scene=ctx.session.scene,
                         roles={"support": ctx.roles["support"]},
                         candidates={"outer": (("Plate",), ("pickupable", "receptacle")),
                                     "inner": (("Bowl",), ("pickupable", "receptacle")),
                                     "content": (("Apple",), ("pickupable",))},
                         edges=(("outer", "support"), ("inner", "outer"),
                                ("content", "inner")), max_trials=6)
    except Exception as exc:
        raise HardConstructionError(f"Native prehistory nested setup failed: {type(exc).__name__}: {exc}") from exc
    for alias, nested_role in (("P", "outer"), ("B", "inner"), ("X", "content")):
        ctx.bind(alias, ctx.roles[nested_role])
    # Calibrate only the forward sequence required by this variant. Restore
    # with setup placement so preflight does not invent extra public-history
    # PutObject routes.
    if variant in (1, 2):
        _move(ctx, "X", "h04_external")
        if variant == 1:
            _move(ctx, "X", "B")
        else:
            _native_setup_place(ctx, "X", "B")
    else:
        _move(ctx, "B", "h04_external")
        if variant == 4:
            _move(ctx, "X", "P")
            _native_setup_place(ctx, "X", "B")
        _native_setup_place(ctx, "B", "P")
    if not (_relation(ctx, "B", "P") and _relation(ctx, "X", "B")):
        raise HardConstructionError("H04 prehistory endpoint calibration did not restore the nested chain")
    _start(ctx, "公开身份规则：P 是外盘、B 是碗、X 是苹果；只按实际成功的原生搬运更新位置。")
    _phase(ctx, "H04 verify nested starting chain")
    ctx.initial_metadata = ctx.session.snapshot()
    if variant in (1, 2):
        _phase(ctx, "H04 remove Apple from Bowl")
        _move(ctx, "X", "h04_external")
        if variant == 1:
            _phase(ctx, "H04 return same Apple to Bowl")
            _move(ctx, "X", "B")
    elif variant in (3, 4):
        _phase(ctx, "H04 move Bowl with Apple to external surface")
        _move(ctx, "B", "h04_external")
        if variant == 4:
            _phase(ctx, "H04 attempt Apple direct reattachment to Plate")
            _move(ctx, "X", "P")  # preserve native rejection in the action ledger
    intact = _relation(ctx, "B", "P") and _relation(ctx, "X", "B")
    apple_out = _relation(ctx, "B", "P") and _relation(ctx, "X", "h04_external") and not _relation(ctx, "X", "B")
    bundle_out = (_relation(ctx, "B", "h04_external") and _relation(ctx, "X", "B")
                  and not _relation(ctx, "B", "P") and not _relation(ctx, "X", "P"))
    reparented = (_relation(ctx, "B", "h04_external") and _relation(ctx, "X", "P")
                  and not _relation(ctx, "X", "B") and not _relation(ctx, "B", "P"))
    ctx.require({1: intact, 2: apple_out, 3: bundle_out, 4: reparented}[variant],
                "H04 did not preserve the intended current internal/external relations before target pickup")
    _phase(ctx, "H04 target PickupObject P", kind="target")
    _target_event(ctx, "PickupObject", "P")
    _questions(ctx, [_q(r, "world_position_changed", "boolean", f"{r} 是否在最后拿起外盘时改变了世界位置？")
                     for r in ("P", "B", "X")])


def _temperature(obj: dict) -> Any:
    return obj.get("temperature") if obj.get("temperature") is not None else obj.get("ObjectTemperature")


def _poll_temperature_cook(ctx: Any, *, cooked_required: bool, timeout: float = 20.0,
                          max_passes: int = 400, label: str = "H05 natural heating") -> list[dict]:
    started = time.monotonic()
    trace = []
    for n in range(max_passes + 1):
        obj = ctx.obj("Z")
        sample = {"pass": n, "elapsed_wall_seconds": time.monotonic() - started,
                  "temperature": _temperature(obj), "isCooked": obj.get("isCooked")}
        if n % 20 == 0 or n == 0 or sample["temperature"] == "Hot" or sample["isCooked"] is True:
            trace.append(sample)
        if sample["temperature"] == "Hot" and (not cooked_required or sample["isCooked"] is True):
            ctx.check(label, True, {"trace": trace, "passes": n,
                                    "elapsed_wall_seconds": time.monotonic() - started})
            return trace
        if time.monotonic() - started >= timeout or n >= max_passes:
            break
        ctx.step("Pass")
        time.sleep(0.05)
    ctx.check(label, False, {"trace": trace, "passes": min(max_passes, n),
                             "elapsed_wall_seconds": time.monotonic() - started,
                             "wall_time_is_not_simulated_time": True})
    raise HardConstructionError(f"{label} did not reach the required state in the bounded window")


def _natural_cool_h05(ctx: Any) -> dict:
    started = time.monotonic()
    deadline = started + 45.0
    trace = []
    passes = 0
    while _temperature(ctx.obj("Z")) != "RoomTemp" and passes < 1500 and time.monotonic() < deadline:
        result = ctx.step("Pass")
        passes += 1
        if passes % 20 == 0 or passes == 1 or _temperature(ctx.obj("Z")) != _temperature(trace[-1]["metadata"] if trace else {}):
            trace.append({"pass": passes, "metadata": ctx.obj("Z"), "record": result.record})
        time.sleep(0.05)
    elapsed = time.monotonic() - started
    cooled = _temperature(ctx.obj("Z")) == "RoomTemp" and ctx.obj("Z").get("isCooked") is True
    result = {"samples": trace, "passes": passes, "elapsed_wall_seconds": elapsed,
              "cooled_to_room_temp": _temperature(ctx.obj("Z")) == "RoomTemp",
              "cooked_retained": ctx.obj("Z").get("isCooked") is True}
    ctx.check("natural_cooling_trace", cooled, result)
    ctx.cooling_trace = result
    if not cooled:
        raise HardConstructionError("Natural cooling did not reach RoomTemp while retaining cooked state")
    return result


def _prepare_h05_native(ctx: Any, variant: int):
    _role(ctx, "Z", "Potato", ("pickupable", "cookable"))
    _role(ctx, "Microwave", "Microwave", ("toggleable", "openable", "receptacle"))
    surfaces = _surface_candidates(ctx)
    if len(surfaces) < 2:
        raise HardConstructionError("H05 requires separate native cooling C and final exterior E positions")
    _set_waypoint(ctx, "cooling_C", surfaces[0])
    _set_waypoint(ctx, "final_E", surfaces[1])
    ctx.ops.set_toggle(ctx.roles["Microwave"], False)
    ctx.ops.set_open(ctx.roles["Microwave"], True)
    z = ctx.obj("Z")
    if z.get("isCooked") is not False or _temperature(z) != "RoomTemp":
        raise HardConstructionError("H05 native reset must provide an uncooked RoomTemp Potato")
    if _relation(ctx, "Z", "Microwave"):
        _native_transfer(ctx, "Z", "cooling_C")
    else:
        _native_setup_place(ctx, "Z", "cooling_C")
    ctx.ops.settle(steps=4)


def _h05_cook_history_native(ctx: Any):
    _native_transfer(ctx, "Z", "Microwave")
    ctx.ops.set_open(ctx.roles["Microwave"], False)
    ctx.ops.set_toggle(ctx.roles["Microwave"], True)
    _poll_temperature_cook(ctx, cooked_required=True, timeout=20.0, max_passes=400)
    ctx.ops.set_toggle(ctx.roles["Microwave"], False)
    ctx.ops.set_open(ctx.roles["Microwave"], True)
    _native_transfer(ctx, "Z", "cooling_C")
    _natural_cool_h05(ctx)


def _h05(ctx: Any, variant: int):
    _prepare_h05_native(ctx, variant)
    _calibrate_forward(ctx, "Z", "cooling_C", "Microwave")
    _calibrate_forward(ctx, "Z", "cooling_C", "final_E")
    ctx.require(ctx.obj("Z").get("isCooked") is False
                and _temperature(ctx.obj("Z")) == "RoomTemp"
                and _relation(ctx, "Z", "cooling_C"),
                "H05 endpoint calibration did not restore the uncooked RoomTemp baseline")
    _start(ctx, "公开温度前提：最终测试阶段的室温基线已通过本次原生 metadata 确认；不预告土豆熟度或最终内外位置。")
    _phase(ctx, "H05 baseline uncooked and RoomTemp")
    state = ctx.obj("Z")
    ctx.require(state.get("isCooked") is False and _temperature(state) == "RoomTemp",
                "H05 requires native reset potato uncooked and at RoomTemp")
    ctx.initial_metadata = ctx.session.snapshot()
    if variant in (2, 4):
        _phase(ctx, "H05 real microwave cook history: put in, close, turn on")
        _h05_cook_history_native(ctx)
        ctx.require(ctx.obj("Z").get("isCooked") is True,
                    "Natural microwave history did not verify isCooked=True")
        _phase(ctx, "H05 natural cook history completed; temperature and cooked state rechecked")
        ctx.require(_temperature(ctx.obj("Z")) == "RoomTemp" and ctx.obj("Z").get("isCooked") is True,
                    "Potato did not naturally cool to RoomTemp while retaining cooked state")
    else:
        _phase(ctx, "H05 uncooked history: microwave remains off, put in and remove")
        ctx.ops.set_open(ctx.roles["Microwave"], True)
        _native_transfer(ctx, "Z", "Microwave")
        _native_transfer(ctx, "Z", "cooling_C")
    final_inside = variant in (1, 2)
    _phase(ctx, "H05 place at final inside/outside position and close appliance")
    _native_transfer(ctx, "Z", "Microwave" if final_inside else "final_E")
    ctx.ops.set_open(ctx.roles["Microwave"], False)
    final = ctx.obj("Z")
    ctx.require(final.get("isCooked") is (variant in (2, 4)) and _temperature(final) == "RoomTemp",
                "H05 final pre-event temperature/cooked metadata failed validation")
    location_ok = _relation(ctx, "Z", "Microwave") if final_inside else (
        not _relation(ctx, "Z", "Microwave") and
        (_waypoint_id(ctx.waypoints.get("final_E")) in (final.get("parentReceptacles") or [])
         or ctx.roles["Z"] in (ctx.obj(_waypoint_id(ctx.waypoints.get("final_E"))).get("receptacleObjectIds") or [])))
    ctx.require(location_ok, "H05 final inside/outside position did not verify from native metadata")
    ctx.require(ctx.obj("Microwave").get("isToggled") is False and ctx.obj("Microwave").get("isOpen") is False,
                "H05 microwave must be off and closed before the final target event")
    ctx.require(not ctx.session.inventory(), "H05 final positioning left an object held")
    ctx.public_declarations.append("已逐题公开最终阶段土豆室温基线确认；熟度仍依据历史与真实 metadata。")
    _phase(ctx, "H05 target ToggleObjectOn Microwave", kind="target")
    _target_event(ctx, "ToggleObjectOn", "Microwave", observation_passes=(0, 1, 4, 12, 36, 72, 120))
    _questions(ctx, [
        _q("Microwave", "isToggled", "boolean", "微波炉现在开启了吗？"),
        _q("Z", "temperature", "enum:Hot|Cold|RoomTemp", "土豆现在是什么温度？"),
        _q("Z", "isCooked", "boolean", "土豆现在熟了吗？"),
        _q("Z", "location", "semantic_location", "土豆现在位于微波炉内还是炉外？"),
    ])


def cases() -> list[HardCase]:
    """Return the 20 ordered H01-1..H05-4 records specified by the plan."""
    result: list[HardCase] = []
    for n in range(1, 5):
        result.append(HardCase(f"H01-{n}", "H01", "liquid_interleaving", "FloorPlan1",
                               f"双杯液体交错历史 {n}", lambda ctx, n=n: _h01(ctx, n)))
    for n in range(1, 5):
        result.append(HardCase(f"H02-{n}", "H02", "support_and_position_swap", "FloorPlan2",
                               f"双盘换位与苹果承载 {n}", lambda ctx, n=n: _h02(ctx, n)))
    for n in range(1, 5):
        result.append(HardCase(f"H03-{n}", "H03", "burner_control_after_swap", "FloorPlan2",
                               f"炉头旋钮映射与容器换位 {n}", lambda ctx, n=n: _h03(ctx, n)))
    for n in range(1, 5):
        result.append(HardCase(f"H04-{n}", "H04", "nested_relation_history", "FloorPlan1",
                               f"嵌套移出与恢复 {n}", lambda ctx, n=n: _h04(ctx, n)))
    for n in range(1, 5):
        result.append(HardCase(f"H05-{n}", "H05", "cooking_and_position_history", "FloorPlan1",
                               f"熟度与炉内外位置交叉 {n}", lambda ctx, n=n: _h05(ctx, n)))
    return result


def _position(obj: dict) -> dict | None:
    p = obj.get("position")
    if not isinstance(p, dict):
        return None
    try:
        return {k: float(p[k]) for k in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError):
        return None


def derive_answer(question: dict, metadata: dict, ctx: Any, *, before: dict | None = None) -> Any:
    """Derive one factual answer from actual metadata; unavailable stays unknown.

    Position-change uses Euclidean displacement > 0.02 m to ignore small
    simulator settling jitter. Location is returned only when an actual direct
    parent maps to a recorded semantic waypoint; otherwise it is unknown.
    """
    role = question.get("subject")
    predicate = question.get("predicate")
    objects = metadata.get("objects", []) if isinstance(metadata, dict) else []
    oid = getattr(ctx, "roles", {}).get(role, role)
    obj = next((o for o in objects if o.get("objectId") == oid), None)
    if not obj:
        return None
    if predicate == "liquid":
        if obj.get("isFilledWithLiquid") is False and obj.get("fillLiquid") in (None, ""):
            return "Empty"
        if obj.get("isFilledWithLiquid") is True:
            liquid = str(obj.get("fillLiquid") or "").lower()
            return {"water": "Water", "coffee": "Coffee"}.get(liquid)
        return None
    if predicate in {"isToggled", "isCooked"}:
        value = obj.get(predicate)
        return value if isinstance(value, bool) else None
    if predicate == "temperature":
        return _temperature(obj)
    if predicate == "world_position_changed":
        old_rows = before if before is not None else getattr(ctx, "before_target", {})
        if isinstance(old_rows, dict) and isinstance(old_rows.get("objects"), list):
            old = next((row for row in old_rows["objects"] if row.get("objectId") == oid), None)
        else:
            old = old_rows.get(role) if isinstance(old_rows, dict) else None
        p0, p1 = _position(old or {}), _position(obj)
        if p0 is None or p1 is None:
            return None
        return math.dist(tuple(p0.values()), tuple(p1.values())) > 0.02
    if predicate == "location":
        parents = obj.get("parentReceptacles")
        if not isinstance(parents, list):
            return None
        by_id = {row.get("objectId"): row for row in objects if row.get("objectId")}
        aliases: dict[str, list[tuple[str, str]]] = {}
        for name, parent_id in getattr(ctx, "roles", {}).items():
            if parent_id in parents and parent_id != oid:
                aliases.setdefault(parent_id, []).append(("role", name))
        for name, waypoint in getattr(ctx, "waypoints", {}).items():
            parent_id = _waypoint_id(waypoint)
            if parent_id in parents and parent_id != oid:
                aliases.setdefault(parent_id, []).append(("waypoint", name))
        if not aliases:
            return None

        def is_ancestor(ancestor_id: str, child_id: str) -> bool:
            ancestor, child = by_id.get(ancestor_id), by_id.get(child_id)
            if ancestor_id in ((child or {}).get("parentReceptacles") or []):
                return True
            if child_id in ((ancestor or {}).get("receptacleObjectIds") or []):
                return True
            return False

        candidate_ids = set(aliases)
        # parentReceptacles can list the whole ancestry chain. Remove an
        # ancestor only when the live native object graph confirms the edge.
        ancestors = {candidate for candidate in candidate_ids
                     if any(candidate != other and is_ancestor(candidate, other)
                            for other in candidate_ids)}
        most_specific = candidate_ids - ancestors
        if len(most_specific) != 1:
            return None
        selected_id = next(iter(most_specific))
        names = aliases[selected_id]
        task_role_order = ("A", "B", "M", "P", "Q", "X", "Y", "BA", "BB",
                           "KA", "KB", "Microwave", "Z")
        role_names = [name for kind, name in names if kind == "role"]
        if role_names:
            return min(role_names, key=lambda name: task_role_order.index(name)
                       if name in task_role_order else len(task_role_order))
        waypoint_names = sorted({name for _, name in names})
        return waypoint_names[0] if len(waypoint_names) == 1 else None
    return None

