"""Exploratory native probes for simulator facts F7-F11.

This module deliberately reports construction failures and missing timing
controls as inconclusive. It does not treat metadata mappings as proof of
physical effects, or held-object metadata as proof that a child stopped
following its parent.
"""
from __future__ import annotations

import copy
import math
import time
from typing import Any, Callable

from mechanism_probe_common import ProbeCase, ProbeUnavailable, write_json


def _bind_selected(ctx: Any, alias: str, object_type: str, capability: str | None = None,
                   exclude: tuple[str, ...] = ()) -> str:
    object_id = ctx.select(alias, object_type, capability=capability, exclude=exclude)
    ctx.bind(alias, object_id)
    return object_id


def _snapshot(ctx: Any, label: str) -> dict[str, Any]:
    return ctx.capture(label, image=True)


def _step(ctx: Any, label: str, action: str, **kwargs: Any) -> dict[str, Any]:
    result = ctx.step(action, **kwargs)
    # Capture after every state-changing step so RGB and metadata have the
    # same action index. The ledger itself remains owned by ControllerSession.
    snap = _snapshot(ctx, label)
    return {
        "label": label,
        "action": action,
        "kwargs": copy.deepcopy(kwargs),
        "record": copy.deepcopy(getattr(result, "record", {})),
        "snapshot": snap,
    }


