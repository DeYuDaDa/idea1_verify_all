"""Native AI2-THOR probes for the unverified F1-F6 thermal/liquid claims.

Each case observes natural simulator events. CookObject, FillObjectWithLiquid,
EmptyLiquidFromObject, DirtyObject and CleanObject are used only to construct
explicit pre-event states; they are never treated as evidence for the tested
heat, water-contact or coffee-fill mechanism.
"""
from __future__ import annotations

from typing import Any

from mechanism_probe_common import ProbeCase, ProbeUnavailable, native_temperature


def _bind(ctx: Any, alias: str, object_type: str, *, capability: str | None = None,
          exclude: tuple[str, ...] = ()) -> str:
    try:
        object_id = ctx.select(alias, object_type, capability=capability, exclude=exclude)
    except Exception as exc:
        raise ProbeUnavailable(f"setup_failed: missing {object_type} for {alias}: {exc}") from exc
    ctx.bind(alias, object_id)
    return object_id


def _parents(ctx: Any, alias: str) -> list[str]:
    value = ctx.obj(alias).get("parentReceptacles") or []
    return sorted(str(item) for item in value)


def _state(ctx: Any, alias: str, fields: tuple[str, ...]) -> dict[str, Any]:
    # ctx.obj is the declared stable interface and includes actual current geometry.
    obj = ctx.obj(alias)
    result: dict[str, Any] = {}
    result["object_id"] = obj.get("objectId")
    result["object_type"] = obj.get("objectType")
    result["position"] = obj.get("position")
    result["axisAlignedBoundingBox"] = obj.get("axisAlignedBoundingBox")
    result["parentReceptacles"] = _parents(ctx, alias)
    for field in fields:
        result[field] = ctx.field(alias, field)
    return result


def _record(ctx: Any, label: str, aliases: tuple[str, ...], fields: dict[str, tuple[str, ...]],
            *, observe: bool = True) -> dict[str, Any]:
    shots = ctx.observe() if observe else []
    latest: dict[str, Any] = {}
    for alias in aliases:
        latest[alias] = _state(ctx, alias, fields.get(alias, ()))
    return {"label": label, "observations": shots, "latest": latest}


def _changed(before: dict[str, Any], after: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: {"before": before.get(key), "after": after.get(key),
                  "changed": before.get(key) != after.get(key)} for key in keys}


def _natural_step(ctx: Any, action: str, **kwargs: Any) -> dict[str, Any]:
    """Run one tested native event; failed actions are logged as inconclusive."""
    try:
        result = ctx.step(action, **kwargs)
        return {"success": True, "action": action,
                "record": getattr(result, "record", None)}
    except Exception as exc:  # A rejected native event is not a mechanism counterexample.
        records = getattr(ctx.session, "records", [])
        return {"success": False, "action": action, "error": str(exc),
                "record": records[-1] if records else None}


def _put_natural(ctx: Any, child_alias: str, parent_alias: str) -> dict[str, Any]:
    """Use the interaction wrapper's audited native PutObject path."""
    try:
        result = ctx.put_event(child_alias, parent_alias)
        return {"success": True, "action": "PutObject",
                "record": getattr(result, "record", None)}
    except Exception as exc:
        records = getattr(ctx.session, "records", [])
        return {"success": False, "action": "PutObject", "error": str(exc),
                "record": records[-1] if records else None}


def _status_from_effect(effect: bool | None) -> str:
    if effect is True:
        return "observed_supported"
    if effect is False:
        return "observed_counterexample"
    return "inconclusive"


def _setup_call(ctx: Any, description: str, fn: Any) -> Any:
    try:
        return fn()
    except ProbeUnavailable:
        raise
    except Exception as exc:
        raise ProbeUnavailable(f"setup_failed: {description}: {type(exc).__name__}: {exc}") from exc


def _prepare_microwave(ctx: Any, food_alias: str, food_type: str = "Potato") -> tuple[str, str]:
    microwave_id = _bind(ctx, "Microwave", "Microwave", capability="toggleable")
    food_id = _bind(ctx, food_alias, food_type, capability="pickupable")
    _setup_call(ctx, "microwave off", lambda: ctx.ops.set_toggle(microwave_id, False))
    _setup_call(ctx, "microwave open for setup", lambda: ctx.ops.set_open(microwave_id, True))
    return microwave_id, food_id


def _ensure_bread_slices(ctx: Any, count: int) -> list[str]:
    """Use an existing Bread and native SliceObject only when slices are absent."""
    aliases = [f"Bread_{i + 1}" for i in range(count)]
    ids: list[str] = []
    missing = 0
    for alias in aliases:
        try:
            object_id = ctx.select(alias, "BreadSliced", capability="pickupable", exclude=ids)
        except ProbeUnavailable:
            missing += 1
            break
        ctx.bind(alias, object_id)
        ids.append(object_id)
    if missing:
        try:
            bread_id = ctx.select("WholeBread_setup", "Bread", capability="sliceable")
            created = ctx.ops.slice_object(bread_id)
            if created:
                ctx.check("native_slicing_created_existing_inventory_objects", True,
                          {"source_id": bread_id, "returned_ids": created})
        except Exception as exc:
            raise ProbeUnavailable(f"setup_failed: no sufficient BreadSliced inventory and native slicing failed: {exc}") from exc
        for alias in aliases[len(ids):]:
            try:
                object_id = ctx.select(alias, "BreadSliced", capability="pickupable", exclude=ids)
            except ProbeUnavailable as exc:
                raise ProbeUnavailable(f"setup_failed: native slicing did not provide {count} usable BreadSliced objects") from exc
            ctx.bind(alias, object_id)
            ids.append(object_id)
    return aliases


def _f1_run(order: str):
    def run(ctx: Any) -> dict[str, Any]:
        toaster_id = _bind(ctx, "Toaster", "Toaster", capability="toggleable")
        _ensure_bread_slices(ctx, 1)
        ctx.bind("Bread", ctx.roles["Bread_1"])
        _setup_call(ctx, "toaster starts off", lambda: ctx.ops.set_toggle(toaster_id, False))
        ctx.require(ctx.obj("Bread").get("isCooked") is False, "uncooked bread slice unavailable")
        _bind(ctx, "Counter", "CounterTop", capability="receptacle")
        _setup_call(ctx, "stage bread outside inactive toaster", lambda: ctx.move_setup("Bread", "Counter"))
        ctx.require(ctx.field("Bread", "temperature") == "RoomTemp",
                    "RoomTemp bread baseline unavailable for trigger-order probe")
        if order == "enter_then_activate":
            pre = ctx.capture("bread_outside_before_entry")
            _setup_call(ctx, "hold bread before tested PutObject", lambda: ctx.pickup("Bread"))
            before_entry = ctx.capture("after_pickup_before_entry")
            entry = _put_natural(ctx, "Bread", "Toaster")
            between = ctx.capture("after_entry_before_activation")
            event = {"success": entry["success"], "action": "PutObject", "record": entry.get("record")}
            if entry["success"]:
                event["following_toggle"] = _natural_step(ctx, "ToggleObjectOn", objectId=toaster_id, forceAction=True)
            trigger = "PutObject_then_ToggleObjectOn"
        else:
            pre = ctx.capture("bread_outside_before_activation")
            event = _natural_step(ctx, "ToggleObjectOn", objectId=toaster_id, forceAction=True)
            between = ctx.capture("after_activation_before_pickup_and_entry")
            trigger = "ToggleObjectOn_then_PutObject"
            if event["success"]:
                _setup_call(ctx, "hold bread before tested PutObject", lambda: ctx.pickup("Bread"))
                before_entry = ctx.capture("after_pickup_before_entry")
                event["following_put_event"] = _put_natural(ctx, "Bread", "Toaster")
            else:
                before_entry = None
        after = _record(ctx, "after_ordered_actions", ("Toaster", "Bread"),
                        {"Toaster": ("isToggled",),
                         "Bread": ("ObjectTemperature", "isCooked")})
        before_obj = next((o for o in pre.get("metadata", {}).get("objects", [])
                           if o.get("objectId") == ctx.obj("Bread")["objectId"]), {})
        before = {"ObjectTemperature": native_temperature(before_obj), "isCooked": before_obj.get("isCooked")}
        current = after["latest"]["Bread"]
        effect = (current.get("ObjectTemperature") not in (None, before["ObjectTemperature"]) or
                  current.get("isCooked") is True and before.get("isCooked") is not True)
        complete = (event.get("success") and event.get("following_toggle", {"success": True}).get("success")
                    and event.get("following_put_event", {"success": True}).get("success"))
        ctx.check("ordered_native_actions_succeeded", complete is True,
                  {"order": order, "event": event})
        ctx.check("ordered_actions_produced_heating_or_cooking", complete is True and effect,
                  {"trigger_actions": trigger, "before": before, "after": current,
                   "observation_trace": after["observations"]})
        status = _status_from_effect(effect if complete else None)
        if complete and not effect:
            status = "inconclusive"  # delayed/conditional heating needs longer observation.
        return {"status": status, "fact_id": "F1", "condition": order,
                "trigger_actions": trigger, "pre_event_snapshot": pre,
                "between_event_snapshots": [between], "before_entry": before_entry,
                "event": event, "after": after,
                "field_changes": _changed(before, current, ("ObjectTemperature", "isCooked")),
                "interpretation": "Order-specific observation only; this case does not establish the opposite order."}
    return run


