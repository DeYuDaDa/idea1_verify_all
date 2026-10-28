"""Generate hard-group candidate data and full native traces, without a model."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from full_step_trace import FullStepTrace
from hard_camera import CameraPreflightError, audit_fixed_views, configure_evidence_cameras
from hard_context import HardContext
from hard_navigation import NavigationUnavailable
from hard_scene_survey import survey_scenes
from hard_inventory_prepare import ensure_native_inventory
from hard_inventory import check_inventory
from hard_contracts import validate_instance_contract
from hard_export import NativeMeasurementUnavailable, export_case, public_roles, sha_file, write_audit_timeline, write_json
from hard_scenarios import HardConstructionError, cases
from observation_views import world_state
from interactions import Interactions
from runtime import ControllerSession


HERE = Path(__file__).resolve().parent
COMMIT = "f0825767cd50d69f666c7f282e54abfe58f1e917"
BUILD = f"thor-CloudRendering-{COMMIT}"
FROZEN_CASES = {"H04-2", "H04-3"}


def controller_launch_options(platform, build_cache, executable=None):
    """Keep cached CloudRendering builds out of AI2-THOR's ExternalBuild branch.

    In ai2thor 5.0.0 an explicit executable selects ExternalBuild/Linux64 even
    when platform=CloudRendering was requested. Use the verified pinned cache
    through find_build instead; never invent a DISPLAY value to hide this.
    """
    cache = Path(build_cache).expanduser().resolve()
    options = {"build_cache_dir": cache, "commit_id": COMMIT}
    if platform != "CloudRendering":
        options["local_executable_path"] = executable
        return options
    pinned = cache / "releases" / BUILD / BUILD
    if executable is not None and Path(executable).expanduser().resolve() != pinned:
        raise ValueError("CloudRendering requires the existing pinned cache executable; "
                         "a different local_executable_path would select ExternalBuild/Linux64 "
                         "in ai2thor 5.0.0. No download or DISPLAY rewrite was attempted.")
    data = pinned.parent / f"{BUILD}_Data"
    if (not pinned.is_file() or pinned.stat().st_size == 0 or not os.access(pinned, os.X_OK)
            or not data.is_dir() or not any(data.iterdir())):
        raise RuntimeError(f"Pinned CloudRendering cache is incomplete: {pinned}; "
                           "refusing to construct Controller or download a build")
    # Deliberately omit local_executable_path: even the correct cached path
    # would switch AI2-THOR to its ExternalBuild/Linux64 startup branch.
    return options


def plan(selected):
    return {
        "schema": "hard-plan/v1", "model_called": False, "simulator_started": False,
        "status": "static_plan_only_not_a_geometry_or_mechanism_pass",
        "cases": [{"case_id": c.case_id, "group_id": c.group_id, "scene": c.scene, "title": c.title,
                   "conditional_reparenting_unverified": c.case_id == "H04-4"} for c in selected],
        "checks": ["native inventory and capabilities before history", "spare placement slots",
                   "all history heat-source prerequisites", "one final target event",
                   "live AABB and fixed-camera mask preflight", "pixel-exact RLE with step mappings"],
        "limits": "Missing H01/H02 objects may be created by a native, recorded private setup action. Actual distinct IDs/capabilities must pass again in each world. Failures stay failures; twenty designs do not imply twenty valid constructions.",
    }


def _identity_history(ctx):
    """Bind public aliases in actual first-person frames, across a native tour."""
    from runtime import StepResult
    ctx.require(not ctx.session.inventory(), "Initial identity tour requires an empty hand")
    baseline = world_state(ctx.session.snapshot())["objects"]
    anchors = []
    for alias in public_roles(ctx):
        ctx.phase(f"公开初态身份巡视：{alias}", public=True, kind="history")
        ctx.navigate_to(alias, "initial_first_person_identity")
        event = ctx.session.controller.last_event
        bbox = Interactions._rendered_target_bbox(StepResult(event, ctx.session.snapshot(), {}), ctx.roles[alias])
        ctx.require(bbox is not None, f"First-person initial identity is not visible: {alias}")
        row = ctx.trace.capture_current(f"第一人称身份确认：{alias}")
        anchors.append({"alias": alias, "view_id": "agent",
                        "initial_capture_group_index": row["global_step"],
                        "pixel_bbox": [bbox["x"], bbox["y"], bbox["x"] + bbox["width"],
                                       bbox["y"] + bbox["height"]]})
    ctx.initial_identity_regions = anchors
    actual = world_state(ctx.session.snapshot())["objects"]
    changed = [alias for alias in public_roles(ctx)
               if baseline.get(ctx.roles[alias]) != actual.get(ctx.roles[alias])]
    ctx.check("identity_tour_preserves_task_state", not changed, {"changed_roles": changed})
    ctx.require(not changed and not ctx.session.inventory(),
                f"First-person identity tour changed task object state: {changed}")
    write_json(ctx.out / "initial_identity_regions.json", anchors)


def _camera_preflight(ctx, trace):
    """Configure debug cameras only when requested; agent-only is explicit, not screened."""
    if getattr(ctx, "debug_views", False):
        report = configure_evidence_cameras(ctx, trace, ctx.out / "camera_preflight")
        ctx.require(report.get("status") == "screened", f"Camera preflight rejected: {report.get('error')}")
        return report
    report = {"status": "not_requested", "camera_kind": "none_agent_first_person_only",
              "camera_actions": [], "selected_views": [], "semantic_readability": "not_assessed",
              "note": "Fixed-camera checks were not run. Identity evidence comes only from the real agent first-person tour."}
    write_json(ctx.out / "camera_preflight" / "report.json", report)
    return report


def _preflight(ctx, trace):
    preflight_label = ("真实实例与调试相机预检" if getattr(ctx, "debug_views", False)
                       else "真实实例与第一视角配置")
    trace.set_phase(preflight_label, public=False, kind="calibration")
    trace.mark(preflight_label + "开始", kind="calibration_begin")
    trace.set_role_ids(ctx.roles)
    # Let native setup settle before testing whether observation itself changes
    # the world. This preserves the strict camera guard rather than deleting
    # motion/geometry fields from the comparison.
    stable = 0
    previous = world_state(ctx.session.snapshot())
    stability = []
    for index in range(20):
        ctx.step("Pass")
        current = world_state(ctx.session.snapshot())
        stable = stable + 1 if current == previous else 0
        stability.append({"pass": index + 1, "unchanged": current == previous})
        previous = current
        if stable >= 2:
            break
    write_json(ctx.out / "pre_camera_stability.json", stability)
    ctx.require(stable >= 2, "Native setup did not reach a stable baseline before bounded camera preflight")
    # Future held positions are proposals, not measured trajectories. Preserve
    # them separately from the native receptacle/waypoint IDs used for actions.
    agent = ctx.session.snapshot().get("agent", {}).get("position", {})
    if all(k in agent for k in ("x", "y", "z")):
        ctx.capture_waypoints = {a: [{"position": {"x": agent["x"], "y": agent["y"] + 1.0,
                                                    "z": agent["z"]},
                                     "note": "proposed held region; not a measured endpoint"}]
                                 for a in public_roles(ctx) if ctx.obj(a).get("pickupable") is True}
    _camera_preflight(ctx, trace)
    ctx.initial_identity_regions = []  # Grounded later in the public agent-only tour.
    if ctx.group_id == "H03":
        mapping = []
        for knob in ("KA", "KB"):
            actual = [entry.get("objectId") if isinstance(entry, dict) else entry
                      for entry in (ctx.obj(knob).get("controlledObjects") or [])]
            controlled = [b for b in ("BA", "BB") if ctx.roles[b] in actual]
            ctx.require(len(controlled) == 1, "Unresolved actual knob/burner public mapping")
            mapping.append(f"{knob}控制{controlled[0]}")
        ctx.public_declarations.append("本实例固定控制映射：" + "；".join(mapping) + "。")
    if ctx.group_id == "H05":
        ctx.require(ctx.obj("Z").get("isCooked") is False, "Initial potato must really be uncooked")
        ctx.public_declarations.append("公开历史起点：土豆Z未熟，温度为室温；后续熟度依据历史恢复。")
    trace.mark(preflight_label + "完成", kind="calibration_end")


def _public_capture_errors(trace):
    return [r for r in trace.events if r.get("phase_public") and
            (not r.get("new_event_received") or r.get("frame_status") != "captured"
             or r.get("action") in {"Teleport", "TeleportFull", "PlaceObjectAtPoint",
                                    "CreateObject", "CreateObjectAtLocation", "InitialRandomSpawn"})]


def target_capture_diagnostics(ctx, trace):
    events = [e for e in trace.events if e.get("phase_public")]
    hashes = {}
    for event in events:
        for frame in event.get("frames", []):
            if frame.get("pixel_sha256"):
                hashes.setdefault(frame["view_id"], set()).add(frame["pixel_sha256"])
    target_index = ctx.target_event.get("event_index")
    target = next((i for i, e in enumerate(events)
                   if e.get("action_index") == target_index and e.get("phase_kind") == "target"
                   and e.get("record_kind") != "checkpoint"), None)
    before = {o["objectId"]: o for o in ctx.before_target.get("objects", [])}
    after = {o["objectId"]: o for o in ctx.after_target.get("objects", [])}
    moved = []
    for alias in public_roles(ctx):
        p = before.get(ctx.roles[alias], {}).get("position")
        q = after.get(ctx.roles[alias], {}).get("position")
        if p and q and sum((float(p[k]) - float(q[k])) ** 2 for k in ("x", "y", "z")) > 0.02 ** 2:
            moved.append(alias)
    same = None
    if target is not None and target > 0:
        prior = {f["view_id"]: f.get("pixel_sha256") for f in events[target - 1].get("frames", [])}
        current = {f["view_id"]: f.get("pixel_sha256") for f in events[target].get("frames", [])}
        common = set(prior) & set(current)
        same = bool(common) and all(prior[k] == current[k] for k in common)
    return {
        "per_view_unique_rgb": {k: len(v) for k, v in hashes.items()},
        "all_public_views_constant": bool(hashes) and all(len(v) == 1 for v in hashes.values()),
        "actual_world_position_changed_roles": moved,
        "target_native_frame_found": target is not None,
        "target_before_after_rgb_all_identical": same,
        "motion_without_rgb_change_requires_review": bool(moved) and same is True,
        "note": "相同RGB不是相机故障证明；须区分出画、遮挡、不可见属性与稳定等待。",
    }


def _quarantine_partial_exports(root, case_id, directory):
    """A failed export must never appear as a legacy/reconstructed question."""
    for folder in ("data/input", "prepared_requests", "hidden_gold"):
        for mode in ("V", "S"):
            source = root / folder / f"{case_id}_{mode}.json"
            if source.is_file():
                # Do not create a nested data/input tree: the one-click
                # reviewer would mistake it for another published dataset.
                target = directory / "unpublished_fragments" / folder.replace("/", "_") / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise FileExistsError(f"Refusing to replace failed export evidence: {target}")
                source.rename(target)


def generate(selected, out, config, *, build_cache, executable=None, seed=17, scene_limit=30, debug_views=False):
    frozen = sorted({c.case_id for c in selected} & FROZEN_CASES)
    if frozen:
        raise ValueError("Refusing to regenerate frozen, human-accepted cases: " + ", ".join(frozen))
    out = Path(out).resolve()
    try:
        out.relative_to(HERE.parent)
    except ValueError:
        pass
    else:
        raise ValueError("Generated data must stay outside the Git repository")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("Refusing to replace an existing batch")
    out.mkdir(parents=True, exist_ok=True)
    # The reviewer can still open a zero-publication batch and show its
    # construction diagnostics; no fake model question is inserted.
    (out / "data" / "input").mkdir(parents=True, exist_ok=True)
    sources = [p for p in HERE.glob("hard_*.py")] + [HERE / n for n in
              ("runtime.py", "interactions.py", "full_step_trace.py", "view_planning.py", "observation_views.py",
               "nested_setup.py", "docs/ai2thor_object_reference.md", "困难组逐题流程与全程采集核对_20261027.md")]
    manifest = {"schema": "hard-generation/v1", "created_utc": datetime.now(timezone.utc).isoformat(),
                "model_called": False, "build_commit_requested": COMMIT, "seed": seed,
                "unity_executable": str(executable) if executable else None,
                "unity_executable_sha256": sha_file(executable) if executable else None,
                "python": sys.version,
                "versions": {n: importlib.metadata.version(n) for n in ("ai2thor", "numpy", "Pillow")},
                "source_sha256": {str(p.relative_to(HERE)): sha_file(p) for p in sources if p.is_file()},
                "plan": plan(selected), "review_status": "pending_human_review",
                "view_mode": "agent_plus_private_debug_fixed_views" if debug_views else "agent_first_person_only",
                "debug_views_enabled": bool(debug_views),
                "view_mode_note": ("Private fixed/overview/detail cameras are diagnostic only; they do not alter public first-person exports or physical labels."
                                   if debug_views else "No fixed cameras are configured; identity evidence is from the actual agent first-person tour only.")}
    write_json(out / "run_manifest.json", manifest)
    platform = config.get("platform", "CloudRendering")
    launch = controller_launch_options(platform, build_cache, executable)
    survey = survey_scenes(selected, out, config, launch, scene_limit=scene_limit, seed=seed)
    rows = []
    for case in selected:
        directory = out / "audit_traces" / case.case_id
        session = trace = ctx = None
        started = time.monotonic()
        scene = survey["assignments"].get(case.group_id)
        row = {"case_id": case.case_id, "scene": scene or case.scene, "title": case.title,
               "status": "not_started", "published_inputs": []}
        try:
            if scene is None:
                raise HardConstructionError(f"No surveyed native scene satisfied {case.group_id} inventory; "
                                            "see inventory_survey.json, including any native addition attempts.")
            session = ControllerSession(scene=scene, platform=platform,
                        width=config.get("width", 640), height=config.get("height", 480),
                        controller_kwargs={"snapToGrid": False},
                        **launch)
            trace = FullStepTrace(session, directory)
            trace.set_phase("初始化与原生搭建", public=False, kind="setup")
            trace.capture_current("原生初始化返回")
            write_json(directory / "initial_inventory.json", session.snapshot())
            def phase(label, public, kind):
                prior = ctx.executed_phases[-2]["label"] if len(ctx.executed_phases) > 1 else "初始化与原生搭建"
                if ctx.history_started and public and trace.events:
                    checkpoints = getattr(ctx, "view_checkpoints", [])
                    checkpoints.append({"next_phase": label, "previous_phase": prior,
                                        "view_audit": (audit_fixed_views(ctx, trace, prior)
                                                       if getattr(ctx, "debug_views", False)
                                                       else {"status": "not_requested", "camera_kind": "none_agent_first_person_only",
                                                             "native_actions_sent": 0, "views": [],
                                                             "note": "No fixed-camera audit was requested; first-person evidence remains in the trace."})})
                    ctx.view_checkpoints = checkpoints
                    write_json(directory / "view_checkpoints.json", checkpoints)
                trace.mark(prior + " 结束", kind="phase_end")
                trace.set_phase(label, public=public, kind=kind)
                trace.mark(label + " 开始", kind="phase_begin")
            ctx = HardContext(session, directory, seed=seed, on_phase=phase,
                              on_start_history=lambda context: _preflight(context, trace),
                              on_identity_history=_identity_history)
            ctx.case_id, ctx.group_id, ctx.family = case.case_id, case.group_id, case.family
            ctx.debug_views = bool(debug_views)
            ctx.trace = trace
            if case.group_id in {"H01", "H02"}:
                ctx.mark_setup_stage("原生补充独立物品并核对属性", kind="setup")
                prepared = ensure_native_inventory(session, [case.group_id], seed=seed,
                                                   history_started=ctx.history_started)
                write_json(directory / "native_inventory_preparation.json", prepared)
                verified = check_inventory(case.group_id, session.snapshot())
                ctx.check("native_inventory_preparation", verified["satisfied"],
                          {"preparation": prepared, "inventory_check": verified})
                ctx.require(prepared.get("status") in {"already_sufficient", "added_and_verified"}
                            and verified["satisfied"],
                            "Native inventory preparation did not verify distinct, capable objects in this case world")
            case.run(ctx)
            ctx.require(ctx.target_event.get("success") is True, "Target action was not confirmed successful")
            contracts = validate_instance_contract(ctx)
            for check in contracts:
                ctx.check(check["name"], check["passed"], check.get("detail"))
            write_json(directory / "instance_contract.json", contracts)
            ctx.require(bool(contracts) and all(c["passed"] for c in contracts),
                        "This actual instance does not establish the declared local mechanism; retain its trace without publishing a rule/Gold contradiction")
            trace.mark("规定观察窗口结束", kind="observation_end")
            diagnostics = (audit_fixed_views(ctx, trace, ctx.executed_phases[-1]["label"])
                           if debug_views else {"status": "not_requested",
                               "camera_kind": "none_agent_first_person_only",
                               "agent_capture_diagnostics": target_capture_diagnostics(ctx, trace)})
            write_json(directory / "end_view_diagnostics.json", diagnostics)
            ctx.require(not _public_capture_errors(trace), "Public history has missing/stale camera frames")
            ctx.require(not session.observer_errors, "A full-trace observer failed; do not silently drop steps")
            index = trace.finish()
            write_audit_timeline(ctx, trace, case)
            row["published_inputs"] = export_case(ctx, trace, out, case)
            row["status"] = "candidate_pending_visual_review"
            row["capture_steps"] = index["global_step_count"]
            row["identical_frame_diagnostics"] = diagnostics
        except (HardConstructionError, CameraPreflightError, NativeMeasurementUnavailable, NavigationUnavailable) as exc:
            row.update(status="construction_or_evidence_unavailable", error=str(exc), traceback=traceback.format_exc())
        except Exception as exc:
            row.update(status="execution_error", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        finally:
            if not row["published_inputs"]:
                _quarantine_partial_exports(out, case.case_id, directory)
            if trace:
                try:
                    trace.finish()
                    if ctx:
                        write_audit_timeline(ctx, trace, case)
                except Exception as exc:
                    row["trace_flush_error"] = f"{type(exc).__name__}: {exc}"
            if ctx:
                if trace:
                    ctx.capture_diagnostics = target_capture_diagnostics(ctx, trace)
                    write_json(directory / "target_capture_diagnostics.json", ctx.capture_diagnostics)
                    write_audit_timeline(ctx, trace, case)
                write_json(directory / "native_result.json", {
                    "case_id": case.case_id, "roles": ctx.roles, "waypoints": ctx.waypoints,
                    "checks": ctx.checks, "phases": ctx.executed_phases, "target_event": ctx.target_event,
                    "initial_metadata": ctx.initial_metadata, "before_target": ctx.before_target,
                    "after_target": ctx.after_target, "model_called": False,
                    "measurement_issues": getattr(ctx, "measurement_issues", []),
                    "navigation_attempts": ctx.navigation_attempts,
                })
            if session:
                try:
                    session.stop()
                except Exception as exc:
                    row["controller_stop_error"] = str(exc)
            row["elapsed_wall_seconds"] = round(time.monotonic() - started, 3)
            row["last_phase"] = ctx.executed_phases[-1]["label"] if ctx and ctx.executed_phases else None
            row["target_event_completed"] = bool(ctx and ctx.target_event.get("success") is True)
            rows.append(row)
            write_json(out / "generation_summary.json", {
                "requested_cases": [c.case_id for c in selected], "attempts": rows,
                "not_attempted_cases": [c.case_id for c in selected if c.case_id not in {r["case_id"] for r in rows}],
                "published_case_count": sum(bool(r["published_inputs"]) for r in rows),
                "published_input_count": sum(len(r["published_inputs"]) for r in rows),
                "source_status": "candidates_pending_review" if len(rows) == len(selected)
                    and all(r["published_inputs"] for r in rows) else "source_incomplete",
                "model_called": False, "benchmark_ready": False,
            })
        if session is None and scene is not None:
            break  # Infrastructure failure must not cause twenty repeated launches.
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    selection = p.add_mutually_exclusive_group()
    selection.add_argument("--cases", default=None)
    selection.add_argument("--all", action="store_true")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--out", type=Path)
    p.add_argument("--config", type=Path, default=HERE / "config.json")
    p.add_argument("--build-cache-dir", type=Path)
    p.add_argument("--local-executable-path", type=Path)
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--scene-limit", type=int, default=30)
    p.add_argument("--debug-views", action="store_true", help="Enable private fixed/overview/detail diagnostic cameras")
    p.add_argument("--platform", choices=("CloudRendering", "Linux64"), default=None)
    args = p.parse_args(argv)
    if not 1 <= args.scene_limit <= 30:
        p.error("--scene-limit must be between 1 and 30")
    available = cases()
    ids = [c.case_id for c in available if c.case_id not in FROZEN_CASES] if args.all else (args.cases or "H05-1").split(",")
    if len(ids) != len(set(ids)) or set(ids) - {c.case_id for c in available}:
        p.error("Unknown/duplicate case; use H01-1 through H05-4")
    selected = [c for c in available if c.case_id in ids]
    frozen = sorted(set(ids) & FROZEN_CASES)
    if frozen and not args.plan_only:
        p.error("Refusing to regenerate frozen, human-accepted cases: " + ", ".join(frozen))
    if args.plan_only:
        print(json.dumps(plan(selected), ensure_ascii=False, indent=2))
        return 0
    if sys.platform != "linux":
        p.error("Linux generation only; do not execute on the Windows authoring checkout")
    if args.out is None or args.build_cache_dir is None:
        p.error("--out and --build-cache-dir are required for a real generation")
    executable = args.local_executable_path
    if executable is None:
        if args.platform == "Linux64":
            p.error("Linux64 requires an explicitly configured existing executable; no download is attempted")
        executable = args.build_cache_dir / "releases" / BUILD / BUILD
    if not executable.is_file() or not os.access(executable, os.X_OK):
        p.error("Pinned existing Unity executable is unavailable; no download will be attempted")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.platform:
        config["platform"] = args.platform
    result = generate(selected, args.out, config, build_cache=args.build_cache_dir,
                      executable=executable, seed=args.seed, scene_limit=args.scene_limit,
                      debug_views=args.debug_views)
    for row in result:
        if not row["published_inputs"]:
            print(f"[hard_generate] {row['case_id']} {row['status']}: {row.get('error', 'no published input')}",
                  file=sys.stderr, flush=True)
    image_count = sum(1 for path in args.out.rglob("*.png") if path.is_file())
    print(json.dumps({"out": str(args.out), "attempted": len(result),
                      "not_attempted": len(selected) - len(result),
                      "published_cases": sum(bool(r["published_inputs"]) for r in result),
                      "image_file_count": image_count,
                      "source_status": "candidates_pending_review"
                                       if len(result) == len(selected) and all(r["published_inputs"] for r in result)
                                       else "source_incomplete",
                      "model_called": False}, ensure_ascii=False, indent=2))
    return 0 if len(result) == len(selected) and all(r["published_inputs"] for r in result) else 2


if __name__ == "__main__":
    raise SystemExit(main())
