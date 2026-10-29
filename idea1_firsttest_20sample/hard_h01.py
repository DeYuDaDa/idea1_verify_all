"""H01 variants: natural water contact, real spilling, private checkpoint evidence.

No simulator on import. All changes use ControllerSession native steps. Geometry
is screened privately; missing contact is a construction failure, never a fill
setter fallback. Checkpoints are private and never enter model_input.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

from hard_export import write_json
from hard_navigation import floor_distance, shortest_grid_route, xyz
from hard_scenarios import (HardConstructionError, _role, _surface_candidates,
                            _set_waypoint, _native_setup_place, _calibrate_forward,
                            _move, _target_event, _questions, _q)


MAX_HAND_STEP = 0.04
MAX_HAND_DISTANCE = 0.85
CONTACT_PASSES = 4
POSITION_EPS = 0.03
FIELDS = ("objectId", "objectType", "position", "rotation", "axisAlignedBoundingBox",
          "isFilledWithLiquid", "fillLiquid", "isPickedUp", "isBroken",
          "parentReceptacles", "receptacleObjectIds", "isToggled", "isDirty")


def liquid(obj):
    if obj.get("isFilledWithLiquid") is False and obj.get("fillLiquid") in (None, ""):
        return "Empty"
    if obj.get("isFilledWithLiquid") is True:
        return {"water": "Water", "coffee": "Coffee"}.get(str(obj.get("fillLiquid", "")).lower())
    return None


def center(obj):
    return dict((obj.get("axisAlignedBoundingBox") or {}).get("center") or obj["position"])


def distance(a, b):
    return math.dist([float(a[k]) for k in ("x", "y", "z")],
                     [float(b[k]) for k in ("x", "y", "z")])


def tilt(obj):
    rotation = obj.get("rotation") or {}
    if not all(k in rotation for k in ("x", "y", "z")):
        raise HardConstructionError("Cup rotation metadata missing; cannot verify a spill")
    # Unity Euler Z-X-Y: world-up dot local-up = cos(pitch)*cos(roll).
    return math.degrees(math.acos(max(-1., min(1.,
        math.cos(math.radians(float(rotation.get("x", 0)))) *
        math.cos(math.radians(float(rotation.get("z", 0))))))))


def camera_delta(delta, agent):
    """World displacement -> MoveHeldObject camera-right/up/ahead coordinates."""
    yaw = math.radians(float(agent.get("rotation", {}).get("y", 0)))
    horizon = math.radians(float(agent.get("cameraHorizon", 0)))
    x, y, z = (float(delta[k]) for k in ("x", "y", "z"))
    return {"right": x * math.cos(yaw) - z * math.sin(yaw),
            "up": x * math.sin(yaw) * math.sin(horizon) + y * math.cos(horizon)
                  + z * math.cos(yaw) * math.sin(horizon),
            "ahead": x * math.sin(yaw) * math.cos(horizon) - y * math.sin(horizon)
                     + z * math.cos(yaw) * math.cos(horizon)}


def parked(ctx, role):
    child = ctx.obj(role)
    parent_id = ctx.waypoints[role + "_park"]["objectId"]
    parent = ctx.obj(parent_id)
    # A CounterTop ancestor alone must not certify restoration from the machine.
    return (parent_id in (child.get("parentReceptacles") or [])
            and ctx.roles[role] in (parent.get("receptacleObjectIds") or [])
            and ctx.roles["M"] not in (child.get("parentReceptacles") or [])
            and ctx.roles[role] not in (ctx.obj("M").get("receptacleObjectIds") or [])
            and child.get("isPickedUp") is False)


def variant_spec(variant):
    if variant not in (1, 2, 3, 4):
        raise ValueError("H01 variant must be 1..4")
    first, second = ("A", "B") if variant in (1, 4) else ("B", "A")
    target = "A" if variant in (1, 2) else "B"
    before = {first: "Empty", second: "Water"}
    after = {**before, target: "Coffee" if before[target] == "Empty" else "Water"}
    return {"first": first, "second": second, "target": target,
            "other": "B" if target == "A" else "A", "before": before, "after": after}


def checkpoint_plan(variant=1):
    spec = variant_spec(variant)
    first, second, target = spec["first"], spec["second"], spec["target"]
    rows = [("C01", "物品、水源与停放位"), ("C02", "机器槽位与原生恢复"),
            ("C03-A", "A 私有自然接水与倾倒验证"), ("C03-B", "B 私有自然接水与倾倒验证"),
            ("C04", "正式初态：两杯空、设备关、手空")]
    for stage, role in (("T01", first), ("T02", second), ("T05", second)):
        for suffix, title in (("W01", "拿起空杯"), ("W02", "接近但尚未接水"),
                              ("W03", "流水开启、杯仍空"), ("W04", "流水下自然接水"),
                              ("W05", "移离关水、保留水"), ("W06", "展示液面并归位")):
            rows.append((stage + "-" + suffix, role + " / " + title))
    for stage, role in (("T03", first), ("T04", second)):
        for suffix, title in (("D01", "拿起后仍有水"), ("D02", "倾倒触发清空"),
                              ("D03", "扶正后仍空"), ("D04", "展示空杯并归位")):
            rows.append((stage + "-" + suffix, role + " / " + title))
    rows += [("T06", "开启咖啡机、两杯保持"), ("T07", f"正确的 {target} 在手、目标前核对"),
             ("T08", "真实放入机器的回执与关系"),
             ("T09", f"实际后态：A={spec['after']['A']}、B={spec['after']['B']}，位置与设备状态")]
    order = ["C01", "C02", "C03-A", "C03-B", "C04", "T01", "T02", "T03", "T04",
             "T05", "T06", "T07", "T08", "T09"]
    rows.sort(key=lambda row: order.index(row[0] if row[0].startswith("C") else row[0][:3]))
    return [{"id": key, "title": title, "status": "not_executed", "public": key.startswith("T") or key == "C04",
             "visual_review": "pending_human_review", "facts": [], "evidence": []} for key, title in rows]


class H01Natural:
    def __init__(self, ctx, variant=1):
        self.ctx = ctx
        self.variant = variant
        self.spec = variant_spec(variant)
        self.case_id = f"H01-{variant}"
        ctx.h01_natural = True
        ctx.identity_on_first_pickup = {"A", "B"}
        ctx.h01_checkpoints = checkpoint_plan(variant)
        self.active = None
        self.other_baseline = None
        self.expected_machine = False
        self.expected_liquids = {"A": "Empty", "B": "Empty"}
        self.calibrations = {}
        self.pending_spill_rolls = {}
        self.persist()

    def persist(self):
        write_json(self.ctx.out / "h01_checkpoints.json", {
            "schema": "h01-checkpoints/v1", "case_id": self.case_id, "variant": self.variant,
            "checkpoints": self.ctx.h01_checkpoints, "calibrations": self.calibrations,
            "pending_spill_relative_rolls": self.pending_spill_rolls,
            "contact_passes": CONTACT_PASSES, "hand_step_m": MAX_HAND_STEP,
            "note": "私有检查与图片定位；不属于模型输入，程序通过不等于人眼可答。"})

    def begin(self, key):
        self.active = next(row for row in self.ctx.h01_checkpoints if row["id"] == key)
        self.active["status"] = "running"
        self.active["action_index_start"] = len(self.ctx.session.records)
        self.ctx.phase(key + " / " + self.active["title"], public=self.active["public"],
                       kind="target" if key == "T08" else "history" if self.active["public"] else "setup")
        self.persist()

    def capture(self, label):
        result = self.ctx.trace.capture_current(label)
        evidence = {"label": label, "global_step": result["global_step"],
                    "action_index": result.get("action_index"), "frame_status": result.get("frame_status"),
                    "frames": copy.deepcopy(result.get("frames", []))}
        if self.active:
            self.active["evidence"].append(evidence)
        return result

    def finish(self, facts):
        row = self.active
        row["facts"] = [{"fact": name, "expected": expected, "actual": actual,
                          "passed": actual == expected} for name, expected, actual in facts]
        row["state"] = {alias: {key: obj.get(key) for key in FIELDS}
                        for alias in self.ctx.roles for obj in [self.ctx.obj(alias)]}
        row["inventory"] = self.ctx.session.inventory()
        row["native_receipts"] = copy.deepcopy(self.ctx.session.records[row["action_index_start"]:])
        self.capture(row["id"] + " / 检查点状态")
        media_ok = bool(row["evidence"]) and all(e.get("frame_status") == "captured"
                   and any(f.get("view_id") == "agent" and f.get("path")
                           and (Path(self.ctx.trace.directory) / f["path"]).is_file()
                           and (Path(self.ctx.trace.directory) / f["path"]).stat().st_size > 0
                           for f in e["frames"])
                   for e in row["evidence"])
        row["facts"].append({"fact": "检查点图片存在且是本次实际返回事件", "expected": True,
                              "actual": media_ok, "passed": media_ok})
        passed = all(f["passed"] for f in row["facts"])
        row["status"] = "passed" if passed else "failed"
        self.ctx.check(self.case_id + "/" + row["id"], passed, {"facts": row["facts"]})
        self.persist()
        self.ctx.require(passed, self.case_id + " checkpoint failed: " + row["id"] + " / " + str(row["facts"]))

    def fail(self, exc):
        if self.active and self.active["status"] == "running":
            self.active["status"] = "failed"
            self.active["error"] = f"{type(exc).__name__}: {exc}"
            self.active["native_receipts"] = copy.deepcopy(self.ctx.session.records[self.active["action_index_start"]:])
            self.active["state"] = {alias: {key: self.ctx.obj(alias).get(key) for key in FIELDS}
                                    for alias in self.ctx.roles}
            if self.active["id"].startswith("C03-"):
                calibration = self.calibrations.get(self.active["id"][-1])
                if calibration is not None:
                    calibration.update(status="failed", error=str(exc))
            try:
                self.capture(self.active["id"] + " / 停止位置")
            except Exception as capture_exc:
                self.active["capture_error"] = str(capture_exc)
            self.persist()

    def guard(self):
        if self.other_baseline:
            role, baseline = self.other_baseline
            obj = self.ctx.obj(role)
            self.ctx.require(liquid(obj) == liquid(baseline) and parked(self.ctx, role)
                and distance(obj["position"], baseline["position"]) <= POSITION_EPS,
                "Inactive cup changed during operation: " + role)
        if "M" in self.ctx.roles:
            self.ctx.require(self.ctx.obj("M").get("isToggled") is self.expected_machine,
                             "Coffee machine changed before its planned event")
        for role in ("A", "B"):
            if role in self.ctx.roles:
                self.ctx.require(self.ctx.obj(role).get("isBroken") is not True, "Broken cup: " + role)

    def step(self, action, **kwargs):
        self.guard()
        result = self.ctx.step(action, **kwargs)
        self.guard()
        # Every hand pose, spill and water-contact return is retained even in debug.
        if action in {"MoveHeldObject", "RotateHeldObject", "Pass"}:
            self.capture((self.active or {}).get("id", "C03") + " / " + action)
        return result

    def navigate(self, role):
        self.guard()
        self.ctx.navigate_to(role, "H01-1_native_history")
        self.guard()

    def approach_water(self, role, goals, *, preferred=None):
        """H01-only approach: seeing a faucet is not enough to reach its water.

        Keep the 0.85 m hand-motion budget. Walk on actual reachable positions
        first, using the existing collision-checked native route primitives.
        Formal trials replay the privately verified standing position.
        """
        self.navigate("Faucet")
        start = xyz(self.ctx.session.snapshot()["agent"])
        diagnostic = {"method": "H01-1_water_hand_reach", "role": role,
            "start_agent_position": start, "preferred_verified_position": preferred,
            "hand_budget_m": MAX_HAND_DISTANCE,
            "initial_hand_distances_m": [distance(center(self.ctx.obj(role)), goal) for goal in goals],
            "attempts": []}
        self.ctx.navigation_attempts.append(diagnostic)
        if (preferred is None or floor_distance(start, preferred) <= .025) and min(diagnostic["initial_hand_distances_m"]) <= MAX_HAND_DISTANCE:
            diagnostic.update(status="already_within_hand_budget", final_agent_position=start)
            return start
        result = self.step("GetReachablePositions")
        points = [xyz(point) for point in (result.metadata.get("actionReturn") or [])]
        self.ctx.require(bool(points), "Water approach has no native reachable positions")
        if preferred is not None:
            candidates = [p for p in points if floor_distance(p, preferred) <= .025]
        else:
            candidates = [p for p in points if min(floor_distance(p, goal) for goal in goals) <= .95]
            candidates.sort(key=lambda p: (min(floor_distance(p, g) for g in goals), floor_distance(start, p)))
        navigator = self.ctx.navigator
        navigator.action_count = 0
        for point in candidates[:4]:
            route = shortest_grid_route(points, xyz(self.ctx.session.snapshot()["agent"]), point)
            attempt = {"candidate_agent_position": point, "route_points": len(route) if route else 0}
            diagnostic["attempts"].append(attempt)
            if not route:
                attempt["error"] = "No connected native route"
                continue
            # A native collision failure stays a failure; do not teleport or
            # silently carry on from an unverified pose.
            for waypoint in route:
                navigator._walk(waypoint)
                self.guard()
                self.ctx.require(self.holding(role) and liquid(self.ctx.obj(role)) == "Empty",
                                 "Water approach lost its original empty held cup")
            navigator._aim(self.ctx.obj("Faucet"))
            self.guard()
            ranges = [distance(center(self.ctx.obj(role)), goal) for goal in goals]
            attempt["actual_hand_distances_m"] = ranges
            if min(ranges) <= MAX_HAND_DISTANCE:
                actual = xyz(self.ctx.session.snapshot()["agent"])
                diagnostic.update(status="walked_within_hand_budget", final_agent_position=actual)
                self.capture((self.active or {})["id"] + " / 接水近距离站位确认")
                return actual
        diagnostic["status"] = "no_reachable_stance_within_hand_budget"
        raise HardConstructionError("Water faucet visible but no native standing pose brings the held cup within the hand budget")

    def source(self, on):
        if self.ctx.obj("Faucet").get("isToggled") is not on:
            self.step("ToggleObjectOn" if on else "ToggleObjectOff",
                      objectId=self.ctx.roles["Faucet"], forceAction=True)
        self.ctx.require(self.ctx.obj("Faucet").get("isToggled") is on, "Faucet toggle not confirmed")

    def holding(self, role):
        return [o.get("objectId") for o in self.ctx.session.inventory()] == [self.ctx.roles[role]]

    def empty_hand(self):
        return not self.ctx.session.inventory()

    def baseline(self, role):
        other = "B" if role == "A" else "A"
        self.other_baseline = (other, self.ctx.obj(other))

    def pickup(self, role, *, anchor=False):
        self.baseline(role)
        self.navigate(role)
        self.ctx.require(liquid(self.ctx.obj(role)) == self.expected_liquids[role],
                         "Cup liquid changed before pickup: " + role)
        self.capture((self.active or {})["id"] + " / 取杯前")
        self.ctx.ops.pickup_event(self.ctx.roles[role], look_first=False)
        self.guard()
        self.ctx.require(self.holding(role), "Wrong held cup: " + role)
        image = self.capture((self.active or {})["id"] + " / " + ("首次拿起 " if anchor else "拿起 ") + role)
        if anchor:
            from interactions import Interactions
            from runtime import StepResult
            bbox = Interactions._rendered_target_bbox(StepResult(self.ctx.session.controller.last_event,
                    self.ctx.session.snapshot(), {}), self.ctx.roles[role])
            self.ctx.require(bbox is not None, "First pickup cup is not rendered: " + role)
            self.ctx.initial_identity_regions.append({"alias": role, "view_id": "agent",
                "initial_capture_group_index": image["global_step"], "anchor_kind": "first_public_pickup",
                "pixel_bbox": [bbox["x"], bbox["y"], bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]]})

    def put_back(self, role):
        self.navigate(role + "_park")
        self.ctx.ops.put_event(self.ctx.roles[role], self.ctx.waypoints[role + "_park"]["objectId"])
        for _ in range(4):
            self.step("Pass")
        self.ctx.require(parked(self.ctx, role) and self.empty_hand(), "Cup did not return outside machine")
        self.navigate(role)
        self.capture((self.active or {})["id"] + " / 归位杯口确认 " + role)

    def hand_path(self, role, goal, *, expect_empty=False):
        """Collision-checked, bounded, native translation, with no teleports."""
        start = center(self.ctx.obj(role))
        self.ctx.require(distance(start, goal) <= MAX_HAND_DISTANCE, "Water target beyond bounded hand reach")
        # Cross the sink rim above it, then lower vertically under the stream.
        # A direct diagonal often hits the counter before reaching the basin.
        basin_box = self.ctx.obj("SinkBasin").get("axisAlignedBoundingBox") or {}
        cup_box = self.ctx.obj(role).get("axisAlignedBoundingBox") or {}
        safe_y = max(float(start["y"]), float(goal["y"]),
                     float((basin_box.get("center") or start)["y"])
                     + float(basin_box.get("size", {}).get("y", .15)) / 2
                     + float(cup_box.get("size", {}).get("y", .10)) / 2 + .025)
        for waypoint in ({**start, "y": safe_y}, {**goal, "y": safe_y}, goal):
            self._hand_segment(role, waypoint, expect_empty=expect_empty)

    def _hand_segment(self, role, goal, *, expect_empty=False):
        for _ in range(28):
            actual = center(self.ctx.obj(role))
            remaining = distance(actual, goal)
            if remaining <= 0.012:
                return
            delta = {k: (float(goal[k]) - float(actual[k])) * min(1., MAX_HAND_STEP / remaining)
                     for k in ("x", "y", "z")}
            args = camera_delta(delta, self.ctx.session.snapshot()["agent"])
            self.step("MoveHeldObject", **args)
            self.ctx.require(self.holding(role) and tilt(self.ctx.obj(role)) < 30,
                             "Water approach lost held/upright cup")
            if expect_empty:
                self.ctx.require(liquid(self.ctx.obj(role)) == "Empty", "Dry-control path unexpectedly filled cup")
            self.ctx.require(distance(actual, center(self.ctx.obj(role))) > 0.001,
                             "Native hand move made no measurable progress")
        raise HardConstructionError("Bounded hand path did not reach water candidate")

    def spill_held(self, role):
        self.ctx.require(self.holding(role) and self.ctx.obj("Faucet").get("isToggled") is False,
                         "Spill requires correct held cup and faucet off")
        self.ctx.require(tilt(self.ctx.obj(role)) < 15 and liquid(self.ctx.obj(role)) == "Water",
                         "Spill must begin with an upright cup of water")
        self.ctx.require(not self.pending_spill_rolls.get(role), "Previous spill rotation was not reversed")
        applied = self.pending_spill_rolls.setdefault(role, [])
        self.capture((self.active or {})["id"] + " / 倾倒前仍有水")
        emptied = False
        # The pitch/yaw/roll overload is RELATIVE, not an absolute pose setter.
        # Record only successful deltas so upright can invert exactly these calls.
        for _ in range(6):
            self.step("RotateHeldObject", pitch=0, yaw=0, roll=20)
            applied.append(20)
            self.persist()
            if liquid(self.ctx.obj(role)) == "Empty":
                self.ctx.require(tilt(self.ctx.obj(role)) > 90, "Cup emptied before measured spill tilt")
                emptied = True
                break
            if tilt(self.ctx.obj(role)) > 90:
                for _ in range(CONTACT_PASSES):
                    self.step("Pass")
                    if liquid(self.ctx.obj(role)) == "Empty":
                        self.ctx.require(tilt(self.ctx.obj(role)) > 90, "Empty cup lacks actual spill tilt")
                        emptied = True
                        break
                if emptied:
                    break
        self.ctx.require(emptied, "Native tilting did not empty cup; no direct empty fallback")

    def upright(self, role):
        applied = self.pending_spill_rolls.get(role, [])
        while applied:
            self.step("RotateHeldObject", pitch=0, yaw=0, roll=-applied[-1])
            applied.pop()
            self.ctx.require(self.holding(role) and liquid(self.ctx.obj(role)) == "Empty",
                             "Spill restoration lost original empty held cup")
            self.persist()
        self.ctx.require(tilt(self.ctx.obj(role)) < 15 and self.holding(role), "Cup not restored upright")

    def facts(self, role=None, value=None, *, held=None):
        facts = [("M保持预定开关", self.expected_machine, self.ctx.obj("M").get("isToggled"))]
        if role:
            facts += [(role + "液体", value, liquid(self.ctx.obj(role)))]
            if held is not None:
                facts.append((role + "在手", held, self.holding(role)))
                if not held:
                    facts += [(role + "归位", True, parked(self.ctx, role)), ("手空", True, self.empty_hand())]
        if self.other_baseline:
            other, old = self.other_baseline
            facts += [(other + "液体保留", liquid(old), liquid(self.ctx.obj(other))),
                      (other + "保持停放位", True, parked(self.ctx, other)),
                      (other + "位置保持3cm内", True,
                       distance(old["position"], self.ctx.obj(other)["position"]) <= POSITION_EPS)]
        return facts

    def calibrate_water(self, role):
        self.begin("C03-" + role)
        self.pickup(role)
        self.source(False)
        self.ctx.require(liquid(self.ctx.obj(role)) == "Empty", "Calibration cup must start empty")
        faucet, basin = center(self.ctx.obj("Faucet")), center(self.ctx.obj("SinkBasin"))
        basin_height = float((self.ctx.obj("SinkBasin").get("axisAlignedBoundingBox") or {}).get("size", {}).get("y", .15))
        height = min(float(faucet["y"]) - 0.10,
                     float(basin["y"]) + basin_height)
        height = max(float(basin["y"]), height)
        candidates = [{"x": float(faucet["x"]) * (1-t) + float(basin["x"]) * t,
                       "y": height, "z": float(faucet["z"]) * (1-t) + float(basin["z"]) * t}
                      # Basin-centred candidate succeeded in GJGb0m; the older
                      # halfway candidate collided with the faucet. Keep bounded
                      # native alternatives, but do not repeat that known bad path first.
                      for t in (1., 0.5, 0., .25, .75)]
        trials = []
        self.calibrations[role] = {"status": "searching", "trials": trials,
                                   "protocol": "native_wet_contact_only",
                                   "dry_control_repeated": False}
        stance = self.approach_water(role, candidates)
        self.calibrations[role]["approach_agent_position"] = stance
        start = center(self.ctx.obj(role))
        for index, goal in enumerate(candidates):
            trial = {"candidate": index, "goal_center": goal, "start_center": start,
                     "hand_distance_m": distance(start, goal)}
            trials.append(trial)
            self.persist()
            try:
                trial["stage"] = "water_contact_geometry"
                self.ctx.phase("C03-" + role + f" / 候选{index + 1} / 开水自然接水校准",
                               public=False, kind="calibration")
                self.source(True)
                self.ctx.require(liquid(self.ctx.obj(role)) == "Empty", "Water source reaches approach start")
                self.hand_path(role, goal)
                for _ in range(CONTACT_PASSES):
                    if liquid(self.ctx.obj(role)) == "Water":
                        break
                    self.step("Pass")
                filled = liquid(self.ctx.obj(role)) == "Water"
                self.source(False)
                self.hand_path(role, start)
                trial["became_water"] = filled
                if filled:
                    self.ctx.require(liquid(self.ctx.obj(role)) == "Water", "Water lost on retreat")
                    trial["water_retained_after_retreat"] = True
                    trial["stage"] = "spill_and_restore"
                    self.calibrations[role].update(status="contact_verified_pending_spill_restore", goal_center=goal,
                        approach_start=start, contact_passes=CONTACT_PASSES)
                    self.spill_held(role)
                    self.upright(role)
                    self.put_back(role)
                    self.finish(self.facts(role, "Empty", held=False) + [("水龙头关闭", False,
                        self.ctx.obj("Faucet").get("isToggled")),
                        ("流水接触后实际装水", True, trial.get("became_water")),
                        ("离水关水后保留水", True, trial.get("water_retained_after_retreat"))])
                    self.calibrations[role]["status"] = "verified"
                    self.persist()
                    return
            except Exception as exc:
                trial["error"] = f"{type(exc).__name__}: {exc}"
                self.persist()
                # No reset, scene teleport, fill setter, or swallowed spill/state error.
                # Recover only a still-empty cup from a failed geometry trial.
                if (trial.get("stage") != "water_contact_geometry"
                        or not self.holding(role) or liquid(self.ctx.obj(role)) != "Empty"):
                    raise
                self.source(False)
                self.hand_path(role, start, expect_empty=True)
            self.persist()
        raise HardConstructionError("No native natural-water path verified for " + role)

    def water(self, role, stage, *, first=False):
        self.begin(stage + "-W01")
        self.source(False)
        self.pickup(role, anchor=first)
        self.finish(self.facts(role, "Empty", held=True))
        self.begin(stage + "-W02")
        self.approach_water(role, [self.calibrations[role]["goal_center"]],
                            preferred=self.calibrations[role].get("approach_agent_position"))
        start = center(self.ctx.obj(role))
        self.finish(self.facts(role, "Empty", held=True) + [("水龙头关闭", False, self.ctx.obj("Faucet").get("isToggled"))])
        self.begin(stage + "-W03")
        self.source(True)
        self.finish(self.facts(role, "Empty", held=True) + [("水龙头开启", True, self.ctx.obj("Faucet").get("isToggled"))])
        self.begin(stage + "-W04")
        self.hand_path(role, self.calibrations[role]["goal_center"])
        for _ in range(CONTACT_PASSES):
            if liquid(self.ctx.obj(role)) == "Water":
                break
            self.step("Pass")
        self.finish(self.facts(role, "Water", held=True) + [("水龙头开启", True, self.ctx.obj("Faucet").get("isToggled"))])
        self.begin(stage + "-W05")
        # Retract while water still running; no filling shortcut is involved.
        self.hand_path(role, start)
        self.source(False)
        self.capture(stage + " / 接水后杯口与液面")
        self.finish(self.facts(role, "Water", held=True) + [("水龙头关闭", False, self.ctx.obj("Faucet").get("isToggled"))])
        self.begin(stage + "-W06")
        self.put_back(role)
        self.expected_liquids[role] = "Water"
        self.finish(self.facts(role, "Water", held=False))

    def spill(self, role, stage):
        self.begin(stage + "-D01")
        self.ctx.require(self.ctx.obj("Faucet").get("isToggled") is False, "Cannot spill under running water")
        self.pickup(role)
        self.finish(self.facts(role, "Water", held=True))
        self.begin(stage + "-D02")
        # The cup is held at its external parking area, away from the faucet.
        self.spill_held(role)
        self.finish(self.facts(role, "Empty", held=True))
        self.begin(stage + "-D03")
        self.upright(role)
        self.finish(self.facts(role, "Empty", held=True))
        self.begin(stage + "-D04")
        self.put_back(role)
        self.expected_liquids[role] = "Empty"
        self.finish(self.facts(role, "Empty", held=False))

    def run(self):
        ctx = self.ctx
        self.begin("C01")
        _role(ctx, "A", "Mug", ("canFillWithLiquid", "pickupable"))
        _role(ctx, "B", "Mug", ("canFillWithLiquid", "pickupable"), exclude=("A",))
        _role(ctx, "M", "CoffeeMachine", ("toggleable", "receptacle"))
        _role(ctx, "Faucet", "Faucet", "toggleable")
        basins = [o for o in ctx.session.snapshot()["objects"] if o.get("objectType") == "SinkBasin" and o.get("receptacle")]
        ctx.require(bool(basins), "No native sink basin for natural water")
        basin = min(basins, key=lambda o: distance(center(o), center(ctx.obj("Faucet"))))
        ctx.bind("SinkBasin", basin["objectId"])
        # Ensure sources are disabled before any calibration or cup handling.
        for obj in ctx.session.snapshot()["objects"]:
            if obj.get("objectType") == "Faucet" and obj.get("isToggled") is True:
                ctx.step("ToggleObjectOff", objectId=obj["objectId"], forceAction=True)
        if ctx.obj("M").get("isToggled") is not False:
            ctx.step("ToggleObjectOff", objectId=ctx.roles["M"], forceAction=True)
        slots = _surface_candidates(ctx)
        ctx.require(len(slots) >= 2, "H01-1 needs two distinct external surfaces")
        # Prefer surfaces farther from the sink to avoid accidental re-filling.
        slots.sort(key=lambda o: -distance(center(o), center(basin)))
        _set_waypoint(ctx, "A_park", slots[0])
        _set_waypoint(ctx, "B_park", slots[1])
        self.finish([("两个不同杯子", True, ctx.roles["A"] != ctx.roles["B"]),
                     ("M关闭", False, ctx.obj("M").get("isToggled")),
                     ("水龙头关闭", False, ctx.obj("Faucet").get("isToggled"))])
        self.begin("C02")
        _native_setup_place(ctx, "A", "A_park")
        _native_setup_place(ctx, "B", "B_park")
        _calibrate_forward(ctx, "A", "A_park", "M")
        _calibrate_forward(ctx, "B", "B_park", "M")
        # Private initialization only; never used in public history.
        for role in ("A", "B"):
            ctx.ops.set_liquid(ctx.roles[role], None)
        self.finish([("A归位", True, parked(ctx, "A")), ("B归位", True, parked(ctx, "B")),
                     ("两杯均空", ["Empty", "Empty"], [liquid(ctx.obj(r)) for r in ("A", "B")]),
                     ("手空", True, self.empty_hand())])
        self.calibrate_water("A")
        self.calibrate_water("B")
        self.other_baseline = None
        first, second, target, other = (self.spec[k] for k in ("first", "second", "target", "other"))
        before_values, after_values = self.spec["before"], self.spec["after"]
        ctx.public_declarations.extend([
            f"正式历史中第一次拿起来接水的杯子记为{first}；随后第一次拿起来接水的另一只杯子记为{second}。后续反复拿取仍沿用这两个身份，私有校准不计入。",
            "初态两杯均空，位于各自外部停放位；咖啡机和水龙头关闭。空杯接触流水可装水，持杯大幅倾斜可倒空；流水关闭后不会继续接水。"])
        ctx.start_history()
        public_action_start = len(ctx.session.records)
        self.begin("C04")
        for role in ("A", "B"):
            self.navigate(role)
            self.capture("C04 / 两只空杯的初态 / " + role)
        self.finish([("A空", "Empty", liquid(ctx.obj("A"))), ("B空", "Empty", liquid(ctx.obj("B"))),
                     ("A归位", True, parked(ctx, "A")), ("B归位", True, parked(ctx, "B")),
                     ("M关闭", False, ctx.obj("M").get("isToggled")),
                     ("水龙头关闭", False, ctx.obj("Faucet").get("isToggled")), ("手空", True, self.empty_hand())])
        self.water(first, "T01", first=True)
        self.water(second, "T02", first=True)
        self.spill(first, "T03")
        self.spill(second, "T04")
        self.water(second, "T05")
        self.other_baseline = None
        self.begin("T06")
        self.navigate("M")
        ctx.step("ToggleObjectOn", objectId=ctx.roles["M"], forceAction=True)
        self.expected_machine = True
        self.finish([("A液体", before_values["A"], liquid(ctx.obj("A"))),
                     ("B液体", before_values["B"], liquid(ctx.obj("B"))),
                     ("A归位", True, parked(ctx, "A")), ("B归位", True, parked(ctx, "B")),
                     ("M开启", True, ctx.obj("M").get("isToggled")),
                     ("机器无任务杯", True, not any(ctx.roles[r] in (ctx.obj("M").get("receptacleObjectIds") or []) for r in ("A", "B")))])
        self.begin("T07")
        self.pickup(target)
        self.navigate("M")
        self.finish(self.facts(target, before_values[target], held=True) + [(target + "尚未入机", False,
            ctx.roles["M"] in (ctx.obj(target).get("parentReceptacles") or []))])
        self.begin("T08")
        event = _target_event(ctx, "PutObject", target, "M")
        # The shared target helper includes the fixed Pass-0/Pass-4 window.
        # Link the actual PutObject return (not the later settled image) too.
        for recorded in ctx.trace.events:
            if (recorded.get("action") == "PutObject"
                    and recorded.get("action_index") == (event.get("record") or {}).get("index")):
                self.active["evidence"].append({"label": "T08 / PutObject 即时返回",
                    **{k: copy.deepcopy(recorded.get(k)) for k in ("global_step", "action_index", "frame_status", "frames")}})
                break
        before = {o["objectId"]: o for o in ctx.before_target["objects"]}
        self.guard()
        self.finish([("PutObject成功", True, event.get("success")),
                     ("实际事件前目标杯液体", before_values[target], liquid(before[ctx.roles[target]])),
                     ("事件源是正确目标杯", [ctx.roles[target]], [o.get("objectId") for o in ctx.before_target.get("inventoryObjects",
                         ctx.before_target.get("agent", {}).get("inventoryObjects", []))]),
                     ("目标杯在M中", True, ctx.roles["M"] in (ctx.obj(target).get("parentReceptacles") or [])),
                     ("机器包含目标杯", True, ctx.roles[target] in (ctx.obj("M").get("receptacleObjectIds") or [])),
                     ("手空", True, self.empty_hand())])
        self.begin("T09")
        self.active["observation_samples"] = copy.deepcopy(event["observation_samples"])
        self.active["observation_note"] = "窗口在T08真实PutObject后立即执行；此节点引用其原始记录，不重新延长观察。"
        for recorded in ctx.trace.events:
            if recorded.get("phase_kind") == "observation" and recorded.get("frame_status") == "captured":
                self.active["evidence"].append({"label": "T09 / " + recorded.get("phase_label", "观察窗口"),
                    **{k: copy.deepcopy(recorded.get(k)) for k in ("global_step", "action_index", "frame_status", "frames")}})
        other_old = self.other_baseline[1]
        preserved = all(liquid(sample["metadata"][other]) == before_values[other]
                        and distance(sample["metadata"][other]["position"], other_old["position"]) <= POSITION_EPS
                        and ctx.roles["M"] not in (sample["metadata"][other].get("parentReceptacles") or [])
                        for sample in event["observation_samples"])
        forbidden = {"FillObjectWithLiquid", "EmptyLiquidFromObject", "SetObjectPoses",
                     "PlaceObjectAtPoint", "Teleport", "TeleportFull", "InitialRandomSpawn"}
        shortcuts = [record for record in ctx.session.records[public_action_start:] if record.get("action") in forbidden]
        self.finish(self.facts(target, after_values[target]) + [("目标杯在M中", True,
            ctx.roles["M"] in (ctx.obj(target).get("parentReceptacles") or [])),
            ("另一杯液体", after_values[other], liquid(ctx.obj(other))), ("另一杯归位", True, parked(ctx, other)),
            ("水龙头关闭", False, ctx.obj("Faucet").get("isToggled")), ("手空", True, self.empty_hand()),
            ("Pass0到固定窗口末端另一杯保留液体与位置", True, preserved),
            ("公开历史没有直接填水清空或传送捷径", [], shortcuts)])
        _questions(ctx, [
            _q("A", "liquid", "enum:Empty|Water|Coffee", f"A（正式历史中{'最先' if first == 'A' else '随后第一次'}拿起来接水的杯子）现在是空的、装水还是装咖啡？"),
            _q("B", "liquid", "enum:Empty|Water|Coffee", f"B（正式历史中{'最先' if first == 'B' else '随后第一次'}拿起来接水的杯子）现在是空的、装水还是装咖啡？"),
            _q("A", "location", "semantic_location", "A 杯现在在哪里？"),
            _q("B", "location", "semantic_location", "B 杯现在在哪里？"),
            _q("M", "isToggled", "boolean", "咖啡机现在开启了吗？")])


def run_h01_1(ctx):
    return run_h01(ctx, 1)


def run_h01(ctx, variant):
    story = H01Natural(ctx, variant)
    try:
        story.run()
    except Exception as exc:
        story.fail(exc)
        raise