def _f1_microwave(order: str):
    def run(ctx: Any) -> dict[str, Any]:
        microwave_id = _bind(ctx, "Microwave", "Microwave", capability="toggleable")
        potato_id = _bind(ctx, "Potato", "Potato", capability="pickupable")
        _bind(ctx, "Counter", "CounterTop", capability="receptacle")
        _setup_call(ctx, "microwave off before order probe", lambda: ctx.ops.set_toggle(microwave_id, False))
        _setup_call(ctx, "open microwave for setup", lambda: ctx.ops.set_open(microwave_id, True))
        ctx.require(ctx.obj("Potato").get("isCooked") is False, "uncooked potato unavailable")
        ctx.require(ctx.field("Potato", "temperature") is not None, "potato temperature metadata unavailable")
        ctx.require(ctx.field("Potato", "temperature") == "RoomTemp", "RoomTemp potato baseline unavailable before order probe")
        _setup_call(ctx, "stage potato outside microwave", lambda: ctx.move_setup("Potato", "Counter"))
        if order == "enter_then_activate":
            pre = ctx.capture("potato_outside_before_entry")
            _setup_call(ctx, "hold potato before tested PutObject", lambda: ctx.pickup("Potato"))
            before_entry = ctx.capture("after_pickup_before_entry")
            entry = _put_natural(ctx, "Potato", "Microwave")
            between = ctx.capture("after_entry_before_close_and_activation")
            close = _natural_step(ctx, "CloseObject", objectId=microwave_id, forceAction=True) if entry["success"] else {"success": False, "skipped": True}
            toggle = _natural_step(ctx, "ToggleObjectOn", objectId=microwave_id, forceAction=True) if close["success"] else {"success": False, "skipped": True}
            actions = {"entry": entry, "close_after_entry": close, "activation": toggle}
        else:
            _setup_call(ctx, "close empty microwave before activation", lambda: ctx.ops.set_open(microwave_id, False))
            pre = ctx.capture("potato_outside_before_activation")
            toggle = _natural_step(ctx, "ToggleObjectOn", objectId=microwave_id, forceAction=True)
            between = ctx.capture("after_activation_before_open_and_entry")
            open_result = _natural_step(ctx, "OpenObject", objectId=microwave_id, forceAction=True) if toggle["success"] else {"success": False, "skipped": True}
            entry = {"success": False, "skipped": True}
            before_entry = None
            close = {"success": False, "skipped": True}
            if open_result["success"]:
                _setup_call(ctx, "hold potato before tested PutObject", lambda: ctx.pickup("Potato"))
                before_entry = ctx.capture("after_pickup_before_entry")
                entry = _put_natural(ctx, "Potato", "Microwave")
                close = _natural_step(ctx, "CloseObject", objectId=microwave_id, forceAction=True) if entry["success"] else {"success": False, "skipped": True}
            actions = {"activation": toggle, "open_after_activation": open_result,
                       "entry": entry, "close_after_entry": close}
        after = _record(ctx, "after_ordered_actions", ("Microwave", "Potato"),
                        {"Microwave": ("isToggled", "isOpen"), "Potato": ("temperature", "isCooked")})
        pre_obj = next((o for o in pre["metadata"].get("objects", []) if o.get("objectId") == potato_id), {})
        final = after["latest"]["Potato"]
        effect = (final.get("temperature") is not None and
                  (final.get("temperature") != native_temperature(pre_obj) or
                  final.get("isCooked") is True and pre_obj.get("isCooked") is not True)
                  )
        complete = all(row.get("success") for row in actions.values() if not row.get("skipped")) and not any(
            row.get("skipped") for row in actions.values())
        ctx.check("ordered_native_actions_succeeded", complete,
                  {"order": order, "actions": actions, "intermediate": between})
        ctx.check("potato_heat_or_cook_change_observed", complete and effect,
                  {"before": pre_obj, "after": final, "trace": after["observations"]})
        status = "observed_supported" if complete and effect else ("inconclusive" if not complete or not effect else "observed_counterexample")
        return {"status": status, "fact_id": "F1", "family": "microwave", "condition": order,
                "pre_event_snapshot": pre, "intermediate_snapshot": between,
                "before_entry": before_entry, "actions": actions,
                "after": after,
                "interpretation": "Door opening may interrupt activation; every ordered native action is retained, and a failed order is inconclusive."}
    return run


def _f1_coffee(order: str):
    def run(ctx: Any) -> dict[str, Any]:
        machine_id = _bind(ctx, "CoffeeMachine", "CoffeeMachine", capability="toggleable")
        mug_id = _bind(ctx, "Mug", "Mug", capability="pickupable")
        _bind(ctx, "Counter", "CounterTop", capability="receptacle")
        _setup_call(ctx, "coffee machine off before order probe", lambda: ctx.ops.set_toggle(machine_id, False))
        _setup_call(ctx, "mug liquid capability", lambda: ctx.require(ctx.obj("Mug").get("canFillWithLiquid") is True,
                                                                         "mug is not fillable"))
        _setup_call(ctx, "explicit empty mug precondition", lambda: ctx.ops.set_liquid(mug_id, None))
        _setup_call(ctx, "stage mug outside coffee machine", lambda: ctx.move_setup("Mug", "Counter"))
        if order == "enter_then_activate":
            pre = ctx.capture("empty_mug_outside_before_entry")
            _setup_call(ctx, "hold mug before tested PutObject", lambda: ctx.pickup("Mug"))
            before_entry = ctx.capture("after_pickup_before_entry")
            entry = _put_natural(ctx, "Mug", "CoffeeMachine")
            between = ctx.capture("after_entry_before_activation")
            toggle = _natural_step(ctx, "ToggleObjectOn", objectId=machine_id, forceAction=True) if entry["success"] else {"success": False, "skipped": True}
            actions = {"entry": entry, "activation": toggle}
        else:
            pre = ctx.capture("empty_mug_outside_before_activation")
            toggle = _natural_step(ctx, "ToggleObjectOn", objectId=machine_id, forceAction=True)
            between = ctx.capture("after_activation_before_entry")
            entry = {"success": False, "skipped": True}
            before_entry = None
            if toggle["success"]:
                _setup_call(ctx, "hold mug before tested PutObject", lambda: ctx.pickup("Mug"))
                before_entry = ctx.capture("after_pickup_before_entry")
                entry = _put_natural(ctx, "Mug", "CoffeeMachine")
            actions = {"activation": toggle, "entry": entry}
        after = _record(ctx, "after_ordered_actions", ("CoffeeMachine", "Mug"),
                        {"CoffeeMachine": ("isToggled",), "Mug": ("isFilledWithLiquid", "fillLiquid", "temperature")})
        final = after["latest"]["Mug"]
        coffee = final.get("isFilledWithLiquid") is True and str(final.get("fillLiquid") or "").lower() == "coffee"
        complete = all(row.get("success") for row in actions.values())
        ctx.check("ordered_native_actions_succeeded", complete, {"order": order, "actions": actions})
        ctx.check("coffee_fill_observed", complete and coffee, {"after": final, "trace": after["observations"]})
        status = "observed_supported" if complete and coffee else ("observed_counterexample" if complete else "inconclusive")
        return {"status": status, "fact_id": "F1", "family": "coffee", "condition": order,
                "pre_event_snapshot": pre, "intermediate_snapshot": between,
                "before_entry": before_entry, "actions": actions, "after": after,
                "interpretation": "Only this mug and coffee-machine sequence is assessed; the opposite order has its own case."}
    return run