def _position(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        return {axis: float(value[axis]) for axis in ("x", "y", "z")}
    except (KeyError, TypeError, ValueError):
        return None


def _distance(a: Any, b: Any) -> float | None:
    pa, pb = _position(a), _position(b)
    if pa is None or pb is None:
        return None
    return math.sqrt(sum((pa[k] - pb[k]) ** 2 for k in ("x", "y", "z")))


def _vector_delta(a: Any, b: Any) -> dict[str, float] | None:
    pa, pb = _position(a), _position(b)
    if pa is None or pb is None:
        return None
    return {axis: pb[axis] - pa[axis] for axis in ("x", "y", "z")}


def _vector_error(a: Any, b: Any) -> float | None:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    try:
        return math.sqrt(sum((float(a[k]) - float(b[k])) ** 2 for k in ("x", "y", "z")))
    except (KeyError, TypeError, ValueError):
        return None


def _save_action_segment(ctx: Any, name: str) -> str:
    """Persist the current ledger before a reset clears ControllerSession.records."""
    path = ctx.out / f"{name}_actions.json"
    write_json(path, ctx.session.records)
    return path.name


def _parents(obj: dict[str, Any]) -> list[str]:
    value = obj.get("parentReceptacles") or []
    result = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("objectId")
        if isinstance(item, str):
            result.append(item)
    return result


def _base(case_id: str, fact_id: str, family: str, status: str,
          *, checks: list[dict[str, Any]], steps: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "fact_id": fact_id,
        "family": family,
        "status": status,
        "checks": copy.deepcopy(checks),
        "steps": copy.deepcopy(steps),
        **copy.deepcopy(extra),
    }


def _check(ctx: Any, name: str, condition: bool, detail: Any = None) -> dict[str, Any]:
    return ctx.check(name, bool(condition), detail=detail)


def _pick_two_stove_mappings(ctx: Any) -> list[tuple[str, str]]:
    """Read controlledObjects only to nominate controls for physical trials."""
    metadata = ctx.session.snapshot()
    by_id = {o.get("objectId"): o for o in metadata.get("objects", [])}
    pairs: list[tuple[str, str]] = []
    for knob in sorted((o for o in metadata.get("objects", [])
                        if o.get("objectType") == "StoveKnob"),
                       key=lambda o: str(o.get("objectId", ""))):
        for entry in knob.get("controlledObjects") or []:
            target_id = entry.get("objectId") if isinstance(entry, dict) else entry
            target = by_id.get(target_id)
            if target and target.get("objectType") == "StoveBurner":
                pair = (knob["objectId"], target_id)
                if pair not in pairs:
                    pairs.append(pair)
    return pairs


def _native_stove_knobs(ctx: Any) -> list[str]:
    return sorted({str(o["objectId"]) for o in ctx.session.snapshot().get("objects", [])
                   if o.get("objectType") == "StoveKnob" and o.get("objectId")})


def _f7(condition: str) -> Callable[[Any], dict[str, Any]]:
    def run(ctx: Any) -> dict[str, Any]:
        case_id = f"F7_{condition}"
        steps: list[dict[str, Any]] = []
        checks = ctx.checks
        _bind_selected(ctx, "container", "Plate", "pickupable")
        _bind_selected(ctx, "child", "Apple", "pickupable")
        _bind_selected(ctx, "surface", "CounterTop", "receptacle")
        ctx.move_setup("child", "container")
        if condition in {"removed", "returned"}:
            # Make the intervening removal a real setup placement, then use a
            # fresh placement for the return condition. Each ProbeCase receives
            # a clean scene reset from the runner.
            ctx.move_setup("child", "surface")
            removed = ctx.roles["container"] not in _parents(ctx.obj("child"))
            _check(ctx, "child_removed_before_event", removed,
                   {"child": ctx.obj("child"), "container": ctx.roles["container"]})
            ctx.require(removed, "F7 setup failed: child still reports the container as a parent after removal")
            if condition == "returned":
                ctx.move_setup("child", "container")
        related_before = ctx.roles["container"] in _parents(ctx.obj("child"))
        if condition in {"returned", "retained"}:
            _check(ctx, "expected_relation_exists_before_event", related_before,
                   {"condition": condition, "child": ctx.obj("child"), "container": ctx.roles["container"]})
            ctx.require(related_before, f"F7 {condition} setup failed to establish current child-container relation")
        elif related_before:
            raise ProbeUnavailable("F7 removed setup failed: child is still related to the container")
        before = _snapshot(ctx, "before_pickup_container")
        child_before = ctx.obj("child")
        container_before = ctx.obj("container")
        relative_before = _vector_delta(container_before.get("position"), child_before.get("position"))
        steps.append(_step(ctx, "pickup_container", "PickupObject",
                           objectId=ctx.roles["container"], forceAction=True))
        trajectory = ctx.observe(steps=(0, 1, 4, 12, 36))
        metrics = []
        for row in trajectory:
            metadata = row.get("metadata", {})
            by_id = {item.get("objectId"): item for item in metadata.get("objects", [])}
            child_now = by_id.get(ctx.roles["child"], {})
            container_now = by_id.get(ctx.roles["container"], {})
            child_delta = _vector_delta(child_before.get("position"), child_now.get("position"))
            container_delta = _vector_delta(container_before.get("position"), container_now.get("position"))
            relative_now = _vector_delta(container_now.get("position"), child_now.get("position"))
            metrics.append({"capture_label": row.get("label"), "observation_passes": row.get("observation_passes"),
                            "child_position": child_now.get("position"),
                            "container_position": container_now.get("position"),
                            "child_displacement_m": _distance(child_before.get("position"), child_now.get("position")),
                            "container_displacement_m": _distance(container_before.get("position"), container_now.get("position")),
                            "child_vs_container_displacement_error_m": _vector_error(child_delta, container_delta),
                            "relative_position_error_m": _vector_error(relative_before, relative_now)})
        child_after, container_after = ctx.obj("child"), ctx.obj("container")
        moved_points = [row for row in metrics if row["container_displacement_m"] is not None
                        and row["container_displacement_m"] > 0.05]
        _check(ctx, "container_world_displacement_observed", bool(moved_points), metrics)
        if not moved_points:
            status = "inconclusive"
            supported = False
        elif condition == "removed":
            supported = all(row["child_displacement_m"] is not None
                            and row["child_displacement_m"] < 0.05
                            and row["relative_position_error_m"] is not None
                            and row["relative_position_error_m"] > 0.05
                            for row in moved_points)
            status = "observed_supported" if supported else "observed_counterexample"
        else:
            supported = all(row["child_vs_container_displacement_error_m"] is not None
                            and row["child_vs_container_displacement_error_m"] < 0.10
                            and row["relative_position_error_m"] is not None
                            and row["relative_position_error_m"] < 0.10
                            for row in moved_points)
            status = "observed_supported" if supported else "observed_counterexample"
        _check(ctx, "condition_specific_world_and_relative_motion", supported, {
            "condition": condition, "metrics": metrics,
            "parent_relation_before_event": related_before,
            "parent_relation_after_event": ctx.roles["container"] in _parents(child_after),
            "held_parent_field_disappearance_is_not_failure": True,
        })
        return _base(case_id, "F7", "current_carry_relation", status,
                     checks=checks, steps=steps, before=before,
                     child_before=child_before, child_after=child_after,
                     container_before=container_before, container_after=container_after,
                     trajectory=trajectory, motion_metrics=metrics,
                     interpretation={
                         "condition": condition,
                         "position_and_relative_motion_are_primary": True,
                         "parent_relation_before_event": related_before,
                         "parent_relation_after_event": ctx.roles["container"] in _parents(child_after),
                         "held_parent_disappearance_is_not_labeled_relation_loss": True,
                     })
    return run


def _f8(which: int, swapped: bool) -> Callable[[Any], dict[str, Any]]:
    def run(ctx: Any) -> dict[str, Any]:
        case_id = f"F8_control_{'A' if which == 0 else 'B'}{'_swapped' if swapped else ''}"
        checks, steps = ctx.checks, []
        pairs = _pick_two_stove_mappings(ctx)
        if len(pairs) < 2:
            raise ProbeUnavailable(f"F8 requires two distinct native knob-to-burner candidates; found {pairs!r}")
        distinct = next((p for p in pairs[1:] if p[0] != pairs[0][0] and p[1] != pairs[0][1]), None)
        if distinct is None:
            raise ProbeUnavailable(f"F8 mappings are not independent: {pairs!r}")
        mapping_a, mapping_b = pairs[0], distinct
        knob_id, burner_id = (mapping_a, mapping_b)[which]
        ctx.bind("knob_a", mapping_a[0]); ctx.bind("burner_a", mapping_a[1])
        ctx.bind("knob_b", mapping_b[0]); ctx.bind("burner_b", mapping_b[1])
        ctx.bind("target_knob", knob_id); ctx.bind("target_burner", burner_id)
        # Keep object identity and type fixed across all four conditions.
        _bind_selected(ctx, "probe_container_a", "Kettle", "pickupable")
        _bind_selected(ctx, "probe_container_b", "Pot", "pickupable")
        _check(ctx, "both_fixed_probe_objects_have_temperature",
               ctx.field("probe_container_a", "temperature") is not None and
               ctx.field("probe_container_b", "temperature") is not None,
               {"a": ctx.obj("probe_container_a"), "b": ctx.obj("probe_container_b")})
        ctx.require(ctx.field("probe_container_a", "temperature") is not None and
                    ctx.field("probe_container_b", "temperature") is not None,
                    "F8 needs a Kettle and Pot with native temperature metadata")
        # Turn off every stove knob candidate so unrelated burners cannot heat
        # either container. Use actual events and retain their RGB captures.
        for index, candidate_id in enumerate(_native_stove_knobs(ctx)):
            alias = f"candidate_knob_{index}"
            ctx.bind(alias, candidate_id)
            if ctx.obj(alias).get("isToggled") is True:
                steps.append(_step(ctx, f"{alias}_off_before_setup", "ToggleObjectOff",
                                   objectId=candidate_id, forceAction=True))
        room_rows = ctx.observe(steps=(0, 1, 4, 12, 36, 72, 120))
        if any(ctx.field(alias, "temperature") != "RoomTemp"
               for alias in ("probe_container_a", "probe_container_b")):
            raise ProbeUnavailable("F8 could not establish RoomTemp baselines with all candidate stove knobs off")
        destination_a, destination_b = (("burner_b", "burner_a") if swapped
                                        else ("burner_a", "burner_b"))
        ctx.move_setup("probe_container_a", destination_a)
        ctx.move_setup("probe_container_b", destination_b)
        placement_settle = ctx.observe(steps=(0, 1, 4, 12, 36))
        if any(ctx.field(alias, "temperature") != "RoomTemp"
               for alias in ("probe_container_a", "probe_container_b")):
            raise ProbeUnavailable("F8 placement did not preserve a RoomTemp pre-event baseline")
        # Control mappings are hypothesis selectors, not effect evidence. Run
        # actual on and off actions and inspect burner plus both object states.
        before = {"a": ctx.obj("probe_container_a"), "b": ctx.obj("probe_container_b"),
                  "burner_a": ctx.obj("burner_a"), "burner_b": ctx.obj("burner_b"),
                  "temperature_a": ctx.field("probe_container_a", "temperature"),
                  "temperature_b": ctx.field("probe_container_b", "temperature")}
        steps.append(_step(ctx, "target_on", "ToggleObjectOn", objectId=knob_id, forceAction=True))
        observations = ctx.observe(steps=(0, 1, 4, 12, 36, 72))
        active_state = {"burner_a": ctx.obj("burner_a").get("isToggled"),
                        "burner_b": ctx.obj("burner_b").get("isToggled")}
        after_on = {"a": ctx.field("probe_container_a", "temperature"),
                    "b": ctx.field("probe_container_b", "temperature")}
        steps.append(_step(ctx, "target_off", "ToggleObjectOff", objectId=knob_id, forceAction=True))
        off_state = {"burner_a": ctx.obj("burner_a").get("isToggled"),
                     "burner_b": ctx.obj("burner_b").get("isToggled")}
        target_side = "burner_a" if which == 0 else "burner_b"
        other_side = "burner_b" if which == 0 else "burner_a"
        observed_target = active_state[target_side] is True and active_state[other_side] is False
        _check(ctx, "native_mapping_target_burner_toggled", observed_target,
               {"metadata_mapping_candidate": [knob_id, burner_id], "burner_states_after_on": active_state,
                "target_on_and_other_off_required": True})
        target_container = ("probe_container_a" if
                            (ctx.roles[destination_a] == burner_id) else "probe_container_b")
        target_key = "a" if target_container == "probe_container_a" else "b"
        other_key = "b" if target_key == "a" else "a"
        target_hot = after_on[target_key] == "Hot"
        other_preserved = after_on[other_key] == "RoomTemp"
        _check(ctx, "object_on_target_burner_became_hot", target_hot,
               {"target_container": target_container,
                "before": before[f"temperature_{target_key}"], "after_72_pass": after_on[target_key],
                "positions_swapped": swapped})
        _check(ctx, "other_container_remained_room_temp", other_preserved,
               {"other_container": "probe_container_b" if other_key == "b" else "probe_container_a",
                "before": before[f"temperature_{other_key}"], "after_72_pass": after_on[other_key]})
        _check(ctx, "both_burners_off_after_target_off",
               off_state == {"burner_a": False, "burner_b": False}, off_state)
        # A positive mapping result needs both an observed controlled burner
        # transition and a temperature response at the tested location.
        off_confirmed = off_state == {"burner_a": False, "burner_b": False}
        status = "observed_supported" if observed_target and target_hot and other_preserved and off_confirmed else "inconclusive"
        return _base(case_id, "F8", "local_control_mapping", status,
                     checks=checks, steps=steps, native_mapping_candidate={"knob": knob_id, "burner": burner_id},
                     initial=before, states_after_on=active_state, temperatures_after_on=after_on,
                     states_after_off=off_state, container_assignment={"a": destination_a, "b": destination_b},
                     baseline_cooling=room_rows, placement_settle=placement_settle,
                     effect_observations=observations,
                     interpretation={"controlledObjects_is_metadata_candidate_only": True,
                                     "actual_toggle_and_temperature_were_checked": True,
                                     "negative_temperature_change_requires_more_timing_and_cooling_control": True})
    return run


def _f9(ctx: Any) -> dict[str, Any]:
    """Compare cooling after source-off event with a matched no-event arm."""
    case_id = "F9_matched_time"
    checks, steps = ctx.checks, []
    pairs = _pick_two_stove_mappings(ctx)
    if not pairs:
        raise ProbeUnavailable("F9 requires a native controllable heat source candidate")
    knob_id, burner_id = pairs[0]
    initial_scene = ctx.session.scene
    trials: dict[str, Any] = {}

    def run_arm(name: str, *, native_time: bool, turn_off: bool) -> dict[str, Any]:
        setup_start = time.monotonic()
        ctx.bind("target_knob", knob_id); ctx.bind("target_burner", burner_id)
        _bind_selected(ctx, "probe_object", "Kettle", "pickupable")
        for index, candidate_id in enumerate(_native_stove_knobs(ctx)):
            alias = f"{name}_candidate_knob_{index}"
            ctx.bind(alias, candidate_id)
            if ctx.obj(alias).get("isToggled") is True:
                steps.append(_step(ctx, f"{alias}_off_initial", "ToggleObjectOff",
                                   objectId=candidate_id, forceAction=True))
        ctx.move_setup("probe_object", "target_burner")
        if ctx.field("probe_object", "temperature") != "RoomTemp":
            ctx.observe(steps=(0, 1, 4, 12, 36, 72, 120, 240))
        ctx.require(ctx.field("probe_object", "temperature") == "RoomTemp",
                    f"{name}: could not establish RoomTemp before heating")
        steps.append(_step(ctx, f"{name}_heat_source_on", "ToggleObjectOn",
                           objectId=knob_id, forceAction=True))
        heat_observations = []
        for i in range(240):
            result = ctx.step("Pass")
            if i in {0, 3, 11, 35, 71, 119, 239}:
                heat_observations.append(_snapshot(ctx, f"{name}_precondition_heat_pass_{i+1}"))
            if ctx.field("probe_object", "temperature") == "Hot":
                break
        ctx.require(ctx.field("probe_object", "temperature") == "Hot",
                    f"{name}: source did not produce a Hot baseline within 240 Pass actions")
        hot_baseline = {"temperature": ctx.field("probe_object", "temperature"),
                        "object": ctx.obj("probe_object"), "knob": ctx.obj("target_knob"),
                        "burner": ctx.obj("target_burner")}
        if native_time:
            paused = False
            try:
                try:
                    # Treat the pause as potentially applied even when the
                    # action call raises; cleanup must try Unpause either way.
                    paused = True
                    pause_result = ctx.step("PausePhysicsAutoSim")
                    steps.append({"label": f"{name}_pause_auto_sim", "action": "PausePhysicsAutoSim",
                                  "kwargs": {}, "record": copy.deepcopy(pause_result.record),
                                  "snapshot": _snapshot(ctx, f"{name}_pause_auto_sim")})
                except Exception as exc:
                    raise ProbeUnavailable(f"native time action failed at PausePhysicsAutoSim: {type(exc).__name__}: {exc}") from exc
                if turn_off:
                    steps.append(_step(ctx, f"{name}_target_source_off", "ToggleObjectOff",
                                       objectId=knob_id, forceAction=True))
                # Official AI2-THOR contract: timeStep is in seconds and must
                # be in (0, 0.05]; 400 successful 0.01-second steps request
                # four simulated seconds. ObjectTemperature's clock may differ.
                controlled = []
                sample_indices = {1, 10, 50, 100, 200, 400}
                for index in range(1, 401):
                    try:
                        ctx.step("AdvancePhysicsStep", timeStep=0.01)
                    except Exception as exc:
                        raise ProbeUnavailable(f"native time action failed at AdvancePhysicsStep: {type(exc).__name__}: {exc}") from exc
                    if index in sample_indices:
                        controlled.append(_snapshot(ctx, f"{name}_physics_{index}_steps"))
                final = {"temperature": ctx.field("probe_object", "temperature"),
                         "object": ctx.obj("probe_object"), "knob": ctx.obj("target_knob"),
                         "burner": ctx.obj("target_burner")}
                try:
                    unpause_result = ctx.step("UnpausePhysicsAutoSim")
                    paused = False
                    steps.append({"label": f"{name}_unpause_auto_sim", "action": "UnpausePhysicsAutoSim",
                                  "kwargs": {}, "record": copy.deepcopy(unpause_result.record),
                                  "snapshot": _snapshot(ctx, f"{name}_unpause_auto_sim")})
                except Exception as exc:
                    raise ProbeUnavailable(f"native time action failed at UnpausePhysicsAutoSim: {type(exc).__name__}: {exc}") from exc
                return {"initial_hot_state": hot_baseline, "final": final,
                        "heat_precondition_samples": heat_observations,
                        "controlled_time_samples": controlled,
                        "requested_simulated_seconds": 4.0,
                        "time_step_seconds": 0.01, "advance_step_count": 400,
                        "attribute_clock_verified": False,
                        "setup_wall_seconds": time.monotonic() - setup_start}
            except Exception as exc:
                cleanup_error = None
                if paused:
                    try:
                        cleanup_result = ctx.step("UnpausePhysicsAutoSim")
                        paused = False
                        steps.append({"label": f"{name}_unpause_after_error", "action": "UnpausePhysicsAutoSim",
                                      "kwargs": {}, "record": copy.deepcopy(cleanup_result.record),
                                      "snapshot": _snapshot(ctx, f"{name}_unpause_after_error")})
                    except Exception as cleanup_exc:
                        cleanup_error = f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                prefix = str(exc) if "native time action failed" in str(exc) else (
                    f"native-time trial setup/observation failed: {type(exc).__name__}: {exc}")
                raise ProbeUnavailable(f"{prefix}; unpause_cleanup_error={cleanup_error!r}") from exc

        if turn_off:
            steps.append(_step(ctx, f"{name}_target_source_off", "ToggleObjectOff",
                               objectId=knob_id, forceAction=True))
        wall_start = time.monotonic()
        pass_count = 100 if turn_off else 101
        samples = []
        for index in range(1, pass_count + 1):
            ctx.step("Pass")
            if index in {1, 10, 50, 100, 101}:
                samples.append(_snapshot(ctx, f"{name}_wallcount_pass_{index}"))
        return {"initial_hot_state": hot_baseline,
                "final": {"temperature": ctx.field("probe_object", "temperature"),
                          "object": ctx.obj("probe_object"), "knob": ctx.obj("target_knob"),
                          "burner": ctx.obj("target_burner")},
                "heat_precondition_samples": heat_observations,
                "wallcount_samples": samples, "pass_count": pass_count,
                "event_plus_pass_actions": pass_count + (1 if turn_off else 0),
                "observation_wall_seconds": time.monotonic() - wall_start,
                "setup_wall_seconds": time.monotonic() - setup_start}

    arms = (("native_target", True, True), ("native_control", True, False),
            ("wall_target", False, True), ("wall_control", False, False))
    native_supported = True
    abort_after_cleanup_failure = False
    for index, (name, native, turn_off) in enumerate(arms):
        if abort_after_cleanup_failure:
            trials[name] = {"status": "skipped_after_failed_unpause_cleanup"}
            continue
        if index:
            segment = _save_action_segment(ctx, f"F9_{arms[index-1][0]}")
            trials[arms[index-1][0]]["action_file"] = segment
            ctx.session.reset(initial_scene)
        try:
            trials[name] = run_arm(name, native_time=native, turn_off=turn_off)
        except Exception as exc:
            if native:
                native_supported = False
                trials[name] = {"status": "unsupported_native_time_control" if
                                "native time action failed" in str(exc) else "inconclusive_setup",
                                "error": f"{type(exc).__name__}: {exc}",
                                "partial_action_ledger": copy.deepcopy(ctx.session.records)}
                _save_action_segment(ctx, f"F9_{name}_partial")
                if "unpause_cleanup_error=None" not in str(exc):
                    abort_after_cleanup_failure = True
                continue
            trials[name] = {"status": "inconclusive_setup", "error": f"{type(exc).__name__}: {exc}",
                            "partial_action_ledger": copy.deepcopy(ctx.session.records)}
            _save_action_segment(ctx, f"F9_{name}_partial")
    if "wall_control" in trials and "final" in trials["wall_control"]:
        _save_action_segment(ctx, f"F9_{arms[-1][0]}")
    native_contrast = None
    if "native_target" in trials and "native_control" in trials and "final" in trials["native_target"] and "final" in trials["native_control"]:
        native_contrast = {"target_final": trials["native_target"]["final"]["temperature"],
                           "control_final": trials["native_control"]["final"]["temperature"],
                           "requested_simulated_seconds_each": 4.0}
    wall_contrast = None
    if "wall_target" in trials and "wall_control" in trials and "final" in trials["wall_target"] and "final" in trials["wall_control"]:
        wall_contrast = {"target_final": trials["wall_target"]["final"]["temperature"],
                         "control_final": trials["wall_control"]["final"]["temperature"],
                         "target_passes": trials["wall_target"]["pass_count"],
                         "control_passes": trials["wall_control"]["pass_count"],
                         "target_wall_seconds": trials["wall_target"]["observation_wall_seconds"],
                         "control_wall_seconds": trials["wall_control"]["observation_wall_seconds"],
                         "equal_total_action_count": (
                             trials["wall_target"]["event_plus_pass_actions"] ==
                             trials["wall_control"]["event_plus_pass_actions"])}
    _check(ctx, "native_physics_time_control_completed", native_supported,
           {"native_target": trials.get("native_target"), "native_control": trials.get("native_control")})
    _check(ctx, "wallcount_control_completed", wall_contrast is not None, wall_contrast)
    _check(ctx, "wallcount_arms_have_equal_total_action_count",
           bool(wall_contrast and wall_contrast["equal_total_action_count"]), wall_contrast)
    # A cooling effect is supported only when target-source removal reaches
    # RoomTemp while a matched, continuing-source arm stays Hot. Otherwise
    # report the trajectory without claiming causal separation.
    status = "inconclusive"
    if native_contrast and native_contrast["target_final"] == "RoomTemp" and native_contrast["control_final"] == "Hot":
        status = "observed_supported"
    elif native_contrast and native_contrast["target_final"] == "Hot" and native_contrast["control_final"] == "RoomTemp":
        status = "observed_counterexample"
    return _base(case_id, "F9", "background_evolution_time_control", status,
                 checks=checks, steps=steps, trials=trials,
                 native_fixed_time_contrast=native_contrast, wallcount_contrast=wall_contrast,
                 native_time_actions_status="supported" if native_supported else "unsupported_or_setup_failed",
                 claim_scope="This result concerns only the tested Kettle, mapped StoveKnob/StoveBurner, scene, and ObjectTemperature contrast.",
                 confounds=["heating-to-Hot precondition is separately recorded and may vary in setup wall time",
                            "native observation uses requested fixed physics steps at 0.01 seconds each",
                            "Pass-count wall-time arms are comparisons, not equal simulated-time evidence",
                            "temperature persistence may delay observed cooling"],
                 interpretation={"cooling_was_measured": True,
                                 "causal_attribution_requires_native_fixed_time_contrast": True,
                                 "attribute_clock_unverified": True,
                                 "fixed_physics_time_claim_is_limited_to_this_observed_temperature_contrast": True,
                                 "Pass count is never called physical time": True})


def _f10(kind: str) -> Callable[[Any], dict[str, Any]]:
    def run(ctx: Any) -> dict[str, Any]:
        case_id = f"F10_nested_{kind}"
        checks, steps = ctx.checks, []
        from nested_setup import establish_nested
        if kind == "carry":
            surface = ctx.select("support", "CounterTop", capability="receptacle")
            setup = establish_nested(ctx, scene=ctx.session.scene,
                roles={"support": surface},
                candidates={
                    "outer": (("Plate", "Bowl"), ("pickupable", "receptacle")),
                    "inner": (("Bowl", "Cup", "Mug"), ("pickupable", "receptacle")),
                    "content": (("Apple", "Potato"), ("pickupable",)),
                },
                edges=(("outer", "support"), ("inner", "outer"), ("content", "inner")))
            ctx.bind("source", ctx.roles["outer"])
            _snapshot(ctx, "nested_chain_before_pickup")
            content_before_event = ctx.obj("content")
            inner_before_event = ctx.obj("inner")
            relative_before = _vector_delta(ctx.obj("inner").get("position"),
                                            ctx.obj("content").get("position"))
            _check(ctx, "nested_chain_confirmed_before_outer_pickup",
                   ctx.roles["outer"] in _parents(inner_before_event) and
                   ctx.roles["inner"] in _parents(content_before_event),
                   {"content_before_event": content_before_event,
                    "inner_before_event": inner_before_event,
                    "relative_position_after": relative_before,
                    "construction_order": ["outer_to_final_support", "inner_into_outer", "content_into_inner"],
                    "candidate_search": setup})
            before = {name: ctx.obj(name) for name in ("outer", "inner", "content")}
            steps.append(_step(ctx, "pickup_outer", "PickupObject", objectId=ctx.roles["outer"], forceAction=True))
            trajectory = ctx.observe(steps=(0, 1, 4, 12, 36))
            metrics = []
            for row in trajectory:
                by_id = {o.get("objectId"): o for o in row.get("metadata", {}).get("objects", [])}
                after = {name: by_id.get(ctx.roles[name], {}) for name in ("outer", "inner", "content")}
                outer_delta = _vector_delta(before["outer"].get("position"), after["outer"].get("position"))
                inner_delta = _vector_delta(before["inner"].get("position"), after["inner"].get("position"))
                content_delta = _vector_delta(before["content"].get("position"), after["content"].get("position"))
                relative_now = _vector_delta(after["inner"].get("position"), after["content"].get("position"))
                metrics.append({"capture_label": row.get("label"),
                                "outer_displacement_m": _distance(before["outer"].get("position"), after["outer"].get("position")),
                                "inner_vs_outer_displacement_error_m": _vector_error(inner_delta, outer_delta),
                                "content_vs_outer_displacement_error_m": _vector_error(content_delta, outer_delta),
                                "content_inner_relative_position_error_m": _vector_error(relative_before, relative_now)})
            moved = [m for m in metrics if m["outer_displacement_m"] is not None and m["outer_displacement_m"] > 0.05]
            passed = bool(moved) and all(m["inner_vs_outer_displacement_error_m"] is not None and
                                         m["inner_vs_outer_displacement_error_m"] < 0.10 and
                                         m["content_vs_outer_displacement_error_m"] is not None and
                                         m["content_vs_outer_displacement_error_m"] < 0.10 and
                                         m["content_inner_relative_position_error_m"] is not None and
                                         m["content_inner_relative_position_error_m"] < 0.10 for m in moved)
            _check(ctx, "nested_children_relative_motion_follows_outer", passed,
                   {"metrics": metrics, "before": before})
            after = {name: ctx.obj(name) for name in ("outer", "inner", "content")}
            status = "inconclusive" if not moved else ("observed_supported" if passed else "observed_counterexample")
            return _base(case_id, "F10", "nested_carry", status,
                         checks=checks, steps=steps, before=before, after=after,
                         trajectory=trajectory, motion_metrics=metrics, construction_plan=setup,
                         interpretation={"only_nested_carry_was_tested": True})
        if kind == "heat":
            _bind_selected(ctx, "source", "Microwave", "toggleable")
            ctx.bind("outer", ctx.roles["source"])
            ctx.toggle("source", False)
            ctx.ops.set_open(ctx.roles["source"], True)
            _snapshot(ctx, "microwave_open_for_nested_setup")
            setup = establish_nested(ctx, scene=ctx.session.scene,
                roles={"source": ctx.roles["source"], "outer": ctx.roles["outer"]},
                candidates={
                    "inner": (("Bowl", "Cup", "Mug"), ("pickupable", "receptacle")),
                    "content": (("Potato", "Apple"), ("pickupable",)),
                },
                edges=(("inner", "outer"), ("content", "inner")),
                after_reset=lambda current: current.ops.set_open(current.roles["source"], True))
            relation_before_event = {
                "content_in_inner": ctx.roles["inner"] in _parents(ctx.obj("content")),
                "inner_in_source": ctx.roles["source"] in _parents(ctx.obj("inner")),
                "source_is_open": ctx.obj("source").get("isOpen"),
            }
            ctx.require(relation_before_event["content_in_inner"] and relation_before_event["inner_in_source"] and
                        relation_before_event["source_is_open"] is True,
                        f"F10 nested heat setup did not establish open nested containment: {relation_before_event!r}")
            ctx.ops.set_open(ctx.roles["source"], False)
            _snapshot(ctx, "microwave_closed_before_nested_heat_event")
            relation_before_event.update({"source_is_open_after_close": ctx.obj("source").get("isOpen"),
                                          "content_parent_after_close": _parents(ctx.obj("content")),
                                          "inner_parent_after_close": _parents(ctx.obj("inner"))})
            ctx.require(relation_before_event["source_is_open_after_close"] is False and
                        ctx.roles["inner"] in relation_before_event["content_parent_after_close"] and
                        ctx.roles["source"] in relation_before_event["inner_parent_after_close"],
                        f"F10 nested containment changed on closing microwave: {relation_before_event!r}")
            initial = ctx.field("content", "temperature")
            if initial is None:
                raise ProbeUnavailable("F10 nested heat candidate lacks ObjectTemperature metadata")
            steps.append(_step(ctx, "microwave_on", "ToggleObjectOn", objectId=ctx.roles["source"], forceAction=True))
            # Keep the 36 native Pass calls; choose images through the shared
            # sampling policy instead of saving one for every observation step.
            trajectory = ctx.observe(steps=tuple(sorted({0, 36} | {
                n for n in ctx.sample_steps if n <= 36})), total_steps=36)
            final = ctx.field("content", "temperature")
            changed = final != initial
            nested_relation_preserved = (ctx.roles["inner"] in _parents(ctx.obj("content")) and
                                         ctx.roles["source"] in _parents(ctx.obj("inner")))
            _check(ctx, "nested_relation_preserved_through_heating", nested_relation_preserved,
                   {"content_parents": _parents(ctx.obj("content")),
                    "inner_parents": _parents(ctx.obj("inner"))})
            _check(ctx, "nested_content_temperature_changed", changed,
                   {"initial": initial, "final": final, "inner": ctx.obj("inner"),
                    "source": ctx.obj("source")})
            return _base(case_id, "F10", "nested_heat",
                         "observed_supported" if changed and nested_relation_preserved else "inconclusive",
                         checks=checks, steps=steps, initial_temperature=initial, final_temperature=final,
                         trajectory=trajectory, observation_passes=36,
                         setup_search=setup,
                         construction_plan=setup,
                         interpretation={"only_nested_heating_was_tested": True,
                                         "failure_to_change_is_not_a_clean_negative_without_timing_controls": True})
        # Independent wash probe. Use native sink/faucet state and require a
        # real content-property change; basin membership alone is insufficient.
        _bind_selected(ctx, "source", "Faucet", "toggleable")
        _bind_selected(ctx, "basin", "SinkBasin", "receptacle")
        ctx.bind("outer", ctx.roles["basin"])
        ctx.toggle("source", False)
        setup = establish_nested(ctx, scene=ctx.session.scene,
            roles={"source": ctx.roles["source"], "basin": ctx.roles["basin"], "outer": ctx.roles["outer"]},
            candidates={
                "inner": (("Bowl", "Cup", "Mug"), ("pickupable", "receptacle")),
                "content": (("Plate", "Mug", "Cup"), ("pickupable", "dirtyable")),
            },
            edges=(("inner", "basin"), ("content", "inner")))
        if ctx.obj("content").get("isDirty") is not True:
            ctx.ops.set_dirty(ctx.roles["content"], True)
            ctx.require(ctx.obj("content").get("isDirty") is True,
                        "Native set-dirty action did not establish the wash precondition")
        initial = ctx.obj("content").get("isDirty")
        _snapshot(ctx, "nested_dirty_chain_before_water_on")
        steps.append(_step(ctx, "faucet_on", "ToggleObjectOn", objectId=ctx.roles["source"], forceAction=True))
        trajectory = ctx.observe(steps=tuple(sorted({0, 36} | {
            n for n in ctx.sample_steps if n <= 36})), total_steps=36)
        final = ctx.obj("content").get("isDirty")
        changed = initial is True and final is False
        nested_relation_preserved = (ctx.roles["inner"] in _parents(ctx.obj("content")) and
                                     ctx.roles["basin"] in _parents(ctx.obj("inner")))
        _check(ctx, "nested_relation_preserved_through_washing", nested_relation_preserved,
               {"content_parents": _parents(ctx.obj("content")),
                "inner_parents": _parents(ctx.obj("inner"))})
        _check(ctx, "nested_content_cleaned", changed,
               {"initial_isDirty": initial, "final_isDirty": final,
                "inner_parent_ids": _parents(ctx.obj("inner")), "content": ctx.obj("content")})
        return _base(case_id, "F10", "nested_wash",
                     "observed_supported" if changed and nested_relation_preserved else "inconclusive",
                     checks=checks, steps=steps, setup_search=setup,
                     trajectory=trajectory, observation_passes=36,
                     construction_plan=setup,
                     initial_isDirty=initial, final_isDirty=final,
                     interpretation={"basin_relation_alone_is_not_water_contact_evidence": True,
                                     "only_nested_cleaning_was_tested": True})
    return run


def _f11(ctx: Any) -> dict[str, Any]:
    case_id = "F11_redundant_support"
    checks, steps = ctx.checks, []
    pairs = _pick_two_stove_mappings(ctx)
    distinct = next((p for p in pairs[1:] if p[0] != pairs[0][0] and p[1] != pairs[0][1]), None) if pairs else None
    if distinct is None:
        return _base(case_id, "F11", "redundant_property_support", "inconclusive",
                     checks=checks, steps=steps, reason="unsupported_setup",
                     search_failure={"condition": "two distinct native controls were unavailable",
                                     "candidate_mapping_count": len(pairs),
                                     "mappings": pairs},
                     epistemic_boundary="This rules out this construction in the current scene only; it does not deny all AI2-THOR configurations.")
    # The current scene exposes two controls, but a single object generally
    # cannot be natively placed on both burners at once. Do not fabricate a
    # joint support condition from proximity or controlledObjects metadata.
    _bind_selected(ctx, "probe_object", "Kettle", "pickupable")
    initial_scene = ctx.session.scene
    first, second = pairs[0], distinct
    burner_a, burner_b = ctx.obj(first[1]), ctx.obj(second[1])
    center_distance = _distance(burner_a.get("position"), burner_b.get("position"))
    obj_bounds = ctx.obj("probe_object").get("axisAlignedBoundingBox") or {}
    extent = obj_bounds.get("size") if isinstance(obj_bounds, dict) else None
    if not isinstance(extent, dict):
        extent = {}
    nominal_span = max((float(extent.get(k, 0.0) or 0.0) for k in ("x", "y", "z")), default=0.0)
    if center_distance is None or center_distance > max(nominal_span, 0.0):
        return _base(case_id, "F11", "redundant_property_support", "inconclusive",
                     checks=checks, steps=steps, reason="unsupported_setup",
                     search_failure={"condition": "no demonstrated joint physical influence region",
                                     "burner_center_distance_m": center_distance,
                                     "probe_object_bbox_max_span_m": nominal_span,
                                     "mappings": [first, second],
                                     "required_followup": "Find a native position where the same property is verified under A-only, B-only, and both, then withdraw each source separately."},
                     epistemic_boundary="Distance and bounding boxes are diagnostic only; they do not certify thermal support or its absence.")
    # Geometry is only a candidate-search heuristic. Attempt one native
    # placement at the two-burner midpoint, then require measured outcomes in
    # every intervention arm before accepting any redundant-support claim.
    midpoint = {}
    for axis in ("x", "y", "z"):
        midpoint[axis] = (float(burner_a.get("position", {})[axis]) +
                          float(burner_b.get("position", {})[axis])) / 2.0
    try:
        placed = ctx.step("PlaceObjectAtPoint", objectId=ctx.roles["probe_object"], position=midpoint)
        placed_snapshot = _snapshot(ctx, "f11_midpoint_candidate_placed")
        steps.append({"label": "place_midpoint_candidate", "action": "PlaceObjectAtPoint",
                      "kwargs": {"position": midpoint},
                      "record": copy.deepcopy(getattr(placed, "record", {})),
                      "snapshot": placed_snapshot})
    except Exception as exc:
        return _base(case_id, "F11", "redundant_property_support", "inconclusive",
                     checks=checks, steps=steps, reason="unsupported_setup",
                     search_failure={"condition": "native midpoint placement failed",
                                     "error": f"{type(exc).__name__}: {exc}",
                                     "midpoint": midpoint, "mappings": [first, second]},
                     epistemic_boundary="The failed placement establishes only that this candidate was unavailable in this scene.")
    placement_error = _distance(ctx.obj("probe_object").get("position"), midpoint)
    if placement_error is None or placement_error > 0.15:
        return _base(case_id, "F11", "redundant_property_support", "inconclusive",
                     checks=checks, steps=steps, reason="unsupported_setup",
                     search_failure={"condition": "native placement did not put the object near the candidate point",
                                     "midpoint": midpoint, "actual_position": ctx.obj("probe_object").get("position"),
                                     "placement_error_m": placement_error},
                     epistemic_boundary="Position proximity does not prove common heating; it only determines whether intervention trials can proceed.")
    _check(ctx, "midpoint_candidate_position_reached", True,
           {"midpoint": midpoint, "actual": ctx.obj("probe_object").get("position"),
            "diagnostic_only": True})
    # Preserve the candidate-search action ledger before any reset. The common
    # runner's normal flush only sees the final reset segment.
    search_action_file = _save_action_segment(ctx, "F11_midpoint_candidate_search")
    ctx.session.reset(initial_scene)
    arms: dict[str, Any] = {}
    setup_errors: dict[str, Any] = {}
    cleanup_errors: dict[str, Any] = {}
    paused_state = {"paused": False}
    arm_names = ("Aonly", "Bonly", "both", "withdrawA", "withdrawB", "neither")

    def set_source(alias: str, desired: bool, arm: str) -> None:
        if ctx.obj(alias).get("isToggled") is not desired:
            steps.append(_step(ctx, f"{arm}_{alias}_{'on' if desired else 'off'}",
                               "ToggleObjectOn" if desired else "ToggleObjectOff",
                               objectId=ctx.roles[alias], forceAction=True))

    def verify_burners(arm: str, a_on: bool, b_on: bool, stage: str) -> None:
        actual = {"A": ctx.obj("burner_a").get("isToggled"),
                  "B": ctx.obj("burner_b").get("isToggled")}
        expected = {"A": a_on, "B": b_on}
        _check(ctx, f"{arm}_{stage}_burner_states_match", actual == expected,
               {"actual": actual, "expected": expected})
        ctx.require(actual == expected,
                    f"{arm}: burner state did not match source intervention at {stage}: {actual!r}")

    def advance_seconds(arm: str, seconds: float) -> list[dict[str, Any]]:
        count = int(round(seconds / 0.01))
        samples = []
        sample_at = {1, 10, 50, 100, 200, 400}
        for index in range(1, count + 1):
            ctx.step("AdvancePhysicsStep", timeStep=0.01)
            if index in sample_at or index == count:
                samples.append(_snapshot(ctx, f"{arm}_physics_{index}_steps"))
        return samples

    def configure_and_pause(arm: str) -> None:
        ctx.bind("knob_a", first[0]); ctx.bind("burner_a", first[1])
        ctx.bind("knob_b", second[0]); ctx.bind("burner_b", second[1])
        _bind_selected(ctx, "probe_object", "Kettle", "pickupable")
        for index, control_id in enumerate(_native_stove_knobs(ctx)):
            alias = f"{arm}_candidate_knob_{index}"
            ctx.bind(alias, control_id)
            if ctx.obj(alias).get("isToggled") is True:
                steps.append(_step(ctx, f"{arm}_{alias}_initial_off", "ToggleObjectOff",
                                   objectId=control_id, forceAction=True))
        if ctx.field("probe_object", "temperature") != "RoomTemp":
            ctx.observe(steps=(0, 1, 4, 12, 36, 72, 120, 240))
        ctx.require(ctx.field("probe_object", "temperature") == "RoomTemp",
                    f"{arm}: no verified RoomTemp baseline with candidate sources off")
        placed = ctx.step("PlaceObjectAtPoint", objectId=ctx.roles["probe_object"], position=midpoint)
        steps.append({"label": f"{arm}_place_common_candidate", "action": "PlaceObjectAtPoint",
                      "kwargs": {"position": midpoint}, "record": copy.deepcopy(placed.record),
                      "snapshot": _snapshot(ctx, f"{arm}_candidate_placed")})
        error = _distance(ctx.obj("probe_object").get("position"), midpoint)
        ctx.require(error is not None and error <= 0.15,
                    f"{arm}: object did not reach the common candidate point; error={error!r}")
        ctx.require(ctx.field("probe_object", "temperature") == "RoomTemp",
                    f"{arm}: placement did not preserve RoomTemp baseline")
        paused_state["paused"] = True
        pause_result = ctx.step("PausePhysicsAutoSim")
        steps.append({"label": f"{arm}_pause_auto_sim", "action": "PausePhysicsAutoSim",
                      "kwargs": {}, "record": copy.deepcopy(pause_result.record),
                      "snapshot": _snapshot(ctx, f"{arm}_pause_auto_sim")})

    previous_arm = None
    for arm_index, arm in enumerate(arm_names):
        if cleanup_errors:
            setup_errors[arm] = {"status": "skipped_after_failed_unpause_cleanup"}
            continue
        if arm_index:
            if previous_arm:
                _save_action_segment(ctx, f"F11_{previous_arm}")
            ctx.session.reset(initial_scene)
        try:
            configure_and_pause(arm)
            preheat_requested_seconds = 0.0
            if arm in {"withdrawA", "withdrawB", "neither"}:
                set_source("knob_a", True, arm)
                set_source("knob_b", True, arm)
                verify_burners(arm, True, True, "both_preheat_start")
                preheat_samples = advance_seconds(arm + "_both_preheat", 4.0)
                preheat_requested_seconds += 4.0
                # Give the paired source condition additional fixed-time blocks
                # when needed; no fixed-temperature action is used.
                for block in range(4):
                    if ctx.field("probe_object", "temperature") == "Hot":
                        break
                    preheat_samples.extend(advance_seconds(f"{arm}_both_preheat_block_{block+2}", 4.0))
                    preheat_requested_seconds += 4.0
                ctx.require(ctx.field("probe_object", "temperature") == "Hot",
                            f"{arm}: both sources did not produce Hot in up to 20 simulated seconds")
            else:
                expected_a = arm in {"Aonly", "both"}
                expected_b = arm in {"Bonly", "both"}
                set_source("knob_a", expected_a, arm)
                set_source("knob_b", expected_b, arm)
                verify_burners(arm, expected_a, expected_b, "single_or_both_source_start")
                preheat_samples = []
                for block in range(5):
                    preheat_samples.extend(advance_seconds(f"{arm}_preheat_block_{block+1}", 4.0))
                    preheat_requested_seconds += 4.0
                    if ctx.field("probe_object", "temperature") == "Hot":
                        break
            if arm == "withdrawA":
                set_source("knob_a", False, arm)
            elif arm == "withdrawB":
                set_source("knob_b", False, arm)
            elif arm == "neither":
                set_source("knob_a", False, arm); set_source("knob_b", False, arm)
            if arm == "withdrawA":
                verify_burners(arm, False, True, "after_withdraw_A")
            elif arm == "withdrawB":
                verify_burners(arm, True, False, "after_withdraw_B")
            elif arm == "neither":
                verify_burners(arm, False, False, "after_withdraw_all")
            observation_samples = []
            observation_requested_seconds = 0.0
            if arm == "neither":
                # Continue fixed-time cooling until RoomTemp or a bounded 60s.
                for block in range(15):
                    observation_samples.extend(advance_seconds(f"{arm}_cool_block_{block+1}", 4.0))
                    observation_requested_seconds += 4.0
                    if ctx.field("probe_object", "temperature") == "RoomTemp":
                        break
            else:
                observation_samples = advance_seconds(f"{arm}_post_intervention", 4.0)
                observation_requested_seconds = 4.0
            arm_final = {"temperature": ctx.field("probe_object", "temperature"),
                         "object": ctx.obj("probe_object"),
                         "knob_a": ctx.obj("knob_a"), "knob_b": ctx.obj("knob_b"),
                         "burner_a": ctx.obj("burner_a"), "burner_b": ctx.obj("burner_b")}
            unpause_result = ctx.step("UnpausePhysicsAutoSim")
            paused_state["paused"] = False
            steps.append({"label": f"{arm}_unpause_auto_sim", "action": "UnpausePhysicsAutoSim",
                          "kwargs": {}, "record": copy.deepcopy(unpause_result.record),
                          "snapshot": _snapshot(ctx, f"{arm}_unpause_auto_sim")})
            arms[arm] = {**arm_final,
                         "preheat_samples": preheat_samples,
                         "observation_samples": observation_samples,
                         "requested_preheat_seconds": preheat_requested_seconds,
                         "requested_observation_seconds": observation_requested_seconds,
                         "time_step_seconds": 0.01,
                         "arm_requires_both_before_withdrawal": arm in {"withdrawA", "withdrawB", "neither"}}
        except Exception as exc:
            setup_errors[arm] = {"error": f"{type(exc).__name__}: {exc}",
                                 "partial_actions": copy.deepcopy(ctx.session.records)}
        finally:
            if paused_state["paused"]:
                try:
                    cleanup_result = ctx.step("UnpausePhysicsAutoSim")
                    paused_state["paused"] = False
                    steps.append({"label": f"{arm}_unpause_after_error", "action": "UnpausePhysicsAutoSim",
                                  "kwargs": {}, "record": copy.deepcopy(cleanup_result.record),
                                  "snapshot": _snapshot(ctx, f"{arm}_unpause_after_error")})
                except Exception as cleanup_exc:
                    cleanup_errors[arm] = f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                    setup_errors.setdefault(arm, {})["unpause_cleanup_error"] = cleanup_errors[arm]
            previous_arm = arm
    final_segment_name = previous_arm or "candidate_search"
    _save_action_segment(ctx, f"F11_{final_segment_name}")
    independent = all(arms.get(name, {}).get("temperature") == "Hot"
                      for name in ("Aonly", "Bonly", "both", "withdrawA", "withdrawB"))
    decayed = arms.get("neither", {}).get("temperature") == "RoomTemp"
    _check(ctx, "same_property_supported_by_each_source_after_fresh_reset", independent, arms)
    _check(ctx, "neither_sources_eventually_returned_to_room_temp", decayed,
           arms.get("neither", {"setup_error": setup_errors.get("neither")}))
    status = "observed_supported" if independent and decayed and not setup_errors else "inconclusive"
    return _base(case_id, "F11", "redundant_property_support", status,
                 checks=checks, steps=steps, reason=None if status == "observed_supported" else "unsupported_setup_or_unresolved_timing",
                 candidate_intervention_arms=arms, setup_errors=setup_errors,
                 cleanup_errors=cleanup_errors,
                 candidate_search_actions=search_action_file,
                 per_arm_actions={arm: f"F11_{arm}_actions.json" for arm in arm_names
                                  if arm in arms or (arm in setup_errors and
                                      setup_errors[arm].get("status") != "skipped_after_failed_unpause_cleanup")},
                 burner_center_distance_m=center_distance,
                 probe_object_bbox_max_span_m=nominal_span,
                 interpretation={"each_intervention_arm_started_from_a_fresh_scene_reset_and_RoomTemp": True,
                                 "withdrawA_and_withdrawB_each_started_with_both_sources_on_and_Hot": True,
                                 "neither_required_natural_decay_to_RoomTemp_within_60_simulated_seconds": True,
                                 "temperature_was_never_directly_set": True,
                                 "attribute_clock_unverified": True,
                                 "geometry_and_control_metadata_are_not_effect_evidence": True})


def cases() -> list[ProbeCase]:
    """Return independent probes; the runner should reset the scene per case."""
    result = [
        ProbeCase("F7_removed", "F7", "current_carry_relation", _f7("removed")),
        ProbeCase("F7_returned", "F7", "current_carry_relation", _f7("returned")),
        ProbeCase("F7_retained", "F7", "current_carry_relation", _f7("retained")),
        ProbeCase("F8_control_A", "F8", "local_control_mapping", _f8(0, False)),
        ProbeCase("F8_control_B", "F8", "local_control_mapping", _f8(1, False)),
        ProbeCase("F8_control_A_swapped", "F8", "local_control_mapping", _f8(0, True)),
        ProbeCase("F8_control_B_swapped", "F8", "local_control_mapping", _f8(1, True)),
        ProbeCase("F9_matched_time", "F9", "background_evolution_time_control", _f9),
        ProbeCase("F10_nested_carry", "F10", "nested_carry", _f10("carry")),
        ProbeCase("F10_nested_heat", "F10", "nested_heat", _f10("heat")),
        ProbeCase("F10_nested_wash", "F10", "nested_wash", _f10("wash")),
        ProbeCase("F11_redundant_support", "F11", "redundant_property_support", _f11),
    ]
    return result


__all__ = ["cases"]
