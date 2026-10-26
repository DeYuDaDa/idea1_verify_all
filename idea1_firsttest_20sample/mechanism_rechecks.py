"""R1/R2 bounded native rechecks. No Unity or environment work at import time."""
from __future__ import annotations

import math
import time
from typing import Any

from mechanism_probe_common import ProbeCase, ProbeUnavailable, native_temperature

RELATIONS = ("intact", "apple_out", "bowl_and_apple_out", "apple_reparented")
ROLES = ("outer", "inner", "content")
SAMPLES = (0, 1, 4, 12, 36)
# Existing successful trace: ~3.756m movement, <=10.66mm following error.
# These are explicit operational tolerances, not simulator universal constants.
MOVED_M, FOLLOW_ERROR_M, STATIONARY_M = 0.05, 0.03, 0.02


def state(ctx, role):
    obj = ctx.obj(role)
    return {"objectId": obj["objectId"], "objectType": obj.get("objectType"),
            "position": obj.get("position"),
            "parentReceptacles": obj.get("parentReceptacles"),
            "receptacleObjectIds": obj.get("receptacleObjectIds"),
            "temperature": native_temperature(obj), "isCooked": obj.get("isCooked"),
            "isToggled": obj.get("isToggled"), "isOpen": obj.get("isOpen")}


def vector(a, b):
    try:
        values = tuple(float(b[k]) - float(a[k]) for k in ("x", "y", "z"))
        return values if all(math.isfinite(v) for v in values) else None
    except (TypeError, KeyError, ValueError):
        return None


def norm(v):
    return math.sqrt(sum(x*x for x in v)) if v is not None else None


def relation(ctx, child, parent):
    c, p = ctx.obj(child), ctx.obj(parent)
    return (p["objectId"] in (c.get("parentReceptacles") or []) and
            c["objectId"] in (p.get("receptacleObjectIds") or []))


def unrelated(ctx, child, parent):
    c, p = ctx.obj(child), ctx.obj(parent)
    return (p["objectId"] not in (c.get("parentReceptacles") or []) and
            c["objectId"] not in (p.get("receptacleObjectIds") or []))


def expected_follow(configuration):
    return {"outer": True, "inner": configuration in {"intact", "apple_out"},
            "content": configuration in {"intact", "apple_reparented"}}


def evaluate_motion(before, samples, configuration, pickup):
    expected = expected_follow(configuration)
    metrics, ok = [], True
    for sample in samples:
        deltas = {r: vector(before[r].get("position"), sample[r].get("position")) for r in ROLES}
        distances = {r: norm(deltas[r]) for r in ROLES}
        errors = {r: norm(tuple(a-b for a, b in zip(deltas[r], deltas["outer"])))
                  if deltas[r] is not None and deltas["outer"] is not None else None
                  for r in ROLES}
        valid = all(v is not None for v in distances.values())
        if valid:
            valid = (distances["outer"] > MOVED_M if pickup else distances["outer"] < STATIONARY_M)
            for r in ("inner", "content"):
                valid = valid and (errors[r] < FOLLOW_ERROR_M and distances[r] > MOVED_M
                                   if pickup and expected[r] else distances[r] < STATIONARY_M)
        ok = ok and valid
        metrics.append({"pass": sample.get("pass"), "displacement_m": distances,
                        "vs_outer_vector_error_m": errors, "matches_expectation": valid})
    return {"passed": bool(samples) and ok, "expected_follow_on_pickup": expected,
            "metrics": metrics, "thresholds_m": {"outer_moved": MOVED_M,
            "follow_vector_error": FOLLOW_ERROR_M, "stationary": STATIONARY_M}}


def optional_setup_view(ctx, role):
    """Only before final precondition checks; never during the measured event."""
    if ctx.view_mode != "passive":
        return
    try:
        ctx.ops.look(ctx.roles[role])
        detail = {"target": role, "status": "aimed_before_measurement"}
    except Exception as exc:
        detail = {"target": role, "status": "unavailable", "error": str(exc)}
    # Not a mechanism check: failure does not change the native result.
    ctx.capture("optional_setup_view", image=False)
    ctx.captures[-1]["optional_view_attempt"] = detail
    print(f"  Preview setup: {detail['status']} ({role}); native preconditions checked next", flush=True)