def _f2(inside: bool):
    def run(ctx: Any) -> dict[str, Any]:
        microwave_id, _ = _prepare_microwave(ctx, "Potato", "Potato")
        receptacle = "Microwave" if inside else "Counter"
        if not inside:
            _bind(ctx, "Counter", "CounterTop", capability="receptacle")
        _setup_call(ctx, f"place potato at {receptacle}", lambda: ctx.move_setup("Potato", receptacle))
        _setup_call(ctx, "close microwave before heating", lambda: ctx.ops.set_open(microwave_id, False))
        pre_obj = _state(ctx, "Potato", ("ObjectTemperature", "isCooked"))
        ctx.require(pre_obj.get("isCooked") is False, "uncooked potato unavailable for relation contrast")
        ctx.require(pre_obj.get("ObjectTemperature") is not None, "potato temperature metadata unavailable")
        ctx.require(pre_obj.get("ObjectTemperature") == "RoomTemp", "RoomTemp potato baseline unavailable before relation contrast")
        parents_before = _parents(ctx, "Potato")
        related_before = microwave_id in parents_before
        ctx.require(related_before is inside,
                    f"setup_failed: requested {'inside' if inside else 'outside'} relation was not realized before heating")
        pre = ctx.capture("before_heat_event")
        event = _natural_step(ctx, "ToggleObjectOn", objectId=microwave_id, forceAction=True)
        after = _record(ctx, "post_heat_samples", ("Microwave", "Potato"),
                        {"Microwave": ("isToggled", "isOpen"), "Potato": ("ObjectTemperature", "isCooked")})
        final = after["latest"]["Potato"]
        heated = (final.get("ObjectTemperature") is not None and
                  (final.get("ObjectTemperature") == "Hot" or
                   final.get("ObjectTemperature") != pre_obj.get("ObjectTemperature")))
        expected = related_before and heated if inside else (not related_before and not heated)
        ctx.check("metadata_relation_and_geometry_recorded", True,
                  {"parentReceptacles_before_event": parents_before, "microwave_id": microwave_id,
                   "position": pre_obj.get("position"),
                   "axisAlignedBoundingBox": pre_obj.get("axisAlignedBoundingBox"),
                   "microwave_position": ctx.obj("Microwave").get("position"),
                   "microwave_bounds": ctx.obj("Microwave").get("axisAlignedBoundingBox")})
        ctx.check("heating_matches_current_spatial_relation", event["success"] and expected,
                  {"condition": "inside" if inside else "outside", "related_to_microwave_before_event": related_before,
                   "heated_or_cooked": heated, "event": event, "before": pre_obj, "after": final})
        status = "observed_supported" if event["success"] and expected else (
            "observed_counterexample" if event["success"] and
            (related_before != inside or (not inside and heated)) else "inconclusive")
        return {"status": status, "fact_id": "F2", "condition": "inside" if inside else "outside",
                "pre_event_snapshot": pre, "event": event, "after": after,
                "actual_relation": {"microwave_id": microwave_id, "placement_parent_id": ctx.obj(receptacle)["objectId"],
                                    "parentReceptacles_before_event": parents_before,
                                    "parentReceptacles_after_event": _parents(ctx, "Potato"), "geometry": pre_obj},
                "interpretation": "Inside and outside are separate reset-isolated cases; a boundary/edge placement remains untested."}
    return run


def _relative_bbox_score(point: dict[str, Any], bbox: dict[str, Any]) -> float | None:
    center = bbox.get("center")
    size = bbox.get("size")
    if not isinstance(center, dict) or not isinstance(size, dict):
        return None
    try:
        return sum(((float(point[axis]) - float(center[axis])) / max(float(size[axis]) / 2.0, 1e-6)) ** 2
                   for axis in ("x", "y", "z")) ** 0.5
    except (KeyError, TypeError, ValueError):
        return None


