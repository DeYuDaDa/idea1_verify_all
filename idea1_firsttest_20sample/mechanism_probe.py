"""Run F1--F11 native mechanism observations, never benchmark/model evaluation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from mechanism_probe_common import ObservationCaptureFailure, ProbeContext, ProbeUnavailable, write_json
from runtime import ActionFailure, ControllerSession

HERE = Path(__file__).resolve().parent
COMMIT = "f0825767cd50d69f666c7f282e54abfe58f1e917"
BUILD = f"thor-CloudRendering-{COMMIT}"
FACTS = tuple(f"F{i}" for i in range(1, 12))
FAMILY_SCENES = {
    "thermal_liquid": "microwave", "current_carry_relation": "carrying",
    "local_control_mapping": "stove", "background_evolution_time_control": "stove",
    "nested_carry": "carrying", "nested_heat": "microwave", "nested_wash": "water",
    "redundant_property_support": "stove",
}


def registry(suite="base"):
    if suite == "rechecks":
        from mechanism_rechecks import cases
        return cases()
    if suite != "base":
        raise ValueError(f"Unknown probe suite: {suite}")
    from mechanism_probes_thermal_liquid import cases as thermal_liquid
    from mechanism_probes_relations import cases as relations
    cases = thermal_liquid() + relations()
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate mechanism case IDs")
    if any(case.fact_id not in FACTS for case in cases):
        raise ValueError("Unknown fact ID in case registry")
    if set(c.fact_id for c in cases) != set(FACTS):
        raise ValueError("Registry must explicitly cover F1 through F11")
    if any(not c.case_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in c.case_id) for c in cases):
        raise ValueError("Case IDs must be safe filename identifiers")
    return cases


def inventory(metadata: dict) -> list[dict]:
    fields = ("objectId", "objectType", "assetId", "pickupable", "receptacle",
              "cookable", "dirtyable", "canFillWithLiquid", "toggleable", "openable",
              "controlledObjects", "parentReceptacles", "receptacleObjectIds",
              "position", "axisAlignedBoundingBox")
    return [{k: obj[k] for k in fields if k in obj} for obj in metadata.get("objects", [])]


def log_check_values(detail) -> dict:
    """Readable native values, without dumping complete trajectories to stdout."""
    if not isinstance(detail, dict):
        return {}
    values = {k: detail[k] for k in ("initial", "final", "initial_isDirty", "final_isDirty",
              "configuration", "pickup", "passed", "temperature_matches", "cooked_matches",
              "expected_final_temperature", "expected_final_isCooked", "passes", "elapsed_wall_seconds") if k in detail}
    state_keys = ("temperature", "ObjectTemperature", "isCooked", "isDirty", "isFilledWithLiquid", "fillLiquid")
    for side in ("before", "after"):
        state = detail.get(side)
        if isinstance(state, dict):
            summary = {k: state[k] for k in state_keys if k in state}
            if summary:
                values[side] = summary
    metrics = detail.get("metrics")
    if isinstance(metrics, list) and metrics and isinstance(metrics[-1], dict):
        values["last_motion_sample"] = {k: v for k, v in metrics[-1].items()
                                         if k.endswith("_m") or k in {"capture_label", "observation_passes"}}
        if "displacement_m" in metrics[-1]:
            values["last_motion_sample"] = metrics[-1]
    roles = detail.get("selected_roles")
    if isinstance(roles, dict):
        values["selected_types"] = {k: v.get("objectType") for k, v in roles.items() if isinstance(v, dict)}
        values["placement_order"] = detail.get("placement_order")
    return values


def summarise(rows: list[dict], selected: list, run_metadata: dict) -> dict:
    facts = {}
    for fact_id in FACTS:
        relevant = [r for r in rows if r["fact_id"] == fact_id]
        facts[fact_id] = {
            "planned_case_ids": [c.case_id for c in selected if c.fact_id == fact_id],
            "attempt_count": len(relevant),
            "statuses": dict(Counter(r["status"] for r in relevant)),
            "attempts": [{k: row.get(k) for k in ("case_id", "scene", "status", "result_path", "error")}
                         for row in relevant],
            "global_mechanism_confirmed": False,
            "note": "Inspect actual checks, calibrated conditions and controls; do not turn an existential positive into a universal F-pass.",
        }
    return {**run_metadata, "attempts_completed": len(rows),
            "status_counts": dict(Counter(r["status"] for r in rows)),
            "capture_failure_attempts": sum(r.get("visual_capture_status") == "capture_incomplete" for r in rows),
            "invalid_native_measurements": sum(r.get("native_measurement_valid") is False for r in rows),
            "has_capture_or_measurement_failure": any(
                r.get("visual_capture_status") == "capture_incomplete"
                or r.get("native_measurement_valid") is False for r in rows),
            "facts": facts, "attempts": rows,
            "is_benchmark_evaluation": False, "model_loaded": False,
            "hard_groups_automatically_approved": False,
            "visual_evidence_review": "not_assessed"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--facts", default=",".join(FACTS))
    parser.add_argument("--cases", default="")
    parser.add_argument("--suite", choices=("base", "rechecks"), default="base",
                        help="base preserves the original 45 templates; rechecks selects only R1/R2 (12 arms)")
    parser.add_argument("--list", action="store_true", help="list native probes without starting Unity")
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--scenes", default="", help="explicit scene list, otherwise family candidates")
    parser.add_argument("--max-scenes", type=int, default=2)
    parser.add_argument("--sample-steps", default="0,1,4,12,36")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--view-mode", choices=("none", "planned", "agent", "passive"), default="none",
                        help="none: state only; passive: best-effort existing RGB without camera calls; planned/agent: strict images")
    parser.add_argument("--platform", choices=("Linux64", "CloudRendering"), default="CloudRendering")
    server_home = Path(os.environ.get("SERVER_HOME") or Path.home())
    server_profile = os.environ.get("THOR_SERVER_PROFILE", "auto")
    autodl_root = server_home / "autodl-tmp"
    data_root_default = Path(os.environ.get("DATA_ROOT") or (
        autodl_root / "idea1_firsttest_20sample"
        if server_profile == "autodl" or (server_profile == "auto" and autodl_root.is_dir() and os.access(autodl_root, os.W_OK))
        else server_home / "experiment_data" / "idea1_firsttest_20sample"
    ))
    parser.add_argument("--build-cache-dir", type=Path, default=data_root_default / "unity_cache")
    parser.add_argument("--local-executable-path", type=Path)
    args = parser.parse_args(argv)
    all_cases = registry(args.suite)
    requested = [part.strip() for part in args.facts.split(",") if part.strip()]
    if not requested or len(requested) != len(set(requested)) or set(requested) - set(FACTS):
        parser.error("--facts must be unique F1,...,F11 identifiers")
    requested_cases = [part.strip() for part in args.cases.split(",") if part.strip()]
    if set(requested_cases) - {case.case_id for case in all_cases}:
        parser.error("Unknown case ID; inspect --list")
    selected = [case for case in all_cases if case.fact_id in requested
                and (not requested_cases or case.case_id in requested_cases)]
    if not selected:
        parser.error("No cases match the requested facts and cases")
    if args.list:
        print(json.dumps([{"case_id": c.case_id, "fact_id": c.fact_id, "family": c.family}
                          for c in selected], indent=2))
        return 0
    if sys.platform != "linux":
        parser.error("Linux server only. Do not run this project on the Windows authoring machine.")
    if args.out is None:
        parser.error("--out is required for a real simulator run")
    if args.max_scenes < 1:
        parser.error("--max-scenes must be positive")
    try:
        steps = tuple(sorted(set(int(n) for n in args.sample_steps.split(","))))
        if not steps or min(steps) < 0 or max(steps) > 10000:
            raise ValueError()
    except ValueError:
        parser.error("--sample-steps must be nonnegative integers bounded by 10000")
    out = args.out.expanduser().resolve()
    try:
        out.relative_to(HERE.parent)
    except ValueError:
        pass
    else:
        parser.error("--out must be outside the Git repository")
    if out.exists() and any(out.iterdir()):
        parser.error("Refusing to overwrite a nonempty output directory")
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    source_files = ("mechanism_probe.py", "mechanism_probe_common.py", "mechanism_probes_thermal_liquid.py",
                    "mechanism_probes_relations.py", "runtime.py", "interactions.py", "frame_evidence.py",
                    "hard_group_plan.json", "config.json", "view_planning.py", "observation_views.py", "nested_setup.py",
                    "mechanism_rechecks.py")
    versions, version_errors = {}, {}
    for name in ("ai2thor", "numpy", "Pillow"):
        try:
            versions[name] = importlib.metadata.version(name)
        except Exception as exc:
            version_errors[name] = f"{type(exc).__name__}: {exc}"
    metadata = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "schema_version": 1, "python": sys.version,
                "versions": versions, "version_errors": version_errors, "build_commit_requested": COMMIT,
                "platform": args.platform, "seed": args.seed, "sample_steps": steps,
                "source_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                                  for name in source_files if (HERE / name).is_file()},
                "cli": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
                "trial_reset_policy": "fresh native scene reset before every case",
                "time_contract": "Pass counts and wall time are recorded separately; equal simulated duration is not assumed."}
    write_json(out / "run_manifest.json", metadata)
    print(f"Purpose: native mechanism verification; view_mode={args.view_mode}", flush=True)
    if args.view_mode == "none":
        print("Images intentionally disabled. No capture-induced Pause/Add/Update/Unpause calls will be made; no rgb directory is required.", flush=True)
    write_json(out / "summary.json", summarise([], selected, metadata))
    rows = []
    session = None
    fatal_error = None
    try:
        if version_errors:
            raise RuntimeError(f"Existing simulator environment has missing/unreadable package metadata: {version_errors}")
        if args.platform == "CloudRendering" and args.local_executable_path is None:
            executable = args.build_cache_dir / "releases" / BUILD / BUILD
            data_dir = executable.parent / f"{BUILD}_Data"
            if not executable.is_file() or not os.access(executable, os.X_OK) or not data_dir.is_dir():
                raise RuntimeError("Pinned Unity cache unavailable; no build download is allowed in this probe.")
        for case in selected:
            scenes = ([x.strip() for x in args.scenes.split(",") if x.strip()] if args.scenes
                      else config.get("scene_candidates", {}).get(FAMILY_SCENES.get(case.family, case.family), []))
            scenes = list(dict.fromkeys(scenes))
            if not scenes:
                raise ValueError(f"No configured scenes for family {case.family}")
            for scene in scenes[:args.max_scenes]:
                case_out = out / "attempts" / case.case_id / scene
                row = {"case_id": case.case_id, "fact_id": case.fact_id, "family": case.family,
                       "scene": scene, "status": "not_started",
                       "result_path": (case_out / "result.json").relative_to(out).as_posix()}
                ctx = None
                started = time.monotonic()
                try:
                    if session is None:
                        session = ControllerSession(scene=scene, platform=args.platform,
                            width=config.get("width", 640), height=config.get("height", 480),
                            render_instance_segmentation=True, build_cache_dir=args.build_cache_dir,
                            local_executable_path=args.local_executable_path, commit_id=COMMIT)
                    else:
                        session.reset(scene)
                    ctx = ProbeContext(session, case_out, sample_steps=steps, seed=args.seed,
                                       view_mode=args.view_mode, family=case.family)
                    write_json(case_out / "inventory.json", inventory(session.snapshot()))
                    ctx.capture("scene_initial")
                    result = case.run(ctx)
                    if not isinstance(result, dict) or result.get("status") not in {
                            "observed_supported", "observed_counterexample", "inconclusive"}:
                        raise ValueError("Probe result must explicitly state an observation status")
                    row["status"] = result["status"]
                    row["observation"] = result
                except ObservationCaptureFailure as exc:
                    row.update(status="inconclusive", error=str(exc),
                               stopped_at="capture_failure", remaining_events_skipped=True)
                except ProbeUnavailable as exc:
                    row.update(status="setup_unavailable", error=str(exc))
                except ActionFailure as exc:
                    row.update(status="action_failed", error=str(exc), failed_action=exc.result.record,
                               note="A failed native action is not a successful-trigger counterexample.")
                except Exception as exc:
                    row.update(status="probe_error", error=f"{type(exc).__name__}: {exc}",
                               traceback=traceback.format_exc())
                finally:
                    row["elapsed_wall_seconds"] = time.monotonic() - started
                    if ctx is not None:
                        try:
                            # A failed observer must not create another fake
                            # picture request during error cleanup.
                            observer = ctx.evidence_cameras
                            try:
                                ctx.capture("attempt_final", image=not (
                                    observer.disabled or observer.contaminated or observer.unhealthy
                                    or row.get("stopped_at") == "capture_failure"))
                            except ObservationCaptureFailure as exc:
                                row["final_capture_error"] = str(exc)
                            ctx.flush()
                            row["checks"] = ctx.checks
                            row["role_bindings"] = ctx.roles
                            row["capture_count"] = len(ctx.captures)
                            row["image_capture_points_requested"] = sum(
                                c.get("image_requested") is True for c in ctx.captures)
                            row["metadata_only_records"] = sum(
                                c.get("image_requested") is False for c in ctx.captures)
                            row["capture_errors"] = [c["capture_error"] for c in ctx.captures if "capture_error" in c]
                            row["view_mode"] = args.view_mode
                            row["preview_errors"] = [c["preview_error"] for c in ctx.captures if "preview_error" in c]
                            row["image_view_count"] = sum(len(c["view_frames"]) if "view_frames" in c else
                                                          int(bool(c.get("rgb_path"))) for c in ctx.captures)
                            row["visual_capture_status"] = ("not_requested" if args.view_mode == "none" else
                                "preview_incomplete" if args.view_mode == "passive" and row["preview_errors"] else
                                "needs_review" if not row["capture_errors"] else "capture_incomplete")
                            if ctx.evidence_cameras.contaminated or ctx.evidence_cameras.unhealthy:
                                row["native_observation_status"] = row["status"]
                                row["status"] = "inconclusive"
                                row["native_measurement_valid"] = False
                                row["observation_invalid_reason"] = "camera_intervention_changed_state_or_failed_to_restore_physics"
                        except Exception as exc:
                            row["final_capture_error"] = f"{type(exc).__name__}: {exc}"
                    write_json(case_out / "result.json", row)
                    # Full native trajectories live once in result.json and
                    # snapshots/. Keep the rolling summary small and readable.
                    rows.append({k: value for k, value in row.items() if k not in {"observation", "traceback"}})
                    write_json(out / "summary.json", summarise(rows, selected, metadata))
                    print(f"{case.case_id} {scene}: {row['status']} ({row['elapsed_wall_seconds']:.1f}s)", flush=True)
                    if row.get("error"):
                        print(f"  STOP: {row['error']}", flush=True)
                    for check in row.get("checks", []):
                        values = log_check_values(check.get("detail"))
                        print(f"  CHECK {'PASS' if check.get('passed') else 'FAIL'}: {check['name']}"
                              + (f" | {json.dumps(values, ensure_ascii=False)}" if values else ""), flush=True)
                    if (case.fact_id in {"F9", "F11"} or (ctx is not None and (
                            ctx.evidence_cameras.unhealthy or ctx.evidence_cameras.contaminated))) and session is not None:
                        # These probes manipulate auto-simulation. A fresh
                        # process prevents an unsupported unpause/reset path
                        # from contaminating subsequent experiments.
                        session.stop()
                        session = None
    except Exception as exc:
        fatal_error = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    finally:
        if session is not None:
            try:
                session.stop()
            except Exception as exc:
                write_json(out / "controller_stop_error.json", {"error": str(exc)})
    result = summarise(rows, selected, metadata)
    result["execution_completed"] = fatal_error is None
    result["fatal_error"] = fatal_error
    if args.suite == "rechecks":
        from mechanism_rechecks import comparison_summary
        comparisons = comparison_summary(rows)
        result["recheck_comparisons"] = comparisons
        write_json(out / "recheck_comparisons.json", comparisons)
        for group, comparison in comparisons["groups"].items():
            print(f"{group}: all_attempted={comparison['all_attempted']}, "
                  f"whole_pattern_supported={comparison['whole_pattern_supported']}", flush=True)
    write_json(out / "summary.json", result)
    print(json.dumps({"output": str(out), "execution_completed": result["execution_completed"],
                      "status_counts": result["status_counts"], "fatal_error": fatal_error,
                      "capture_failure_attempts": result["capture_failure_attempts"],
                      "invalid_native_measurements": result["invalid_native_measurements"]}, indent=2), flush=True)
    if result["has_capture_or_measurement_failure"]:
        print("ERROR: Image capture or native measurement failed. Logs were preserved; "
              "this is not a complete usable evidence batch.", flush=True)
    return 2 if (fatal_error or any(r["status"] == "probe_error" for r in rows)
                 or result["has_capture_or_measurement_failure"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
