"""Role-based third-party RGB capture with explicit observation interventions.

Camera candidates come from actual object geometry, never FloorPlan-specific
coordinates. Rendered third-party instance masks screen framing, not semantics.
Camera changes run under physics pause and compare native world state; no agent
teleport, object move, open/close or artificial state setter is used to photograph.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path

from view_planning import plan_views

FAMILIES = {"coffee": "coffee_machine", "water": "sink", "shower": "sink",
            "carrying": "carryplate", "current_carry_relation": "carryplate",
            "local_control_mapping": "stove", "background_evolution_time_control": "stove",
            "redundant_property_support": "stove", "nested_carry": "nested",
            "nested_heat": "nested", "nested_wash": "nested"}
INITIAL_TYPES = {
    "coffee_machine": ("CoffeeMachine", "Mug"), "sink": ("Faucet", "SinkBasin", "Bowl"),
    "microwave": ("Microwave", "Potato"), "toaster": ("Toaster", "Bread", "BreadSliced"),
    "stove": ("StoveKnob", "StoveBurner", "Kettle", "Pot"),
    "carryplate": ("Plate", "Apple"), "nested": ("Plate", "Bowl", "Apple"),
}
STATE_FIELDS = ("temperature", "ObjectTemperature", "isCooked", "isDirty", "isFilledWithLiquid",
                "fillLiquid", "isToggled", "isOpen", "isBroken", "isPickedUp",
                "isMoving", "isSliced", "isUsedUp")
DIAGNOSTIC_MAX_OBJECTS = 32
DIAGNOSTIC_MAX_VALUE_CHARS = 160


def world_state(metadata: dict) -> dict:
    """Ignore visibility/camera/lastAction fields, retain physical task state."""
    def xyz(value, digits=4):
        return {k: round(float(value[k]), digits) for k in ("x", "y", "z") if k in (value or {})}
    rows = {}
    for obj in metadata.get("objects", []):
        rows[obj.get("objectId")] = {
            **{k: copy.deepcopy(obj[k]) for k in STATE_FIELDS if k in obj},
            "position": xyz(obj.get("position")), "rotation": xyz(obj.get("rotation"), 3),
            "parents": sorted(obj.get("parentReceptacles") or []),
            "children": sorted(obj.get("receptacleObjectIds") or []),
        }
    agent = metadata.get("agent", {})
    return {"objects": rows, "agent_position": xyz(agent.get("position")),
            "agent_rotation": xyz(agent.get("rotation"), 3),
            "inventory": sorted(o.get("objectId", "") for o in metadata.get(
                "inventoryObjects", agent.get("inventoryObjects", [])))}


def changed_objects(before: dict, after: dict) -> list[str]:
    return [key for key in sorted(set(before["objects"]) | set(after["objects"]))
            if before["objects"].get(key) != after["objects"].get(key)] + (
        ["agent_or_inventory"] if any(before[k] != after[k] for k in
         ("agent_position", "agent_rotation", "inventory")) else [])


def observation_state_delta(before: dict, after: dict, *, phase: str) -> tuple[list[str], list[str]]:
    """Account for motion flags on physics-control transitions, and nothing else.

    The step-39 native trace shows PausePhysicsAutoSim flips only isMoving for
    four objects before any camera exists. Keep the raw trace, but do not use
    that control flag as evidence of scene damage. Geometry, relations, all
    other attributes and camera-phase motion flags remain strict comparisons.
    """
    if phase not in {"pause", "unpause"}:
        return changed_objects(before, after), []
    left, right = copy.deepcopy(before), copy.deepcopy(after)
    control_flags = []
    for object_id in set(left["objects"]) & set(right["objects"]):
        old, new = left["objects"][object_id], right["objects"][object_id]
        if old.get("isMoving") != new.get("isMoving"):
            control_flags.append(object_id)
        old.pop("isMoving", None)
        new.pop("isMoving", None)
    return changed_objects(left, right), sorted(control_flags)


def _diagnostic_value(value):
    """Return a compact, bounded representation for saved state-diff audits."""
    if isinstance(value, dict):
        value = {str(k): _diagnostic_value(v) for k, v in sorted(value.items())}
    elif isinstance(value, (list, tuple)):
        items = list(value)
        value = [_diagnostic_value(v) for v in items[:16]]
        if len(items) > 16:
            value[-1] = "..."
    elif not isinstance(value, (str, int, float, bool)) and value is not None:
        value = repr(value)
    if isinstance(value, str) and len(value) > DIAGNOSTIC_MAX_VALUE_CHARS:
        return value[:DIAGNOSTIC_MAX_VALUE_CHARS - 3] + "..."
    return value


def state_diff_audit(before: dict, after: dict, target_roles: dict[str, str], *,
                     phase: str, action: str, action_index: int | None,
                     action_kwargs: dict | None = None) -> dict:
    """Explain a world_state difference without changing guard semantics."""
    roles_by_id = {}
    for alias, object_id in target_roles.items():
        roles_by_id.setdefault(object_id, []).append(alias)
    changes = []
    object_ids = sorted(set(before["objects"]) | set(after["objects"]))
    for object_id in object_ids:
        old = before["objects"].get(object_id)
        new = after["objects"].get(object_id)
        if old == new:
            continue
        if old is None:
            status = "added"
            fields = {key: {"before": "__MISSING__", "after": _diagnostic_value(value)}
                      for key, value in new.items()}
        elif new is None:
            status = "removed"
            fields = {key: {"before": _diagnostic_value(value), "after": "__MISSING__"}
                      for key, value in old.items()}
        else:
            status = "changed"
            fields = {key: {"before": _diagnostic_value(old.get(key, "__MISSING__")),
                            "after": _diagnostic_value(new.get(key, "__MISSING__"))}
                      for key in sorted(set(old) | set(new)) if old.get(key, "__MISSING__") != new.get(key, "__MISSING__")}
        aliases = sorted(roles_by_id.get(object_id, []))
        changes.append({"entity_type": "object", "object_id": object_id, "status": status,
                        "selected_target_roles": aliases, "unrelated_object": not bool(aliases),
                        "fields": fields})
    for field in ("agent_position", "agent_rotation", "inventory"):
        if before[field] != after[field]:
            changes.append({"entity_type": "agent_or_inventory", "object_id": None,
                            "status": "changed", "selected_target_roles": [],
                            "unrelated_object": False,
                            "fields": {field: {"before": _diagnostic_value(before[field]),
                                               "after": _diagnostic_value(after[field])}}})
    changed_ids = changed_objects(before, after)
    return {"phase": phase, "action": action, "action_index": action_index,
            "action_kwargs": _diagnostic_value(action_kwargs or {}),
            "changed_entities": changed_ids[:DIAGNOSTIC_MAX_OBJECTS],
            "changed_entity_key_count": len(changed_ids),
            "changes": changes[:DIAGNOSTIC_MAX_OBJECTS],
            "changed_entity_count": len(changes),
            "truncated": len(changes) > DIAGNOSTIC_MAX_OBJECTS}


def physics_is_paused(records: list[dict]) -> bool:
    for row in reversed(records):
        if row.get("lastActionSuccess") is not True:
            continue
        if row.get("action") in {"PausePhysicsAutoSim", "UnpausePhysicsAutoSim"}:
            return row["action"] == "PausePhysicsAutoSim"
    return False


def role_objects(metadata: dict, roles: dict[str, str], family: str) -> dict:
    by_id = {o["objectId"]: o for o in metadata.get("objects", []) if "objectId" in o}
    objects = {alias: by_id[oid] for alias, oid in roles.items() if oid in by_id}
    if objects:
        return objects
    # Scene-initial capture precedes task binding. Use explicit family-relevant
    # inventory, not a random default agent view facing a refrigerator.
    kinds = INITIAL_TYPES.get(FAMILIES.get(family, family), ())
    if family == "nested_heat":
        kinds = ("Microwave", "Bowl", "Potato")
    elif family == "nested_wash":
        kinds = ("Faucet", "SinkBasin", "Bowl", "Plate")
    for kind in kinds:
        matches = sorted((o for o in by_id.values() if o.get("objectType") == kind), key=lambda o: o["objectId"])
        for i, obj in enumerate(matches[:2]):
            objects[f"initial_{kind}_{i+1}"] = obj
    return objects


def mask_presence(event, camera_id: int, targets: dict[str, str]) -> dict:
    frames = getattr(event, "third_party_camera_frames", [])
    masks = getattr(event, "third_party_instance_masks", [])
    if camera_id >= len(frames) or camera_id >= len(masks):
        return {"status": "third_party_masks_unavailable", "roles": {}, "present_count": 0, "score": -1.0}
    frame = frames[camera_id]
    height, width = int(frame.shape[0]), int(frame.shape[1])
    rows = {}
    for alias, oid in targets.items():
        try:
            mask = masks[camera_id][oid]
            ys, xs = mask.nonzero()[:2]
            count = len(xs)
            bbox = None if not count else {"x": int(xs.min()), "y": int(ys.min()),
                "width": int(xs.max()-xs.min()+1), "height": int(ys.max()-ys.min()+1)}
        except (KeyError, IndexError, TypeError, AttributeError):
            count, bbox = 0, None
        fraction = count / max(1, height * width)
        present = count >= 16 and fraction >= 0.00015
        rows[alias] = {"object_id": oid, "pixels": count, "fraction": fraction, "bbox": bbox,
                       "framing_presence": present, "semantic_readability": "not_assessed"}
    present_count = sum(row["framing_presence"] for row in rows.values())
    return {"status": "mask_presence_only", "roles": rows, "present_count": present_count,
            "score": present_count * 100.0 + sum(min(row["fraction"], 0.25) for row in rows.values()) * 10}


class EvidenceCameras:
    def __init__(self, session, *, family: str, max_views: int = 3, candidates_per_view: int = 4):
        self.session, self.family = session, family
        self.max_views, self.candidates_per_view = max_views, candidates_per_view
        self._ledger = session.records
        self._ids = []
        self._signature = None
        self._selected = []
        self.disabled = False
        self.unhealthy = False
        self.contaminated = False

    def capture(self, metadata: dict, roles: dict, directory: Path, stem: str) -> dict:
        from PIL import Image
        started = time.monotonic()
        report = {"camera_kind": "third_party", "views": [], "candidate_trials": [],
                  "world_state_changed": False, "unpause_failed": False,
                  "semantic_readability": "not_assessed", "attribute_clock_verified": False}
        if self.session.records is not self._ledger:
            self._ledger = self.session.records
            self._ids, self._selected, self._signature = [], [], None
            self.disabled = False
        if self.disabled:
            return {**report, "error": "observer_disabled_after_previous_error"}
        objects = role_objects(metadata, roles, self.family)
        family = FAMILIES.get(self.family, self.family)
        # The nested planner identifies the actual bound outer/inner/content;
        # source-only partial setup can instead use its actual device family.
        plan = plan_views(objects, device_family=family, observed_metadata=metadata)
        if not plan["groups"] and objects:
            plan = plan_views(objects, observed_metadata=metadata)
        report["plan"] = plan
        groups = [g for g in plan["groups"] if g.get("fit_status") != "not_fit"
                  and g.get("status") not in {"not_fit", "oversized_bounds"}][:self.max_views]
        if not groups:
            return {**report, "error": f"No local evidence camera region: {plan['status']}"}
        signature = json.dumps([{ "id": g["group_id"],
            "roles": {a: objects[a].get("objectId") for a in g["roles"] if a in objects},
            "focus": {k: round(float(v), 2) for k,v in g["focus"]["point"].items()}}
            for g in groups], sort_keys=True)
        configure = signature != self._signature
        baseline = world_state(metadata)
        comparison_baseline = baseline
        already_paused = physics_is_paused(self.session.records)
        pause_attempted = False
        changed = set()
        state_checks = []
        selected_target_roles = {alias: object_id for alias, object_id in roles.items()
                                 if object_id in {obj.get("objectId") for obj in objects.values()}}
        if not selected_target_roles:
            selected_target_roles = {alias: obj["objectId"] for alias, obj in objects.items()
                                     if "objectId" in obj}

        def save_failure_evidence(result, phase):
            # Private debugging artifacts are never copied into view_frames.
            # Retain exact metadata and available images even when evidence
            # approval fails, rather than returning only a list of object IDs.
            try:
                from runtime import ControllerSession
                target = directory.parent / "diagnostics" / "observer" / stem
                target.mkdir(parents=True, exist_ok=True)
                for name, value in (("before.json", metadata), (f"{phase}_after.json", result.metadata)):
                    path = target / name
                    path.write_text(json.dumps(ControllerSession._jsonable(value),
                                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                images = []
                agent_frame = getattr(result.event, "frame", None)
                if agent_frame is not None:
                    images.append(("agent", agent_frame))
                images.extend((f"third_party_{i}", frame) for i, frame in enumerate(
                    getattr(result.event, "third_party_camera_frames", []) or []))
                for name, frame in images:
                    path = target / f"{phase}_{name}_diagnostic.png"
                    Image.fromarray(frame).save(path, format="PNG")
                    report.setdefault("diagnostic_frames", []).append({
                        "path": str(path), "purpose": "observer_failure_debug_only",
                        "approved_evidence": False})
                report["diagnostic_metadata_directory"] = str(target)
            except Exception as exc:
                report.setdefault("diagnostic_save_errors", []).append(f"{type(exc).__name__}: {exc}")

        def native(action, *, phase, **kwargs):
            nonlocal comparison_baseline
            try:
                result = self.session.step(action, raise_on_failure=True, **kwargs)
            finally:
                if self.session.records and self.session.records[-1].get("action") == action:
                    self.session.records[-1]["observation_only"] = True
            if result.record.get("lastActionSuccess") is not True:
                raise RuntimeError(f"Observer action did not succeed: {action}")
            after = world_state(result.metadata)
            action_index = result.record.get("index")
            if action_index is None and self.session.records:
                action_index = self.session.records[-1].get("index", len(self.session.records) - 1)
            check = state_diff_audit(comparison_baseline, after, selected_target_roles,
                                     phase=phase, action=action, action_index=action_index,
                                     action_kwargs=kwargs)
            guard_changes, control_flags = observation_state_delta(comparison_baseline, after, phase=phase)
            check.update(guard_changed_entities=guard_changes,
                         control_motion_flag_changes=control_flags,
                         comparison_baseline="pre_capture" if phase == "pause" else "post_pause")
            state_checks.append(check)
            changed.update(guard_changes)
            if changed:
                save_failure_evidence(result, phase)
                raise RuntimeError("Observer intervention changed native task state")
            if phase == "pause":
                # Compare all camera operations against the now-paused state.
                # Otherwise the accepted pause flags would recur as a false
                # camera failure on the very next Add/Update action.
                comparison_baseline = after
            return result

        try:
            if configure:
                if not already_paused:
                    pause_attempted = True
                    native("PausePhysicsAutoSim", phase="pause")
                selected = []
                for slot, group in enumerate(groups):
                    targets = {a: objects[a]["objectId"] for a in group["roles"] if a in objects}
                    best = None
                    for candidate in group["candidates"][:self.candidates_per_view]:
                        kwargs = {"position": candidate["position"], "rotation": candidate["rotationEuler"],
                                  "fieldOfView": candidate["fov_degrees"], "nearClippingPlane": 0.03,
                                  "farClippingPlane": 20.0}
                        if slot >= len(self._ids):
                            result = native("AddThirdPartyCamera", phase="add_camera_candidate", **kwargs)
                            cameras = result.metadata.get("thirdPartyCameras") or []
                            camera_id = int(cameras[-1]["thirdPartyCameraId"]) if cameras else len(
                                getattr(result.event, "third_party_camera_frames", [])) - 1
                            if camera_id < 0:
                                raise RuntimeError("Added camera produced no indexed third-party frame")
                            self._ids.append(camera_id)
                        else:
                            result = native("UpdateThirdPartyCamera", phase="update_camera_candidate",
                                            thirdPartyCameraId=self._ids[slot], **kwargs)
                        presence = mask_presence(result.event, self._ids[slot], targets)
                        report["candidate_trials"].append({"view": group["purpose"],
                            "candidate": candidate, "rendered_presence": presence})
                        if best is None or presence["score"] > best["presence"]["score"]:
                            best = {"candidate": candidate, "presence": presence}
                    if best is None:
                        continue
                    pose = best["candidate"]
                    native("UpdateThirdPartyCamera", phase="select_camera_pose",
                           thirdPartyCameraId=self._ids[slot], position=pose["position"],
                           rotation=pose["rotationEuler"], fieldOfView=pose["fov_degrees"],
                           nearClippingPlane=0.03, farClippingPlane=20.0)
                    selected.append({"camera_id": self._ids[slot], "purpose": group["purpose"],
                                     "target_roles": targets, "pose": pose})
                self._selected, self._signature = selected, signature

            event = self.session.controller.last_event
            for i, view in enumerate(self._selected):
                presence = mask_presence(event, view["camera_id"], view["target_roles"])
                entry = {**copy.deepcopy(view), "rendered_presence": presence,
                         "same_observation_time": True, "semantic_readability": "not_assessed"}
                if presence["present_count"] == 0:
                    entry["error"] = "No relevant target pixels; image not promoted to evidence"
                    report.setdefault("framing_failures", []).append(entry)
                    continue
                frame = event.third_party_camera_frames[view["camera_id"]]
                path = directory / f"{stem}_view_{i:02d}_{view['purpose']}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(frame).save(path, format="PNG")
                entry.update(path=str(path), png_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                report["views"].append(entry)
            if not report["views"]:
                report["error"] = "No third-party view contains a sufficiently rendered target"
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            self.disabled = True
        finally:
            if pause_attempted:
                try:
                    # Restore only a pause introduced by the observer. Never
                    # unpause a physics-controlled F9/F11 experiment's pause.
                    result = self.session.step("UnpausePhysicsAutoSim", raise_on_failure=True)
                    if self.session.records:
                        self.session.records[-1]["observation_only"] = True
                    if result.record.get("lastActionSuccess") is not True:
                        raise RuntimeError("Unpause did not confirm success")
                    after = world_state(result.metadata)
                    action_index = result.record.get("index")
                    if action_index is None and self.session.records:
                        action_index = self.session.records[-1].get("index", len(self.session.records) - 1)
                    check = state_diff_audit(baseline, after, selected_target_roles,
                                             phase="unpause", action="UnpausePhysicsAutoSim",
                                             action_index=action_index)
                    guard_changes, control_flags = observation_state_delta(baseline, after, phase="unpause")
                    check.update(guard_changed_entities=guard_changes,
                                 control_motion_flag_changes=control_flags,
                                 comparison_baseline="pre_capture")
                    state_checks.append(check)
                    changed.update(guard_changes)
                    if guard_changes:
                        save_failure_evidence(result, "unpause")
                except Exception as exc:
                    self.unhealthy = True
                    report["unpause_failed"] = True
                    report["restore_error"] = str(exc)
            report["world_state_changed"] = bool(changed)
            report["changed_objects"] = sorted(changed)
            first_changed = next((check for check in state_checks if check["changed_entity_count"]), None)
            first_rejected = next((check for check in state_checks if check["guard_changed_entities"]), None)
            report["raw_metadata_changed"] = first_changed is not None
            report["state_diff_audit"] = {
                "schema_version": 2,
                "baseline": "camera checks use post-pause state; restore checks use pre-capture state",
                "control_flag_policy": "only isMoving on Pause/Unpause is excluded from rejection; raw differences retained",
                "selected_target_roles": selected_target_roles,
                "first_changed_action": ({"phase": first_changed["phase"],
                                           "action": first_changed["action"],
                                           "action_index": first_changed["action_index"]}
                                          if first_changed else None),
                "first_rejected_action": ({"phase": first_rejected["phase"],
                                            "action": first_rejected["action"],
                                            "action_index": first_rejected["action_index"]}
                                           if first_rejected else None),
                "action_checks": state_checks,
            }
            report["observer_wall_seconds"] = time.monotonic() - started
            report["camera_actions_required"] = configure
            if changed:
                self.contaminated = True
                self.disabled = True
                # A PNG written before restore can subsequently be invalidated.
                # Move it out of rgb/ so the disk layout agrees with the index.
                for view in report["views"]:
                    try:
                        original = Path(view["path"])
                        quarantine = directory.parent / "diagnostics" / "invalidated_rgb"
                        quarantine.mkdir(parents=True, exist_ok=True)
                        destination = quarantine / original.name
                        original.replace(destination)
                        report.setdefault("diagnostic_frames", []).append({
                            "path": str(destination), "purpose": "invalidated_after_restore",
                            "approved_evidence": False})
                    except Exception as exc:
                        report.setdefault("diagnostic_save_errors", []).append(str(exc))
                report["views"] = []
                report["error"] = "Observation intervention changed native state; this attempt cannot support a mechanism claim"
        return report