def _f2_scan_geometry(target: str):
    def run(ctx: Any) -> dict[str, Any]:
        scene = ctx.session.scene
        if target == "microwave_edge":
            _bind(ctx, "Microwave", "Microwave", capability="receptacle")
            _bind(ctx, "Potato", "Potato", capability="pickupable")
            _setup_call(ctx, "microwave off for position scan", lambda: ctx.ops.set_toggle(ctx.roles["Microwave"], False))
            _setup_call(ctx, "microwave open for native spawn query", lambda: ctx.ops.set_open(ctx.roles["Microwave"], True))
            ctx.require(ctx.obj("Potato").get("isCooked") is False, "uncooked potato unavailable for F2 scan")
            ctx.require(ctx.field("Potato", "temperature") == "RoomTemp", "RoomTemp potato unavailable for F2 scan")
            receptacle_alias, object_alias, family = "Microwave", "Potato", "microwave"
            container_kind = "Microwave"
        else:
            _bind(ctx, "SinkBasin", "SinkBasin", capability="receptacle")
            _bind(ctx, "Faucet", "Faucet", capability="toggleable")
            _bind(ctx, "Bowl", "Bowl", capability="pickupable")
            _setup_call(ctx, "faucet off for basin position scan", lambda: ctx.ops.set_toggle(ctx.roles["Faucet"], False))
            ctx.require(ctx.obj("Bowl").get("dirtyable") is True and ctx.obj("Bowl").get("canFillWithLiquid") is True,
                        "dirtyable/fillable Bowl unavailable for basin scan")
            _setup_call(ctx, "explicit dirty basin-scan state", lambda: ctx.ops.set_dirty(ctx.roles["Bowl"], True))
            _setup_call(ctx, "explicit empty basin-scan state", lambda: ctx.ops.set_liquid(ctx.roles["Bowl"], None))
            receptacle_alias, object_alias, family = "SinkBasin", "Bowl", "water"
            container_kind = "SinkBasin"

        container_id = ctx.roles[receptacle_alias]
        source_id = ctx.roles["Faucet"] if target == "sink_spawn" else ctx.roles["Microwave"]
        object_id = ctx.roles[object_alias]
        spawn_result = ctx.step("GetSpawnCoordinatesAboveReceptacle", objectId=container_id, anywhere=True)
        spawn_points = list(spawn_result.metadata.get("actionReturn") or [])
        ctx.require(bool(spawn_points), f"no native spawn candidates for {container_kind}")
        bbox = ctx.obj(receptacle_alias).get("axisAlignedBoundingBox") or {}
        scored = [(score, point) for point in spawn_points
                  if (score := _relative_bbox_score(point, bbox)) is not None]
        ctx.require(bool(scored), f"native spawn points or {container_kind} AABB do not expose usable XYZ coordinates")
        center_candidate = min(scored, key=lambda item: item[0])
        edge_candidate = max(scored, key=lambda item: item[0])
        candidates = [("center_candidate", center_candidate), ("farthest_edge_candidate", edge_candidate)]
        unique: list[tuple[str, tuple[float, dict[str, Any]]]] = []
        for name, candidate in candidates:
            point = candidate[1]
            if not any(all(float(point[axis]) == float(old[1][1][axis]) for axis in ("x", "y", "z")) for old in unique):
                unique.append((name, candidate))

        trials: list[dict[str, Any]] = []
        for index, (candidate_name, (candidate_score, point)) in enumerate(unique):
            if index:
                ctx.capture(f"before_reset_{target}_{candidate_name}")
                ctx.session.reset(scene)
                ctx.roles.clear()
            trial: dict[str, Any] = {"candidate_name": candidate_name,
                                    "candidate_score_relative_to_aabb": candidate_score,
                                    "requested_position": point,
                                    "setup_status": "not_started"}
            try:
                if target == "microwave_edge":
                    _bind(ctx, "Microwave", "Microwave", capability="receptacle")
                    _bind(ctx, "Potato", "Potato", capability="pickupable")
                    ctx.ops.set_toggle(ctx.roles["Microwave"], False)
                    ctx.ops.set_open(ctx.roles["Microwave"], True)
                    ctx.require(ctx.obj("Potato").get("isCooked") is False,
                                "setup_unavailable: potato is cooked at reset")
                    ctx.require(ctx.field("Potato", "temperature") == "RoomTemp",
                                "setup_unavailable: potato is hot or has no temperature baseline")
                else:
                    _bind(ctx, "SinkBasin", "SinkBasin", capability="receptacle")
                    _bind(ctx, "Faucet", "Faucet", capability="toggleable")
                    _bind(ctx, "Bowl", "Bowl", capability="pickupable")
                    ctx.ops.set_toggle(ctx.roles["Faucet"], False)
                    ctx.ops.set_dirty(ctx.roles["Bowl"], True)
                    ctx.ops.set_liquid(ctx.roles["Bowl"], None)
                live_object_id = ctx.roles[object_alias]
                live_container_id = ctx.roles[receptacle_alias]
                live_source_id = ctx.roles["Microwave" if target == "microwave_edge" else "Faucet"]
                place = ctx.step("PlaceObjectAtPoint", objectId=live_object_id, position=point)
                settle = ctx.ops.settle(steps=2)
                if target == "microwave_edge":
                    close = ctx.step("CloseObject", objectId=live_source_id, forceAction=True)
                    close_settle = ctx.ops.settle(steps=2)
                    trial["source_setup_action"] = getattr(close, "record", None)
                    trial["source_setup_settle_records"] = [getattr(item, "record", None) for item in close_settle]
                placed_obj = ctx.obj(object_alias)
                placed_container = ctx.obj(receptacle_alias)
                parents_before = sorted(placed_obj.get("parentReceptacles") or [])
                relation = live_container_id in parents_before
                trial["placement_action"] = getattr(place, "record", None)
                trial["settle_action_records"] = [getattr(item, "record", None) for item in settle]
                trial["setup_status"] = "placed"
                trial["before_event"] = {"object": _state(ctx, object_alias,
                    ("temperature", "isCooked") if target == "microwave_edge" else ("isDirty", "isFilledWithLiquid", "fillLiquid")),
                    "container_position": placed_container.get("position"),
                    "container_bounds": placed_container.get("axisAlignedBoundingBox"),
                    "metadata_parentReceptacles": parents_before,
                    "relation_to_target": relation,
                    "actual_position_relative_to_aabb_score": _relative_bbox_score(
                        placed_obj.get("position") or {}, placed_container.get("axisAlignedBoundingBox") or {})}
                trial["before_capture"] = ctx.capture(f"f2_{target}_{candidate_name}_before_event")
                if target == "microwave_edge":
                    event = ctx.step("ToggleObjectOn", objectId=live_source_id, forceAction=True)
                else:
                    event = ctx.step("ToggleObjectOn", objectId=live_source_id, forceAction=True)
                trial["source_event"] = getattr(event, "record", None)
                observations = ctx.observe()
                after_obj = _state(ctx, object_alias,
                    ("temperature", "isCooked") if target == "microwave_edge" else ("isDirty", "isFilledWithLiquid", "fillLiquid"))
                trial["observations"] = observations
                trial["after_event"] = after_obj
                trial["after_metadata_parentReceptacles"] = _parents(ctx, object_alias)
                trial["effect"] = ({"temperature_changed_or_hot": after_obj.get("temperature") is not None and
                                     (after_obj.get("temperature") == "Hot" or
                                      after_obj.get("temperature") != trial["before_event"]["object"].get("temperature")),
                                     "cooked": after_obj.get("isCooked")} if target == "microwave_edge" else
                                    {"became_clean": trial["before_event"]["object"].get("isDirty") is True and after_obj.get("isDirty") is False,
                                     "became_filled_with_water": trial["before_event"]["object"].get("isFilledWithLiquid") is False and
                                         after_obj.get("isFilledWithLiquid") is True and
                                         str(after_obj.get("fillLiquid") or "").lower() == "water"})
                trial["setup_status"] = "measured"
            except Exception as exc:
                records = getattr(ctx.session, "records", [])
                trial["setup_status"] = "setup_unavailable"
                trial["setup_error"] = f"{type(exc).__name__}: {exc}"
                trial["last_action_record"] = records[-1] if records else None
            trials.append(trial)

        measured = [trial for trial in trials if trial.get("setup_status") == "measured"]
        relations = {bool(trial["before_event"]["relation_to_target"]) for trial in measured}
        aligned = []
        mismatches = []
        for trial in measured:
            related = trial["before_event"]["relation_to_target"]
            effect = (trial["effect"].get("temperature_changed_or_hot") if target == "microwave_edge"
                      else trial["effect"].get("became_clean") or trial["effect"].get("became_filled_with_water"))
            row = {"candidate_name": trial["candidate_name"], "relation": related, "observed_effect": effect}
            (aligned if effect is related else mismatches).append(row)
        ctx.check("position_scan_measured_real_relation_and_effect", bool(measured),
                  {"trials": trials, "relation_effect_alignment": aligned, "mismatches": mismatches})
        if len(measured) < 2 or len(relations) < 2:
            status = "inconclusive"
            reason = "Fewer than two placements or no inside/outside metadata relation contrast was realized."
        elif mismatches:
            status = "observed_counterexample"
            reason = "Successful native source events produced at least one effect/relation mismatch in the sampled positions."
        else:
            status = "observed_supported"
            reason = "The sampled realized relation categories aligned with the measured native effects for this asset and build."
        return {"status": status, "fact_id": "F2", "family": family, "condition": target,
                "container_type": container_kind, "spawn_candidate_count": len(spawn_points),
                "trials": trials, "relation_effect_distribution": {"aligned": aligned, "mismatches": mismatches,
                    "relation_values_measured": sorted(relations)},
                "interpretation": reason + " Candidate names use AABB-relative coordinates only; measured position, parent relation and effects are retained per trial."}
    return run