def external_surface(ctx, origin):
    """Use an existing different countertop; do not place an outsider on the same support."""
    excluded = ctx.roles.get(origin, origin)
    candidates = [o for o in ctx.session.snapshot().get("objects", [])
                  if o.get("objectType") == "CounterTop" and o.get("receptacle") is True
                  and o["objectId"] != excluded]
    center = ctx.obj(origin).get("position")
    candidates = [o for o in candidates if vector(center, o.get("position")) is not None]
    ctx.require(bool(candidates), "No existing external countertop candidate")
    chosen = max(candidates, key=lambda o: norm(vector(center, o["position"])))
    return ctx.bind("external", chosen["objectId"])


def transfer(ctx, child, parent):
    """Native pickup/put preserves carried contents; no point teleport for removal."""
    try:
        ctx.ops.pickup_event(ctx.roles[child], look_first=False)
        ctx.put_event(child, parent)
        for _ in range(4):
            ctx.step("Pass")
    except Exception as exc:
        raise ProbeUnavailable(f"Native setup transfer {child}->{parent} failed: {exc}") from exc
    ctx.require(relation(ctx, child, parent), f"Transfer did not establish both relation directions: {child}->{parent}")
    ctx.capture(f"setup_transfer_{child}_to_{parent}")


def r1_preconditions(ctx, configuration):
    checks = {"outer_on_support": relation(ctx, "outer", "support")}
    if configuration in {"intact", "apple_out"}:
        checks["inner_on_outer"] = relation(ctx, "inner", "outer")
    else:
        checks["inner_off_outer"] = unrelated(ctx, "inner", "outer") and relation(ctx, "inner", "external")
    if configuration in {"intact", "bowl_and_apple_out"}:
        checks["apple_in_inner"] = relation(ctx, "content", "inner")
    elif configuration == "apple_out":
        checks["apple_on_external"] = relation(ctx, "content", "external")
        checks["apple_off_inner"] = unrelated(ctx, "content", "inner")
    else:
        checks["apple_directly_on_outer"] = relation(ctx, "content", "outer")
        checks["apple_off_inner"] = unrelated(ctx, "content", "inner")
    if configuration in {"apple_out", "bowl_and_apple_out"}:
        checks["apple_off_outer"] = unrelated(ctx, "content", "outer")
    checks["empty_hand"] = not bool(ctx.session.inventory())
    return checks


