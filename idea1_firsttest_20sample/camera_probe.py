"""Three-scene camera calibration probe; this never generates benchmark samples."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

from interactions import Interactions
from runtime import ControllerSession, StepResult


CASES = [
    ("FloorPlan5", "CoffeeMachine"),
    ("FloorPlan201", "Laptop"),
    ("FloorPlan9", "Microwave"),
]
BUILD = "thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917"


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return jsonable(value.tolist())
    return repr(value)


def bbox_for(event: Any, metadata: dict[str, Any], object_id: str) -> dict[str, float] | None:
    return Interactions._rendered_target_bbox(
        StepResult(event=event, metadata=metadata, record={}), object_id
    )


def relevant_snapshot(metadata: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    agent = metadata.get("agent", {})
    return {
        "sceneName": metadata.get("sceneName"),
        "agent": {key: agent.get(key) for key in ("position", "rotation", "cameraHorizon", "isStanding")},
        "cameraPosition": metadata.get("cameraPosition"),
        "target": target,
        "lastActionSuccess": metadata.get("lastActionSuccess"),
        "errorMessage": metadata.get("errorMessage"),
    }


def require_success(result: Any, label: str) -> None:
    if result.record.get("lastActionSuccess") is not True:
        raise RuntimeError(
            f"{label} failed: {result.record.get('errorMessage') or 'lastActionSuccess was not true'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path,
                        default=Path(os.environ.get("DATA_ROOT", "/root/autodl-tmp/idea1_firsttest_20sample"))
                        / "camera_probe")
    parser.add_argument("--build-cache-dir", type=Path,
                        default=Path(os.environ.get("DATA_ROOT", "/root/autodl-tmp/idea1_firsttest_20sample"))
                        / "unity_cache")
    parser.add_argument("--local-executable-path", type=Path, default=None)
    parser.add_argument("--platform", choices=("Linux64", "CloudRendering"),
                        default=os.environ.get("THOR_PLATFORM", "CloudRendering"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source_root = Path(__file__).resolve().parent
    source_sha256 = {
        name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
        for name in ("runtime.py", "interactions.py", "camera_probe.py")
    }
    case_manifest: list[dict[str, Any]] = []
    started = time.monotonic()
    session = None
    try:
        if args.platform == "CloudRendering":
            cache_root = args.build_cache_dir
            expected = cache_root / "releases" / BUILD / BUILD if cache_root else None
            data_dir = expected.parent / f"{BUILD}_Data" if expected is not None else None
            if (expected is None or not expected.is_file() or not os.access(expected, os.X_OK)
                    or data_dir is None or not data_dir.is_dir() or not any(data_dir.iterdir())):
                raise RuntimeError(
                    "CloudRendering executable/Data cache is missing or invalid; run linux_server_operation/13_thor_build.py "
                    "--check-cache first and pass --build-cache-dir DATA_ROOT/unity_cache."
                )
        session = ControllerSession(
            scene=CASES[0][0], platform=args.platform, width=320, height=240, quality="Low",
            render_instance_segmentation=True, render_depth=False,
            build_cache_dir=args.build_cache_dir,
            local_executable_path=args.local_executable_path,
        )
        interactions = Interactions(session)
        for case_index, (scene, object_type) in enumerate(CASES):
            case_started = time.monotonic()
            case_dir = args.out / f"{scene}_{object_type}"
            case_dir.mkdir(parents=True, exist_ok=True)
            item: dict[str, Any] = {
                "scene": scene, "objectType": object_type,
                "status": "failed", "elapsed_seconds": None,
            }
            try:
                if case_index:
                    reset_result = session.reset(scene)
                    require_success(reset_result, f"reset({scene})")
                target = session.find_object(object_type)
                if target is None:
                    raise RuntimeError(f"{scene}: no {object_type} target in metadata")
                object_id = target["objectId"]
                item["objectId"] = object_id
                if object_type in {"Laptop", "Microwave"} and target.get("openable") is True and target.get("isOpen") is not True:
                    interactions.set_open(object_id, True)
                    target = interactions.obj(object_id)

                native_pose = None
                try:
                    poses_result = session.step("GetInteractablePoses", objectId=object_id)
                    require_success(poses_result, f"GetInteractablePoses({object_id})")
                    poses = poses_result.metadata.get("actionReturn") or []
                    native_pose = poses[0] if poses else None
                    item["native_pose_count"] = len(poses)
                except Exception as exc:
                    item["native_pose_error"] = f"{type(exc).__name__}: {exc}"

                view_position = (native_pose or {}).get("position")
                if not isinstance(view_position, dict) and native_pose and all(
                        key in native_pose for key in ("x", "y", "z")):
                    view_position = {key: native_pose[key] for key in ("x", "y", "z")}
                before_result = None
                if native_pose and view_position:
                    try:
                        pose_kwargs = {"position": view_position}
                        pose_kwargs.update({key: native_pose[key] for key in ("horizon", "standing")
                                            if key in native_pose})
                        if "rotation" in native_pose:
                            rotation = native_pose["rotation"]
                            pose_kwargs["rotation"] = (
                                {"x": 0.0, "y": float(rotation), "z": 0.0}
                                if isinstance(rotation, (int, float)) else rotation
                            )
                        before_result = session.step("TeleportFull", **pose_kwargs)
                        require_success(before_result, f"native TeleportFull({object_id})")
                    except Exception as exc:
                        item["native_teleport_error"] = f"{type(exc).__name__}: {exc}"
                if before_result is None or before_result.record.get("lastActionSuccess") is not True:
                    before_result = session.step("Pass")
                    require_success(before_result, f"before-frame Pass({object_id})")
                before_files = session.save_pngs(before_result, case_dir, stem="before_native_pose")
                before_meta = session.snapshot(before_result)
                before_target = next((entry for entry in before_meta.get("objects", [])
                                      if entry.get("objectId") == object_id), target)
                item["before"] = {
                    "rgb": before_files["rgb"], "instance_mask": before_files["instance"],
                    "bbox": bbox_for(before_result.event, before_meta, object_id),
                    "snapshot": relevant_snapshot(before_meta, before_target),
                }

                # Record the geometry-only correction independently from the
                # actual Interactions.look validation path below.
                after_result = None
                try:
                    after_result = session.face_object(before_target, position=view_position)
                    after_files = session.save_pngs(after_result, case_dir, stem="after_calibrated")
                    after_meta = session.snapshot(after_result)
                    after_target = next((entry for entry in after_meta.get("objects", [])
                                         if entry.get("objectId") == object_id), before_target)
                    item["after_calibrated"] = {
                        "rgb": after_files["rgb"], "instance_mask": after_files["instance"],
                        "bbox": bbox_for(after_result.event, after_meta, object_id),
                        "snapshot": relevant_snapshot(after_meta, after_target),
                        "teleport": after_result.record,
                    }
                except Exception as exc:
                    item["calibration_error"] = f"{type(exc).__name__}: {exc}"

                validation_result = None
                try:
                    validation_result = interactions.look(object_id)
                    validated_bbox = interactions._rendered_target_bbox(validation_result, object_id)
                    validation_pass = validated_bbox is not None
                    if not validation_pass:
                        item["look_error"] = "look returned without a qualifying rendered bbox"
                except Exception as exc:
                    validation_pass = False
                    item["look_error"] = f"{type(exc).__name__}: {exc}"
                validation_event = (validation_result.event if validation_result is not None
                                    else getattr(session.controller, "last_event", None))
                validation_meta = (session.snapshot(validation_result) if validation_result is not None
                                   else session.snapshot())
                validation_record = (validation_result.record if validation_result is not None
                                     else (session.records[-1] if session.records else {}))
                validation_snapshot_target = next(
                    (entry for entry in validation_meta.get("objects", [])
                     if entry.get("objectId") == object_id), before_target)
                validated_bbox = (interactions._rendered_target_bbox(validation_result, object_id)
                                  if validation_result is not None else None)
                validated = None
                if validation_event is not None and getattr(validation_event, "frame", None) is not None:
                    validated_result = StepResult(validation_event, validation_meta, validation_record)
                    validation_files = session.save_pngs(validated_result, case_dir, stem="validated_look")
                    validated = {
                        "rgb": validation_files["rgb"], "instance_mask": validation_files["instance"],
                        "bbox": validated_bbox,
                        "snapshot": relevant_snapshot(validation_meta, validation_snapshot_target),
                        "action": validation_record,
                    }
                item["validated_look"] = {"pass": validation_pass, **(validated or {}),
                                           "error": item.get("look_error")}
                item["status"] = "passed" if validation_pass else "failed"
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                item["elapsed_seconds"] = round(time.monotonic() - case_started, 3)
                if session is not None:
                    try:
                        session.export_action_log(case_dir / "action_log.json")
                    except Exception as exc:
                        item["action_log_error"] = f"{type(exc).__name__}: {exc}"
                (case_dir / "metadata.json").write_text(
                    json.dumps(jsonable(item), ensure_ascii=False, indent=2), encoding="utf-8")
                case_manifest.append(item)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        for scene, object_type in CASES[len(case_manifest):]:
            case_dir = args.out / f"{scene}_{object_type}"
            case_dir.mkdir(parents=True, exist_ok=True)
            item = {"scene": scene, "objectType": object_type, "status": "failed",
                    "stage": "controller_init_or_probe", "error": error,
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
            (case_dir / "metadata.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            case_manifest.append(item)
    finally:
        if session is not None:
            try:
                session.stop()
            except Exception:
                pass

    total_elapsed = round(time.monotonic() - started, 3)
    manifest = {"status": "passed" if all(row.get("status") == "passed" for row in case_manifest)
                and len(case_manifest) == len(CASES) else "failed",
                "elapsed_seconds": total_elapsed, "source_sha256": source_sha256,
                "cases": case_manifest}
    (args.out / "manifest.json").write_text(
        json.dumps(jsonable(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.out), "status": manifest["status"],
                      "elapsed_seconds": total_elapsed,
                      "cases": len(case_manifest)}, ensure_ascii=False))
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