def _f3_toaster(single: bool):
    def run(ctx: Any) -> dict[str, Any]:
        toaster_id = _bind(ctx, "Toaster", "Toaster", capability="toggleable")
        _setup_call(ctx, "toaster off before multi-object probe", lambda: ctx.ops.set_toggle(toaster_id, False))
        aliases = _ensure_bread_slices(ctx, 1 if single else 2)
        for alias in aliases:
            ctx.require(ctx.obj(alias).get("isCooked") is False, f"uncooked state unavailable for {alias}")
        for alias in aliases:
            _setup_call(ctx, f"place {alias} in toaster before heat event", lambda a=alias: ctx.move_setup(a, "Toaster"))
        relations_before = {alias: toaster_id in _parents(ctx, alias) for alias in aliases}
        relation_check = ctx.check("all_targets_related_before_heat_event", all(relations_before.values()), relations_before)
        ctx.require(relation_check["passed"], "setup_failed: a selected slice did not remain inside the toaster")
        before = {alias: _state(ctx, alias, ("temperature", "isCooked")) for alias in aliases}
        for alias in aliases:
            ctx.require(before[alias].get("temperature") == "RoomTemp",
                        f"no cool temperature baseline for {alias}")
        pre = ctx.capture("all_targets_inside_before_activation")
        event = _natural_step(ctx, "ToggleObjectOn", objectId=toaster_id, forceAction=True)
        after = _record(ctx, "post_heat_samples", tuple(["Toaster"] + aliases),
                        {"Toaster": ("isToggled",),
                         **{a: ("ObjectTemperature", "isCooked") for a in aliases}})
        outcomes = {}
        for alias in aliases:
            values = after["latest"][alias]
            temp_before = before[alias].get("temperature")
            temp_after = values.get("ObjectTemperature")
            cooked_before = before[alias].get("isCooked")
            cooked_after = values.get("isCooked")
            outcomes[alias] = {"temperature_before": temp_before,
                               "temperature_after": temp_after,
                               "isCooked_before": cooked_before,
                               "isCooked_after": cooked_after,
                               "heated_or_cooked": ((temp_after is not None and temp_after == "Hot") or
                                   (temp_before is not None and temp_after is not None and temp_after != temp_before) or
                                   (cooked_before is False and cooked_after is True)),
                               "parents": values.get("parentReceptacles"),
                               "position": values.get("position")}
        all_changed = event["success"] and relation_check["passed"] and all(v["heated_or_cooked"] for v in outcomes.values())
        any_change = any(v["heated_or_cooked"] for v in outcomes.values())
        ctx.check("every_target_heated_or_cooked", all_changed,
                  {"event": event, "outcomes": outcomes})
        status = "observed_supported" if all_changed else ("observed_counterexample" if event["success"] and any_change else "inconclusive")
        return {"status": status, "fact_id": "F3", "condition": "single_object" if single else "multiple_objects",
                "family": "toaster", "pre_event_snapshot": pre, "event": event, "after": after,
                "single_controls_missing": [],
                "single_control_case_ids": [] if single else ["f3_toaster_single"],
                "multi_object_independence_status": "not_applicable" if single else "inconclusive_pending_paired_single_control",
                "relations_before": relations_before, "before": before, "outcomes": outcomes,
                "interpretation": "BreadSliced objects come from existing scene inventory or native SliceObject; no items are spawned."}
    return run


def _f3_microwave(count: int):
    def run(ctx: Any) -> dict[str, Any]:
        microwave_id = _bind(ctx, "Microwave", "Microwave", capability="toggleable")
        _setup_call(ctx, "microwave off", lambda: ctx.ops.set_toggle(microwave_id, False))
        _setup_call(ctx, "open microwave for setup", lambda: ctx.ops.set_open(microwave_id, True))
        aliases = [f"Potato_{index + 1}" for index in range(count)]
        ids: list[str] = []
        for alias in aliases:
            object_id = _bind(ctx, alias, "Potato", capability="pickupable", exclude=tuple(ids))
            ids.append(object_id)
            ctx.require(ctx.obj(alias).get("isCooked") is False, f"uncooked state unavailable for {alias}")
            ctx.require(ctx.field(alias, "temperature") == "RoomTemp",
                        f"no cool temperature baseline for {alias}")
            _setup_call(ctx, f"place {alias} in microwave", lambda a=alias: ctx.move_setup(a, "Microwave"))
        _setup_call(ctx, "close microwave before heat event", lambda: ctx.ops.set_open(microwave_id, False))
        relations = {alias: microwave_id in _parents(ctx, alias) for alias in aliases}
        relation_check = ctx.check("all_potatoes_related_before_heat_event", all(relations.values()), relations)
        ctx.require(relation_check["passed"], "setup_failed: selected potatoes did not remain in the microwave")
        before = {alias: _state(ctx, alias, ("temperature", "isCooked")) for alias in aliases}
        for alias in aliases:
            ctx.require(before[alias].get("temperature") == "RoomTemp" and
                        before[alias].get("isCooked") is False,
                        f"pre-event cool/uncooked baseline lost during setup for {alias}")
        pre = ctx.capture("all_potatoes_inside_before_activation")
        event = _natural_step(ctx, "ToggleObjectOn", objectId=microwave_id, forceAction=True)
        after = _record(ctx, "post_heat_samples", tuple(["Microwave"] + aliases),
                        {"Microwave": ("isToggled", "isOpen"),
                         **{a: ("temperature", "isCooked") for a in aliases}})
        outcomes = {}
        for alias in aliases:
            final = after["latest"][alias]
            outcomes[alias] = {"temperature_before": before[alias].get("temperature"),
                               "temperature_after": final.get("temperature"),
                               "isCooked_before": before[alias].get("isCooked"),
                               "isCooked_after": final.get("isCooked"),
                               "heated_or_cooked": (final.get("temperature") == "Hot" or
                                   (final.get("temperature") is not None and
                                    before[alias].get("temperature") is not None and
                                    final.get("temperature") != before[alias].get("temperature")) or
                                   (before[alias].get("isCooked") is False and final.get("isCooked") is True))}
        effect_check = ctx.check("each_potato_heated_or_cooked", event["success"] and all(
            row["heated_or_cooked"] for row in outcomes.values()), {"event": event, "outcomes": outcomes})
        any_effect = any(row["heated_or_cooked"] for row in outcomes.values())
        status = "observed_supported" if effect_check["passed"] else (
            "observed_counterexample" if event["success"] and any_effect else "inconclusive")
        return {"status": status, "fact_id": "F3", "family": "microwave",
                "condition": "single_object" if count == 1 else "multiple_objects",
                "single_controls_missing": [],
                "single_control_case_ids": [] if count == 1 else ["f3_microwave_single"],
                "multi_object_independence_status": "not_applicable" if count == 1 else "inconclusive_pending_paired_single_control",
                "pre_event_snapshot": pre, "event": event, "after": after,
                "relations_before": relations, "before": before, "outcomes": outcomes,
                "interpretation": "The single-object and multi-potato trials reset independently; failed placement is setup_failed."}
    return run


def _f3_water(count: int):
    def run(ctx: Any) -> dict[str, Any]:
        faucet_id = _bind(ctx, "Faucet", "Faucet", capability="toggleable")
        _bind(ctx, "SinkBasin", "SinkBasin", capability="receptacle")
        _setup_call(ctx, "faucet off before setup", lambda: ctx.ops.set_toggle(faucet_id, False))
        aliases = [f"Bowl_{index + 1}" for index in range(count)]
        ids: list[str] = []
        for alias in aliases:
            object_id = _bind(ctx, alias, "Bowl", capability="pickupable", exclude=tuple(ids))
            ids.append(object_id)
            ctx.require(ctx.obj(alias).get("canFillWithLiquid") is True,
                        f"{alias} lacks canFillWithLiquid capability")
            _setup_call(ctx, f"make {alias} empty as explicit initial state",
                        lambda a=alias, oid=object_id: ctx.ops.set_liquid(oid, None))
            _setup_call(ctx, f"place {alias} in sink basin", lambda a=alias: ctx.move_setup(a, "SinkBasin"))
        relations = {alias: ctx.obj("SinkBasin")["objectId"] in _parents(ctx, alias) for alias in aliases}
        relation_check = ctx.check("all_fillable_objects_related_before_water_on", all(relations.values()), relations)
        ctx.require(relation_check["passed"], "setup_failed: selected bowls did not remain in the sink basin")
        before = {alias: _state(ctx, alias, ("isFilledWithLiquid", "fillLiquid")) for alias in aliases}
        for alias in aliases:
            ctx.require(before[alias].get("isFilledWithLiquid") is False,
                        f"empty pre-event baseline unavailable for {alias}")
        pre = ctx.capture("all_empty_objects_in_basin_before_running_water")
        event = _natural_step(ctx, "ToggleObjectOn", objectId=faucet_id, forceAction=True)
        after = _record(ctx, "post_water_activation_samples", tuple(["Faucet"] + aliases),
                        {"Faucet": ("isToggled",),
                         **{a: ("isFilledWithLiquid", "fillLiquid") for a in aliases}})
        outcomes = {alias: {"before": before[alias], "after": after["latest"][alias],
                            "filled_with_water": before[alias].get("isFilledWithLiquid") is False and
                                after["latest"][alias].get("isFilledWithLiquid") is True and
                                str(after["latest"][alias].get("fillLiquid") or "").lower() == "water"}
                    for alias in aliases}
        effect_check = ctx.check("every_fillable_object_filled_by_running_water",
                                 event["success"] and all(row["filled_with_water"] for row in outcomes.values()),
                                 {"event": event, "outcomes": outcomes})
        any_effect = any(row["filled_with_water"] for row in outcomes.values())
        status = "observed_supported" if effect_check["passed"] else (
            "observed_counterexample" if event["success"] and any_effect else "inconclusive")
        return {"status": status, "fact_id": "F3", "family": "water",
                "condition": "single_object" if count == 1 else "multiple_objects",
                "single_controls_missing": [],
                "single_control_case_ids": [] if count == 1 else ["f3_water_single"],
                "multi_object_independence_status": "not_applicable" if count == 1 else "inconclusive_pending_paired_single_control",
                "pre_event_snapshot": pre, "event": event, "after": after,
                "relations_before": relations, "before": before, "outcomes": outcomes,
                "interpretation": "The faucet-on event is the native trigger. Inventory and sink placements are verified before it; no extra containers are spawned."}
    return run