def r1(configuration, pickup):
    def run(ctx):
        from nested_setup import establish_nested
        support = ctx.select("support", "CounterTop", capability="receptacle")
        # Exact assets from Step40; no substitution after a failure.
        establish_nested(ctx, scene=ctx.session.scene, roles={"support": support},
            candidates={"outer": (("Plate",), ("pickupable", "receptacle")),
                        "inner": (("Bowl",), ("pickupable", "receptacle")),
                        "content": (("Apple",), ("pickupable",))},
            edges=(("outer", "support"), ("inner", "outer"), ("content", "inner")))
        ctx.bind("source", ctx.roles["outer"])
        if configuration != "intact":
            external_surface(ctx, "support")
            if configuration == "apple_out":
                transfer(ctx, "content", "external")
            else:
                transfer(ctx, "inner", "external")
                ctx.require(relation(ctx, "content", "inner") and unrelated(ctx, "content", "outer"),
                            "Bowl transfer did not preserve apple while disconnecting it from outer")
                if configuration == "apple_reparented":
                    transfer(ctx, "content", "outer")
        optional_setup_view(ctx, "outer")
        for _ in range(4):
            ctx.step("Pass")
        pre = r1_preconditions(ctx, configuration)
        ctx.check("r1_final_relation_configuration", all(pre.values()), pre)
        ctx.require(all(pre.values()), f"Final R1 configuration unavailable: {pre}")
        before = {r: state(ctx, r) for r in ROLES}
        ctx.capture("r1_before_event")
        event = ctx.step("PickupObject", objectId=ctx.roles["outer"], forceAction=True) if pickup else ctx.step("Pass")
        if pickup:
            ctx.require(any(o.get("objectId") == ctx.roles["outer"] for o in ctx.session.inventory()),
                        "Pickup receipt succeeded but outer not held")
        samples = []
        for row in ctx.observe(steps=SAMPLES):
            objects = {o["objectId"]: o for o in row["metadata"]["objects"]}
            samples.append({"pass": row["observation_passes"],
                            **{r: objects.get(ctx.roles[r], {}) for r in ROLES}})
        outcome = evaluate_motion(before, samples, configuration, pickup)
        detail = {"configuration": configuration, "pickup": pickup, "baseline": before,
                  "preconditions": pre, **outcome}
        ctx.check("r1_motion_pattern", outcome["passed"], detail)
        # A stationary outer cannot test propagation; a drifting no-event arm
        # reveals background motion rather than a successful event effect.
        outer_moved = all((m["displacement_m"]["outer"] or 0) > MOVED_M for m in outcome["metrics"])
        status = ("inconclusive" if (pickup and not outer_moved) or (not pickup and not outcome["passed"])
                  else "observed_supported" if outcome["passed"] else "observed_counterexample")
        return {"status": status, "suite": "R1", "configuration": configuration,
                "pickup": pickup, "event": event.record, "before": before,
                "after": {r: state(ctx, r) for r in ROLES}, "motion": outcome,
                "scope": "Current relation configuration vs co-motion; no claim about unique engine causal implementation."}
    return run


def poll_state(ctx, label, predicate, *, max_passes=1500, timeout_seconds=45):
    start, rows = time.monotonic(), []
    for n in range(max_passes + 1):
        current = state(ctx, "Potato")
        reached = bool(predicate(current))
        if reached or n % 20 == 0 or not rows or any(current[k] != rows[-1][k] for k in ("temperature", "isCooked")):
            rows.append({"pass": n, "elapsed_wall_seconds": time.monotonic()-start, **current})
        if reached or time.monotonic()-start >= timeout_seconds or n == max_passes:
            ctx.check(label, reached, {"final": current, "passes": n,
                      "elapsed_wall_seconds": time.monotonic()-start, "trace": rows,
                      "wall_time_is_not_simulated_time": True})
            ctx.capture(label)
            return reached
        ctx.step("Pass")
        time.sleep(0.05)
    return False


def evaluate_thermal(before, samples, cooked, inside):
    baseline_ok = before.get("temperature") == "RoomTemp" and before.get("isCooked") is cooked
    valid = bool(samples) and all(s.get("temperature") is not None and isinstance(s.get("isCooked"), bool) for s in samples)
    final = samples[-1] if samples else {}
    expected_temp, expected_cooked = ("Hot" if inside else "RoomTemp"), (True if inside else cooked)
    temp_ok = valid and (final.get("temperature") == "Hot" if inside else
                         all(s.get("temperature") == "RoomTemp" for s in samples))
    if cooked:
        cooked_ok = valid and all(s.get("isCooked") is True for s in samples)
    elif inside:
        cooked_ok = valid and final.get("isCooked") is True
    else:
        cooked_ok = valid and all(s.get("isCooked") is False for s in samples)
    exposure_seen = any(s.get("temperature") == "Hot" for s in samples)
    passed = baseline_ok and temp_ok and cooked_ok
    status = ("inconclusive" if not baseline_ok or not valid or (inside and not exposure_seen)
              else "observed_supported" if passed else "observed_counterexample")
    return {"status": status, "passed": passed, "temperature_matches": bool(temp_ok),
            "cooked_matches": bool(cooked_ok), "expected_final_temperature": expected_temp,
            "expected_final_isCooked": expected_cooked, "before": before, "after": final,
            "cooked_value_changed": before.get("isCooked") != final.get("isCooked"),
            "finite_window_only": True}


def r2(cooked, inside):
    def run(ctx):
        ctx.select("Microwave", "Microwave", capability=("toggleable", "openable", "receptacle"))
        ctx.select("Potato", "Potato", capability=("pickupable", "cookable"))
        ctx.bind("source", ctx.roles["Microwave"])
        external_surface(ctx, "Microwave")
        ctx.toggle("Microwave", False)
        ctx.ops.set_open(ctx.roles["Microwave"], True)
        optional_setup_view(ctx, "Microwave")
        ctx.require(ctx.field("Potato", "isCooked") is False,
                    "Native reset did not provide an uncooked potato; no uncook or CookObject shortcut")
        if cooked:
            ctx.move_setup("Potato", "Microwave")
            ctx.ops.set_open(ctx.roles["Microwave"], False)
            ctx.require(relation(ctx, "Potato", "Microwave"), "Pre-cooking potato was not inside microwave")
            ctx.step("ToggleObjectOn", objectId=ctx.roles["Microwave"], forceAction=True)
            hot = poll_state(ctx, "r2_natural_pre_cook", lambda s: s["temperature"] == "Hot" and s["isCooked"] is True,
                             max_passes=400, timeout_seconds=20)
            ctx.require(hot, "Natural pre-cooking did not establish Hot+cooked in bounded window")
            ctx.toggle("Microwave", False)
            ctx.ops.set_open(ctx.roles["Microwave"], True)
            transfer(ctx, "Potato", "external")
            cooled = poll_state(ctx, "r2_natural_cooling", lambda s: s["temperature"] == "RoomTemp")
            ctx.require(cooled, "Natural cooling not observed in bounded window; not an uncooling counterexample")
            cooling_trace = next(c["detail"]["trace"] for c in reversed(ctx.checks)
                                 if c["name"] == "r2_natural_cooling")
            retained = ctx.field("Potato", "isCooked") is True and all(s["isCooked"] is True for s in cooling_trace)
            ctx.check("r2_cooked_retained_through_cooling", retained,
                      {"after": state(ctx, "Potato"), "sampled_cooling_trace": cooling_trace})
            if not retained:
                return {"status": "observed_counterexample", "suite": "R2",
                        "stopped_at": "natural_cooling_history", "evaluated_activation_executed": False,
                        "refutes_only": "cooked retention during this observed natural cooling",
                        "after_cooling": state(ctx, "Potato")}
        ctx.move_setup("Potato", "Microwave" if inside else "external")
        ctx.ops.set_open(ctx.roles["Microwave"], False)
        for _ in range(4):
            ctx.step("Pass")
        pre = state(ctx, "Potato")
        location_ok = relation(ctx, "Potato", "Microwave") if inside else (
            unrelated(ctx, "Potato", "Microwave") and relation(ctx, "Potato", "external"))
        ctx.check("r2_event_baseline", location_ok and pre["temperature"] == "RoomTemp" and pre["isCooked"] is cooked,
                  {"before": pre, "inside": inside, "initially_cooked": cooked, "location_ok": location_ok})
        ctx.require(location_ok and pre["temperature"] == "RoomTemp" and pre["isCooked"] is cooked,
                    "Final event-time location/cooked/RoomTemp preconditions failed")
        ctx.require(not ctx.session.inventory(), "Potato setup left an object held before activation")
        ctx.require(ctx.field("Microwave", "isOpen") is False and ctx.field("Microwave", "isToggled") is False,
                    "Microwave must be closed and off before evaluated activation")
        ctx.capture("r2_before_evaluated_activation")
        event = ctx.step("ToggleObjectOn", objectId=ctx.roles["Microwave"], forceAction=True)
        ctx.require(ctx.field("Microwave", "isToggled") is True, "Activation receipt without actual on-state")
        samples = []
        for row in ctx.observe(steps=(0, 1, 4, 12, 36, 72, 120)):
            obj = next((o for o in row["metadata"]["objects"] if o.get("objectId") == ctx.roles["Potato"]), {})
            samples.append({"pass": row["observation_passes"], "temperature": native_temperature(obj),
                            "isCooked": obj.get("isCooked"), "parentReceptacles": obj.get("parentReceptacles")})
        outcome = evaluate_thermal(pre, samples, cooked, inside)
        location_stable = all((ctx.roles["Microwave"] in (s.get("parentReceptacles") or [])) is inside
                              for s in samples)
        outcome["location_stable_during_samples"] = location_stable
        if not location_stable:
            outcome.update(status="inconclusive", passed=False)
        ctx.check("r2_attribute_outcome", outcome["passed"], outcome)
        post_actions = ctx.session.records[event.record["index"] + 1:]
        no_rewriting = all(a["action"] == "Pass" for a in post_actions)
        ctx.check("r2_no_post_event_state_rewriting", no_rewriting,
                  {"event_index": event.record["index"], "post_event_action_names": sorted({a["action"] for a in post_actions}),
                   "post_event_action_count": len(post_actions)})
        if not no_rewriting:
            outcome.update(status="inconclusive", passed=False)
        return {"status": outcome["status"], "suite": "R2", "initially_cooked": cooked,
                "inside": inside, "event": event.record, "samples": samples, "outcome": outcome,
                "history": "actual heating then natural cooling" if cooked else "native uncooked reset",
                "no_CookObject_or_temperature_setter": True}
    return run