def _f3_stove(count: int, single_object_type: str | None = None):
    def run(ctx: Any) -> dict[str, Any]:
        metadata = ctx.session.snapshot()
        by_id = {obj.get("objectId"): obj for obj in metadata.get("objects", [])}
        mapping = None
        for knob in sorted((obj for obj in metadata.get("objects", [])
                            if obj.get("objectType") == "StoveKnob" and obj.get("toggleable") is True),
                           key=lambda obj: str(obj.get("objectId", ""))):
            for target in knob.get("controlledObjects") or []:
                target_id = target.get("objectId") if isinstance(target, dict) else target
                if target_id in by_id and by_id[target_id].get("objectType") == "StoveBurner":
                    mapping = (knob["objectId"], target_id)
                    break
            if mapping:
                break
        ctx.require(mapping is not None, "no native StoveKnob-to-StoveBurner mapping in scene metadata")
        knob_id, burner_id = mapping
        ctx.bind("StoveKnob", knob_id)
        ctx.bind("StoveBurner", burner_id)
        for control in metadata.get("objects", []):
            if control.get("objectType") == "StoveKnob" and control.get("toggleable") is True:
                _setup_call(ctx, "all stove knobs off before setup",
                            lambda oid=control["objectId"]: ctx.ops.set_toggle(oid, False))
        aliases = [f"HeatObject_{index + 1}" for index in range(count)]
        ids: list[str] = []
        for index, alias in enumerate(aliases):
            object_type = (single_object_type or "Kettle") if index == 0 else "Pot"
            try:
                object_id = ctx.select(alias, object_type, capability="pickupable", exclude=tuple(ids))
            except ProbeUnavailable:
                if index == 0 and single_object_type is None:
                    object_type = "Pot"
                    object_id = ctx.select(alias, object_type, capability="pickupable", exclude=tuple(ids))
                else:
                    raise ProbeUnavailable(f"setup_failed: no distinct second heatable object ({object_type})")
            ctx.bind(alias, object_id)
            ids.append(object_id)
            initial_temp = ctx.field(alias, "temperature")
            ctx.require(initial_temp == "RoomTemp", f"no RoomTemp precondition for {alias}")
            _setup_call(ctx, f"place {alias} on mapped burner", lambda a=alias: ctx.move_setup(a, "StoveBurner"))
        relations = {alias: burner_id in _parents(ctx, alias) for alias in aliases}
        relation_check = ctx.check("all_objects_on_same_burner_before_heat_event", all(relations.values()), relations)
        ctx.require(relation_check["passed"], "setup_failed: selected objects did not remain on the mapped burner")
        before = {alias: _state(ctx, alias, ("temperature",)) for alias in aliases}
        for alias in aliases:
            ctx.require(before[alias].get("temperature") == "RoomTemp",
                        f"stove placement lost RoomTemp precondition for {alias}")
        pre = ctx.capture("all_objects_on_burner_before_knob_on")
        event = _natural_step(ctx, "ToggleObjectOn", objectId=knob_id, forceAction=True)
        after = _record(ctx, "post_stove_activation_samples", tuple(["StoveKnob", "StoveBurner"] + aliases),
                        {"StoveKnob": ("isToggled",), "StoveBurner": ("isToggled",),
                         **{alias: ("temperature",) for alias in aliases}})
        outcomes = {}
        for alias in aliases:
            final_temp = after["latest"][alias].get("temperature")
            outcomes[alias] = {"temperature_before": before[alias].get("temperature"),
                               "temperature_after": final_temp,
                               "heated": final_temp is not None and before[alias].get("temperature") is not None and
                                   (final_temp == "Hot" or final_temp != before[alias].get("temperature"))}
        effect_check = ctx.check("each_object_heated_by_same_burner", event["success"] and all(
            row["heated"] for row in outcomes.values()), {"event": event, "outcomes": outcomes})
        any_effect = any(row["heated"] for row in outcomes.values())
        status = "observed_supported" if effect_check["passed"] else (
            "observed_counterexample" if event["success"] and any_effect else "inconclusive")
        return {"status": status, "fact_id": "F3", "family": "stove",
                "condition": "single_object" if count == 1 else "multiple_objects",
                "single_controls_missing": [],
                "single_control_case_ids": ([f"f3_stove_single_{kind.lower()}"
                                              for kind in sorted({ctx.obj(alias).get("objectType") for alias in aliases})]
                                             if count > 1 else []),
                "multi_object_independence_status": "not_applicable" if count == 1 else "inconclusive_pending_paired_single_controls",
                "mapping": {"knob_id": knob_id, "burner_id": burner_id},
                "pre_event_snapshot": pre, "event": event, "after": after,
                "relations_before": relations, "before": before, "outcomes": outcomes,
                "interpretation": "The control mapping only nominates a native target; successful heating is decided from object temperature trajectories."}
    return run