def cases():
    return [ProbeCase(f"R1_{configuration}_{'pickup' if pickup else 'control'}", "F10", "nested_carry",
                      r1(configuration, pickup)) for configuration in RELATIONS for pickup in (True, False)] + [
        ProbeCase(f"R2_{'cooked_cooled' if cooked else 'uncooked'}_{'inside' if inside else 'outside'}",
                  "F4", "thermal_liquid", r2(cooked, inside))
        for cooked in (False, True) for inside in (True, False)]


def comparison_summary(rows):
    by_id = {r["case_id"]: r for r in rows}
    groups = {}
    for group in ("R1", "R2"):
        wanted = [c.case_id for c in cases() if c.case_id.startswith(group + "_")]
        complete = all(k in by_id for k in wanted)
        statuses = {k: by_id[k]["status"] if k in by_id else "not_run" for k in wanted}
        groups[group] = {"conditions_expected": len(wanted), "all_attempted": complete,
                         "statuses": statuses,
                         "whole_pattern_supported": complete and all(s == "observed_supported" for s in statuses.values())}
    pairs = []
    for configuration in RELATIONS:
        def baseline(arm):
            row = by_id.get(f"R1_{configuration}_{arm}", {})
            check = next((c for c in row.get("checks", []) if c["name"] == "r1_motion_pattern"), {})
            return check.get("detail", {}).get("baseline")
        a, b = baseline("pickup"), baseline("control")
        matched = None
        gaps = {}
        if a and b:
            matched = all(a[r]["objectId"] == b[r]["objectId"] and
                          sorted(a[r].get("parentReceptacles") or []) == sorted(b[r].get("parentReceptacles") or []) for r in ROLES)
            gaps = {r: norm(vector(a[r].get("position"), b[r].get("position"))) for r in ROLES}
            matched = matched and all(v is not None and v < STATIONARY_M for v in gaps.values())
        pairs.append({"configuration": configuration, "baseline_ids_relations_and_positions_matched": matched,
                      "baseline_position_gap_m": gaps})
    groups["R1"]["paired_baselines"] = pairs
    groups["R1"]["whole_pattern_supported"] &= all(p["baseline_ids_relations_and_positions_matched"] is True for p in pairs)
    return {"groups": groups, "no_universal_rule_claim": True,
            "pairing_limits": "Fresh reset per arm, same instance/configuration, event vs one Pass; equal action count does not certify equal physical time."}