def _f4(initially_cooked: bool):
    def run(ctx: Any) -> dict[str, Any]:
        microwave_id, _ = _prepare_microwave(ctx, "Potato", "Potato")
        potato_id = ctx.obj("Potato")["objectId"]
        if initially_cooked:
            _setup_call(ctx, "explicit cooked precondition", lambda: ctx.ops.set_cooked(potato_id, True))
        else:
            ctx.require(ctx.obj("Potato").get("isCooked") is False,
                        "uncooked starting state unavailable for this scene object")
        _setup_call(ctx, "place potato inside microwave", lambda: ctx.move_setup("Potato", "Microwave"))
        _setup_call(ctx, "close microwave before heating", lambda: ctx.ops.set_open(microwave_id, False))
        pre = _state(ctx, "Potato", ("ObjectTemperature", "isCooked"))
        ctx.require(pre.get("ObjectTemperature") == "RoomTemp",
                    "RoomTemp starting state unavailable; cooling contrast is not controlled")
        heat_event = _natural_step(ctx, "ToggleObjectOn", objectId=microwave_id, forceAction=True)
        heated = _record(ctx, "heating_samples", ("Microwave", "Potato"),
                         {"Microwave": ("isToggled", "isOpen"), "Potato": ("ObjectTemperature", "isCooked")})
        hot_state = heated["latest"]["Potato"]
        # Removal and cooling are follow-up measurements; CookObject is never a
        # post-event stand-in for the tested heating behavior.
        if heat_event["success"]:
            _setup_call(ctx, "switch device off before removal", lambda: ctx.ops.set_toggle(microwave_id, False))
            open_result = _natural_step(ctx, "OpenObject", objectId=microwave_id, forceAction=True)
            _bind(ctx, "Counter", "CounterTop", capability="receptacle")
            before_removal = ctx.capture("after_heating_and_source_off_before_removal")
            if open_result["success"]:
                _setup_call(ctx, "move potato out to counter for cooling", lambda: ctx.move_setup("Potato", "Counter"))
                after_removal = ctx.capture("after_removal_before_cooling_observation")
            else:
                after_removal = None
        else:
            open_result = None
            before_removal = None
            after_removal = None
        cooling = ctx.observe(wall_seconds=15) if heat_event["success"] and after_removal is not None else []
        cool_state = _state(ctx, "Potato", ("ObjectTemperature", "isCooked"))
        temp_series = [shot for shot in cooling]
        cooked_retained = cool_state.get("isCooked") is True if initially_cooked else hot_state.get("isCooked") is True and cool_state.get("isCooked") is True
        cooled = cool_state.get("ObjectTemperature") == "RoomTemp"
        heated_effect = (hot_state.get("ObjectTemperature") is not None and
                         (hot_state.get("ObjectTemperature") == "Hot" or
                          hot_state.get("ObjectTemperature") != pre.get("ObjectTemperature")))
        cooked_outcome = (hot_state.get("isCooked") is True) if not initially_cooked else cool_state.get("isCooked") is True
        ctx.check("tested_heating_action_succeeded", heat_event["success"], heat_event)
        ctx.check("initial_cook_state", pre.get("isCooked") is initially_cooked, pre)
        ctx.check("cooked_fact_survives_removal_and_cooling", bool(cooked_retained),
                  {"heated_state": hot_state, "after_removal_cooling": cool_state, "initially_cooked": initially_cooked})
        ctx.check("heating_effect_observed", heated_effect,
                  {"before": pre, "after_heating": hot_state, "observation_trace": heated["observations"]})
        ctx.check("temperature_cooling_observed", cooled,
                  {"heated_state": hot_state, "after_removal_cooling": cool_state, "observation_trace": temp_series})
        if not heat_event["success"]:
            status = "inconclusive"
        elif open_result is None or not open_result["success"] or after_removal is None:
            status = "inconclusive"
        elif not heated_effect:
            status = "inconclusive"
        elif cooked_retained and cooked_outcome:
            status = "observed_supported" if cooled else "inconclusive"
        elif not initially_cooked and not cooked_outcome:
            status = "inconclusive"  # Heating without a cooked transition may need a longer native cycle.
        else:
            status = "observed_counterexample"
        return {"status": status, "fact_id": "F4", "condition": "initially_cooked" if initially_cooked else "initially_uncooked",
                "pre_event": pre, "heat_event": heat_event, "heated": heated,
                "open_for_removal": open_result,
                "removal_phase": {"before": before_removal, "after": after_removal},
                "cooling_observations": cooling, "after_cooling": cool_state,
                "interpretation": "Heat response and cooked-state retention are recorded separately; cooling is inconclusive if RoomTemp was not sampled."}
    return run


def _f5(dirty: bool, filled: bool, water_on: bool):
    def run(ctx: Any) -> dict[str, Any]:
        faucet_id = _bind(ctx, "Faucet", "Faucet", capability="toggleable")
        _bind(ctx, "SinkBasin", "SinkBasin", capability="receptacle")
        _bind(ctx, "Counter", "CounterTop", capability="receptacle")
        _bind(ctx, "Bowl", "Bowl", capability="pickupable")
        bowl_id = ctx.obj("Bowl")["objectId"]
        _setup_call(ctx, "Bowl must support both dirty and liquid states",
                    lambda: ctx.require(ctx.obj("Bowl").get("dirtyable") is True and
                                        ctx.obj("Bowl").get("canFillWithLiquid") is True,
                                        "Bowl lacks dirtyable or canFillWithLiquid capability"))
        _setup_call(ctx, "disable faucet before setting dirt/liquid", lambda: ctx.ops.set_toggle(faucet_id, False))
        _setup_call(ctx, "explicit dirt precondition", lambda: ctx.ops.set_dirty(bowl_id, dirty))
        _setup_call(ctx, "explicit liquid precondition", lambda: ctx.ops.set_liquid(bowl_id, "water" if filled else None))
        _setup_call(ctx, "faucet off before target event", lambda: ctx.ops.set_toggle(faucet_id, False))
        _setup_call(ctx, "stage bowl on counter", lambda: ctx.move_setup("Bowl", "Counter"))
        _setup_call(ctx, "hold bowl before water source/contact phase", lambda: ctx.pickup("Bowl"))
        initial = _state(ctx, "Bowl", ("isDirty", "isFilledWithLiquid", "fillLiquid"))
        ctx.require(initial.get("isDirty") is dirty and initial.get("isFilledWithLiquid") is filled,
                    "water four-cell precondition changed during setup/pickup")
        ctx.require((str(initial.get("fillLiquid") or "").lower() or None) == ("water" if filled else None),
                    "water four-cell liquid identity changed during setup/pickup")
        pre = ctx.capture("pre_water_source_and_contact")
        if water_on:
            flow = _natural_step(ctx, "ToggleObjectOn", objectId=faucet_id, forceAction=True)
            after_source = ctx.capture("after_water_source_on_before_contact") if flow["success"] else None
        else:
            flow = {"success": True, "action": "source_remains_off", "record": None}
            after_source = ctx.capture("water_source_off_before_contact")
        put = _put_natural(ctx, "Bowl", "SinkBasin") if flow["success"] else {
            "success": False, "action": "PutObject", "skipped": "water source toggle failed"}
        after = _record(ctx, "after_running_water_contact", ("Faucet", "Bowl", "SinkBasin"),
                        {"Faucet": ("isToggled",), "Bowl": ("isDirty", "isFilledWithLiquid", "fillLiquid")})
        final = after["latest"]["Bowl"]
        relation_id = ctx.obj("SinkBasin")["objectId"]
        parents_after = _parents(ctx, "Bowl")
        relation_after = relation_id in parents_after
        expected_dirty = False if water_on and dirty else dirty
        expected_filled = True if water_on and not filled else filled
        expected_liquid = "water" if expected_filled else None
        final_liquid = str(final.get("fillLiquid") or "").lower() or None
        states_match = (final.get("isDirty") is expected_dirty and
                        final.get("isFilledWithLiquid") is expected_filled and
                        final_liquid == expected_liquid)
        actions_succeeded = flow["success"] and put["success"]
        relation_check = ctx.check("bowl_in_sink_relation_after_native_put", relation_after,
                                   {"sink_id": relation_id, "parents_before_event": initial["parentReceptacles"],
                                    "parents_after_event": parents_after})
        state_check = ctx.check("dirty_and_liquid_match_water_source_condition", actions_succeeded and states_match,
                                {"water_on": water_on, "initial": initial, "expected": {
                                    "isDirty": expected_dirty, "isFilledWithLiquid": expected_filled,
                                    "fillLiquid": expected_liquid}, "final": final})
        supported = actions_succeeded and relation_check["passed"] and state_check["passed"]
        if supported:
            status = "observed_supported"
        elif water_on:
            # Sink membership and source-on do not establish actual water
            # contact. Retain the no-effect observation without claiming a
            # successful-contact mechanism counterexample.
            status = "inconclusive"
        else:
            status = "observed_counterexample" if actions_succeeded and relation_after else "inconclusive"
        newly_cleaned = initial.get("isDirty") is True and final.get("isDirty") is False
        newly_filled = initial.get("isFilledWithLiquid") is False and final.get("isFilledWithLiquid") is True
        return {"status": status, "fact_id": "F5", "family": "water",
                "condition": {"initially_dirty": dirty, "initially_filled_with_water": filled,
                              "water_source_on": water_on},
                "initial_state": initial, "pre_event_snapshot": pre,
                "source_action": flow, "after_source_before_contact": after_source,
                "contact_event": put, "after": after,
                "actual_contact_independently_verified": False,
                "native_effect_witness": {"newly_cleaned": newly_cleaned, "newly_filled": newly_filled},
                "no_effect_interpretation": "contact_or_activation_order_unverified" if water_on and not supported else None,
                "expected_final_state": {"isDirty": expected_dirty, "isFilledWithLiquid": expected_filled,
                                         "fillLiquid": expected_liquid},
                "interpretation": "Each active cell has a paired faucet-off placement control; all four dirt/liquid initial states are repeated under both source conditions."}
    return run


def _f6(initial_liquid: str | None, history: str):
    def run(ctx: Any) -> dict[str, Any]:
        machine_id = _bind(ctx, "CoffeeMachine", "CoffeeMachine", capability="toggleable")
        mug_id = _bind(ctx, "Mug", "Mug", capability="pickupable")
        _bind(ctx, "CounterTop", "CounterTop", capability="receptacle")
        _setup_call(ctx, "coffee machine off before setup", lambda: ctx.ops.set_toggle(machine_id, False))
        _setup_call(ctx, "mug on counter before state setup", lambda: ctx.move_setup("Mug", "CounterTop"))
        _setup_call(ctx, "mug supports liquid state", lambda: ctx.require(ctx.obj("Mug").get("canFillWithLiquid") is True,
                                                                           "Mug lacks canFillWithLiquid capability"))
        history_states = []
        if history == "fill_then_empty":
            _setup_call(ctx, "history stage fill mug", lambda: ctx.ops.set_liquid(mug_id, "water"))
            history_states.append(ctx.capture("history_after_fill"))
            _setup_call(ctx, "history stage empty mug", lambda: ctx.ops.set_liquid(mug_id, None))
            history_states.append(ctx.capture("history_after_empty"))
        elif history == "empty_then_fill":
            _setup_call(ctx, "history stage empty mug", lambda: ctx.ops.set_liquid(mug_id, None))
            history_states.append(ctx.capture("history_after_empty"))
            _setup_call(ctx, "history stage fill mug", lambda: ctx.ops.set_liquid(mug_id, "water"))
            history_states.append(ctx.capture("history_after_fill"))
        else:
            _setup_call(ctx, "explicit initial liquid precondition", lambda: ctx.ops.set_liquid(mug_id, initial_liquid))
        initial_mug_state = _state(ctx, "Mug", ("isFilledWithLiquid", "fillLiquid"))
        _setup_call(ctx, "activate coffee machine before placement", lambda: ctx.ops.set_toggle(machine_id, True))
        _setup_call(ctx, "hold mug before tested coffee placement", lambda: ctx.pickup("Mug"))
        event_time_mug = _state(ctx, "Mug", ("isFilledWithLiquid", "fillLiquid"))
        ctx.require(all(event_time_mug.get(key) == initial_mug_state.get(key)
                        for key in ("isFilledWithLiquid", "fillLiquid")),
                    "coffee liquid precondition changed before the evaluated PutObject")
        before_put = ctx.capture("after_pickup_before_coffee_placement")
        pre = ctx.capture("immediately_before_coffee_placement")
        event = _put_natural(ctx, "Mug", "CoffeeMachine")
        after = _record(ctx, "after_coffee_placement", ("CoffeeMachine", "Mug"),
                        {"CoffeeMachine": ("isToggled",), "Mug": ("isFilledWithLiquid", "fillLiquid", "ObjectTemperature")})
        final = after["latest"]["Mug"]
        before_fill = initial_mug_state.get("isFilledWithLiquid")
        before_kind = initial_mug_state.get("fillLiquid")
        becomes_coffee = final.get("isFilledWithLiquid") is True and str(final.get("fillLiquid") or "").lower() == "coffee"
        preserved = final.get("isFilledWithLiquid") is before_fill and (not before_fill or final.get("fillLiquid") == before_kind)
        source_succeeded = event["success"]
        if not source_succeeded:
            status = "inconclusive"
        elif before_fill is False and becomes_coffee:
            status = "observed_supported"
        elif before_fill is True and preserved:
            status = "observed_supported"
        elif before_fill in (True, False):
            status = "observed_counterexample"
        else:
            status = "inconclusive"
        ctx.check("coffee_placement_event_succeeded", source_succeeded, event)
        ctx.check("actual_initial_liquid_recorded", before_fill in (True, False),
                  {"isFilledWithLiquid": before_fill, "fillLiquid": before_kind, "history": history})
        ctx.check("empty_mug_filled_or_existing_liquid_preserved",
                  source_succeeded and ((before_fill is False and becomes_coffee) or (before_fill is True and preserved)),
                  {"before": {"isFilledWithLiquid": before_fill, "fillLiquid": before_kind}, "after": final,
                   "history_snapshots": history_states})
        return {"status": status, "fact_id": "F6", "condition": {"history": history,
                "configured_initial_liquid": initial_liquid}, "history_snapshots": history_states,
                "initial_state_after_history": initial_mug_state,
                "event_time_mug_state": event_time_mug,
                "before_put": before_put, "pre_event_snapshot": pre, "event": event, "after": after,
                "field_changes": _changed({"isFilledWithLiquid": before_fill, "fillLiquid": before_kind}, final,
                                           ("isFilledWithLiquid", "fillLiquid")),
                "interpretation": "The active-machine PutObject is the tested event. The four cases separately represent empty, water-filled, filled-then-emptied and empty-then-filled states."}
    return run


def cases() -> list[ProbeCase]:
    """Return reset-isolated native mechanism probes for F1-F6."""
    all_cases = [
        ProbeCase("f1_toaster_enter_then_activate", "F1", "toaster", _f1_run("enter_then_activate")),
        ProbeCase("f1_toaster_activate_then_enter", "F1", "toaster", _f1_run("activate_then_enter")),
        ProbeCase("f1_microwave_enter_then_activate", "F1", "microwave", _f1_microwave("enter_then_activate")),
        ProbeCase("f1_microwave_activate_then_enter", "F1", "microwave", _f1_microwave("activate_then_enter")),
        ProbeCase("f1_coffee_enter_then_activate", "F1", "coffee", _f1_coffee("enter_then_activate")),
        ProbeCase("f1_coffee_activate_then_enter", "F1", "coffee", _f1_coffee("activate_then_enter")),
        ProbeCase("f2_microwave_inside", "F2", "microwave", _f2(inside=True)),
        ProbeCase("f2_microwave_outside", "F2", "microwave", _f2(inside=False)),
        ProbeCase("f2_microwave_position_scan", "F2", "microwave", _f2_scan_geometry("microwave_edge")),
        ProbeCase("f2_sink_position_scan", "F2", "water", _f2_scan_geometry("sink_spawn")),
        ProbeCase("f3_toaster_single", "F3", "toaster", _f3_toaster(single=True)),
        ProbeCase("f3_toaster_multiple", "F3", "toaster", _f3_toaster(single=False)),
        ProbeCase("f3_microwave_single", "F3", "microwave", _f3_microwave(1)),
        ProbeCase("f3_microwave_multiple", "F3", "microwave", _f3_microwave(2)),
        ProbeCase("f3_water_single", "F3", "water", _f3_water(1)),
        ProbeCase("f3_water_multiple", "F3", "water", _f3_water(2)),
        ProbeCase("f3_stove_single_kettle", "F3", "stove", _f3_stove(1, "Kettle")),
        ProbeCase("f3_stove_single_pot", "F3", "stove", _f3_stove(1, "Pot")),
        ProbeCase("f3_stove_multiple", "F3", "stove", _f3_stove(2)),
        ProbeCase("f4_uncooked_then_heated_and_cooled", "F4", "microwave", _f4(initially_cooked=False)),
        ProbeCase("f4_cooked_then_reheated_and_cooled", "F4", "microwave", _f4(initially_cooked=True)),
    ]
    for dirty in (True, False):
        for filled in (False, True):
            state = ("dirty" if dirty else "clean") + ("_water_filled" if filled else "_empty")
            all_cases.append(ProbeCase(f"f5_{state}_water_on", "F5", "water", _f5(dirty, filled, True)))
            all_cases.append(ProbeCase(f"f5_{state}_water_off_control", "F5", "water", _f5(dirty, filled, False)))
    all_cases.extend([
        ProbeCase("f6_initially_empty", "F6", "coffee", _f6(None, "empty")),
        ProbeCase("f6_initially_water_filled", "F6", "coffee", _f6("water", "water_filled")),
        ProbeCase("f6_fill_then_empty", "F6", "coffee", _f6(None, "fill_then_empty")),
        ProbeCase("f6_empty_then_fill", "F6", "coffee", _f6(None, "empty_then_fill")),
    ])
    return all_cases

