"""Disk-backed, exact-pixel audit trace for native simulator events.

The recorder is intentionally passive: it consumes arrays already present on a
StepResult and never asks AI2-THOR for another observation.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from runtime import StepResult


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    return repr(value)


class FullStepTrace:
    """Observe every session step, saving full metadata and compact frame indexes."""

    def __init__(self, session: Any, directory: str | Path) -> None:
        self.session = session
        self.directory = Path(directory)
        self.frames_dir = self.directory / "frames"
        self.metadata_dir = self.directory / "metadata"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.directory / "steps.jsonl"
        self._event_file = self.events_path.open("a", encoding="utf-8")
        self._global_step = 0
        self._reset_index = 0
        self._phase_id = 0
        self._phase = {"label": "unclassified", "public": False, "kind": "history"}
        self._segment = 0
        self._has_seen_step = False
        self._runs: list[dict[str, Any]] = []
        self._last_run_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._capture_groups: list[dict[str, Any]] = []
        self._last_capture_group: dict[str, Any] | None = None
        self._boundaries: list[dict[str, Any]] = []
        self._cameras: list[dict[str, Any]] = []
        self._role_ids: dict[str, Any] = {}
        self._finished: dict[str, Any] | None = None
        self.session.add_step_observer(self._observe)

    @property
    def events(self) -> list[dict[str, Any]]:
        """Read the lightweight event ledger from disk without retaining it in RAM."""
        if not self._event_file.closed:
            self._event_file.flush()
        if not self.events_path.exists():
            return []
        with self.events_path.open("r", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]

    @property
    def runs(self) -> list[dict[str, Any]]:
        return [dict(run) for run in self._runs]

    @property
    def auditor_frames(self) -> list[dict[str, Any]]:
        """All frame runs, including private phases and detailed phase labels."""
        return self.runs

    def set_phase(self, label: str, public: bool = False, kind: str = "history") -> None:
        if kind not in {"history", "target", "setup", "calibration", "observation", "other"}:
            raise ValueError(f"unsupported phase kind: {kind!r}")
        self._phase_id += 1
        self._phase = {"label": str(label), "public": bool(public), "kind": kind}
        self._segment += 1

    def mark(self, label: str, kind: str = "boundary") -> dict[str, Any]:
        self._segment += 1
        boundary = {
            "label": str(label), "kind": str(kind), "global_step": self._global_step - 1,
            "reset_index": self._reset_index, "phase_id": self._phase_id,
            "phase_label": self._phase["label"],
        }
        self._boundaries.append(boundary)
        return dict(boundary)

    def set_cameras(self, cameras: list[dict[str, Any]]) -> None:
        normalized = []
        for camera in cameras:
            if not isinstance(camera, Mapping):
                raise TypeError("each camera must be a mapping")
            normalized.append({
                "camera_id": int(camera["camera_id"]),
                "view_id": str(camera["view_id"]),
                "purpose": str(camera["purpose"]),
            })
        self._cameras = normalized

    def set_role_ids(self, mapping: Mapping[str, Any]) -> None:
        self._role_ids = {str(key): _jsonable(value) for key, value in mapping.items()}

    def capture_current(self, label: str = "capture_current") -> dict[str, Any]:
        """Record the already-current event without issuing a native command."""
        event = getattr(self.session.controller, "last_event", None)
        metadata = self.session.snapshot()
        record = dict(self.session.records[-1]) if self.session.records else {
            "index": 0, "action": "Initialize", "kwargs": {},
            "lastActionSuccess": metadata.get("lastActionSuccess"),
            "errorMessage": metadata.get("errorMessage", ""),
        }
        record["capture_label"] = str(label)
        record["record_kind"] = "checkpoint"
        self._observe(StepResult(event, metadata, record))
        return dict(self._last_event)

    def _write_metadata(self, step_number: int, metadata: Mapping[str, Any]) -> str:
        relative = Path("metadata") / f"step_{step_number:08d}.json.gz"
        path = self.directory / relative
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(_jsonable(metadata), stream, ensure_ascii=False, separators=(",", ":"))
        return relative.as_posix()

    @staticmethod
    def _image_info(array: Any) -> tuple[str, int, int, str, bytes]:
        from PIL import Image

        image = Image.fromarray(array)
        mode = image.mode
        width, height = image.size
        pixels = image.tobytes()
        digest = hashlib.sha256(
            f"{width}x{height}:{mode}:".encode("ascii") + pixels
        ).hexdigest()
        return digest, width, height, mode, pixels

    def _save_frame(self, array: Any, view_id: str) -> dict[str, Any]:
        from PIL import Image

        digest, width, height, mode, _ = self._image_info(array)
        relative = Path("frames") / f"{digest}.png"
        path = self.directory / relative
        if not path.exists():
            Image.fromarray(array).save(path, format="PNG")
        return {"view_id": view_id, "path": relative.as_posix(), "pixel_sha256": digest,
                "width": width, "height": height, "mode": mode}

    @staticmethod
    def _third_party_frames(event: Any) -> list[Any]:
        frames = getattr(event, "third_party_camera_frames", None)
        if frames is None:
            frames = getattr(event, "thirdPartyCameraFrames", None)
        return list(frames) if frames is not None else []

    def _get_camera_frame(self, event: Any, camera_id: int) -> Any | None:
        frames = self._third_party_frames(event)
        metadata_rows = getattr(event, "metadata", {}).get("thirdPartyCameras", [])
        for index, row in enumerate(metadata_rows):
            row_id = row.get("thirdPartyCameraId", row.get("cameraId", index))
            if row_id == camera_id and index < len(frames):
                return frames[index]
        return frames[camera_id] if 0 <= camera_id < len(frames) else None

    def _append_run(self, frame: dict[str, Any], step_number: int) -> None:
        key = (self._reset_index, self._phase_id, self._segment, frame["view_id"])
        current = self._last_run_by_key.get(key)
        if (current is not None and current["pixel_sha256"] == frame["pixel_sha256"]
                and current["end_step"] == step_number - 1):
            current["run_length"] += 1
            current["duplicate_count"] += 1
            current["end_step"] = step_number
            current["step_numbers"].append(step_number)
            current["step_frame_map"].append({"global_step": step_number,
                                               "path": frame["path"],
                                               "pixel_sha256": frame["pixel_sha256"]})
            return
        run = {
            **frame, "phase_id": self._phase_id, "phase_label": self._phase["label"],
            "phase_public": self._phase["public"], "phase_kind": self._phase["kind"],
            "reset_index": self._reset_index, "capture_group_index": step_number,
            "start_step": step_number, "end_step": step_number,
            "run_length": 1, "duplicate_count": 0,
            "step_numbers": [step_number],
            "step_frame_map": [{"global_step": step_number, "path": frame["path"],
                                "pixel_sha256": frame["pixel_sha256"]}],
        }
        self._runs.append(run)
        self._last_run_by_key[key] = run

    def _append_capture_group(self, frames: list[dict[str, Any]], step_number: int,
                              frame_status: str = "captured") -> None:
        """RLE complete synchronized view sets; never collapse per-view independently."""
        views = []
        for frame in frames:
            view_id = str(frame.get("view_id", "unknown"))
            camera = next((row for row in self._cameras if row["view_id"] == view_id), {})
            views.append({**frame,
                          "view_role": "agent_first_person" if view_id == "agent" else "third_party",
                          "purpose": frame.get("purpose", "model_evidence" if view_id == "agent" else camera.get("purpose", "unspecified"))})
        signature = [(v.get("view_id"), v.get("status", "captured"), v.get("pixel_sha256")) for v in views]
        previous = self._last_capture_group
        same_context = bool(previous and previous["reset_index"] == self._reset_index
            and previous["phase_id"] == self._phase_id and previous["segment"] == self._segment
            and previous["end_step"] == step_number - 1)
        if same_context and previous.get("_signature") == signature:
            previous["run_length"] += 1
            previous["duplicate_count"] += 1
            previous["end_step"] = step_number
            previous["step_numbers"].append(step_number)
            previous["step_group_map"].append({"global_step": step_number, "views": [
                {k: v.get(k) for k in ("view_id", "view_role", "purpose", "path", "pixel_sha256", "status")}
                for v in views]})
            return
        group = {"capture_group_index": step_number, "global_step": step_number,
            "reset_index": self._reset_index, "phase_id": self._phase_id,
            "phase_label": self._phase["label"], "phase_public": self._phase["public"],
            "phase_kind": self._phase["kind"], "segment": self._segment,
            "frame_status": (frame_status if frame_status != "captured" else
                             "camera_frame_missing" if any(v.get("status") == "camera_frame_missing" for v in views)
                             else "captured"),
            "views": views, "start_step": step_number, "end_step": step_number,
            "run_length": 1, "duplicate_count": 0, "step_numbers": [step_number],
            "step_group_map": [{"global_step": step_number, "views": [
                {k: v.get(k) for k in ("view_id", "view_role", "purpose", "path", "pixel_sha256", "status")}
                for v in views]}], "_signature": signature}
        self._capture_groups.append(group)
        self._last_capture_group = group

    def _observe(self, result: StepResult) -> None:
        if self._finished is not None:
            return
        if (result.record.get("record_kind") != "checkpoint"
                and result.record.get("action") in {"Initialize", "Reset"} and self._has_seen_step):
            self._reset_index += 1
            self._segment += 1
            self._last_run_by_key.clear()
            self._phase_id += 1
            self._phase = {"label": "reset", "public": False, "kind": "setup"}
        step_number = self._global_step
        self._global_step += 1
        event = result.event
        metadata_rel = self._write_metadata(step_number, result.metadata)
        frames: list[dict[str, Any]] = []
        status = "captured"
        if not result.new_event_received:
            status = "stale_exception_event_not_new_picture"
        elif event is None:
            status = "event_missing"
        else:
            agent = getattr(event, "frame", None)
            if agent is None:
                status = "agent_rgb_missing"
                frames.append({"view_id": "agent", "view_role": "agent_first_person",
                               "purpose": "model_evidence", "status": "agent_rgb_missing"})
            else:
                frame = self._save_frame(agent, "agent")
                frames.append(frame)
                self._append_run(frame, step_number)
            for camera in self._cameras:
                array = self._get_camera_frame(event, camera["camera_id"])
                if array is None:
                    frames.append({"view_id": camera["view_id"], "camera_id": camera["camera_id"],
                                   "purpose": camera["purpose"], "status": "camera_frame_missing"})
                    continue
                frame = self._save_frame(array, camera["view_id"])
                frame.update({"camera_id": camera["camera_id"], "purpose": camera["purpose"]})
                frames.append(frame)
                self._append_run(frame, step_number)
            self._append_capture_group(frames, step_number, status)
        if event is None or not result.new_event_received:
            missing_views = [{"view_id": "agent", "status": status}]
            missing_views.extend({"view_id": camera["view_id"], "camera_id": camera["camera_id"],
                                  "purpose": camera["purpose"], "status": status}
                                 for camera in self._cameras)
            self._append_capture_group(missing_views, step_number, status)
        if status == "captured" and any(frame.get("status") == "camera_frame_missing"
                                         for frame in frames):
            status = "camera_frame_missing"
        entry = {
            "global_step": step_number, "reset_index": self._reset_index,
            "action_index": result.record.get("index"),
            "record_kind": result.record.get("record_kind", "native"),
            "action": result.record.get("action"),
            "action_kwargs": result.record.get("kwargs", {}),
            "capture_label": result.record.get("capture_label"),
            "time_utc": result.record.get("time_utc"),
            "wall_time": result.record.get("wall_time"),
            "phase_id": self._phase_id, "phase_label": self._phase["label"],
            "phase_public": self._phase["public"], "phase_kind": self._phase["kind"],
            "frames": frames, "frame_status": status,
            "new_event_received": bool(result.new_event_received),
            "native_exception": result.native_error,
            "lastActionSuccess": result.record.get("lastActionSuccess"),
            "errorMessage": result.record.get("errorMessage", ""),
            "metadata_gzip": metadata_rel,
        }
        self._event_file.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._event_file.flush()
        self._last_event = entry
        self._has_seen_step = True

    def _public_runs(self) -> list[dict[str, Any]]:
        output = []
        phase_order: dict[tuple[int, int], int] = {}
        for group in self._capture_groups:
            if not group["phase_public"]:
                continue
            agent = next((view for view in group["views"] if view.get("view_id") == "agent"), None)
            if agent is None or not agent.get("path"):
                continue
            key = (group["reset_index"], group["phase_id"])
            if key not in phase_order:
                phase_order[key] = 1 + sum(1 for prior in phase_order if prior[0] == key[0])
            phase_number = phase_order[key]
            stage = "目标事件" if group["phase_kind"] == "target" else f"历史片段 {phase_number:02d}"
            output.append({
                "path": agent["path"], "stage": stage, "view_id": "agent",
                "view_role": "agent_first_person", "purpose": "model_evidence",
                "pixel_sha256": agent.get("pixel_sha256"),
                "run_length": group["run_length"], "duplicate_count": group["duplicate_count"],
                "start_step": group["start_step"], "end_step": group["end_step"],
                "step_numbers": list(group["step_numbers"]),
                "capture_group_index": group["capture_group_index"],
            })
        return output

    def model_frames(self) -> list[dict[str, Any]]:
        """Public-only, answer-safe frame runs for the model export path."""
        return self._public_runs()

    def finish(self) -> dict[str, Any]:
        if self._finished is not None:
            return dict(self._finished)
        self.session.remove_step_observer(self._observe)
        self._event_file.flush()
        self._event_file.close()
        boundaries_path = self.directory / "boundaries.json"
        boundaries_path.write_text(json.dumps(self._boundaries, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        failures = [event for event in self.events
                    if event["native_exception"] or event["lastActionSuccess"] is False
                    or event["frame_status"] != "captured"
                    or any(frame.get("status") == "camera_frame_missing"
                           for frame in event["frames"])]
        observer_errors = list(getattr(self.session, "observer_errors", []))
        index = {
            "schema_version": 2,
            "steps_path": "steps.jsonl", "boundaries_path": "boundaries.json",
            "frame_directory": "frames", "metadata_directory": "metadata",
            "global_step_count": self._global_step, "reset_count": self._reset_index + 1,
            "native_call_count": sum(e.get("record_kind") == "native" for e in self.events),
            "readonly_checkpoint_count": sum(e.get("record_kind") == "checkpoint" for e in self.events),
            "run_count": len(self._runs), "frame_file_count": len(list(self.frames_dir.glob("*.png"))),
            "capture_group_count": len(self._capture_groups),
            "capture_group_step_count": sum(group["run_length"] for group in self._capture_groups),
            "capture_group_missing_frame_count": sum(group["frame_status"] != "captured"
                                                       for group in self._capture_groups),
            "failure_count": len(failures),
            # Machine-readable capture integrity and visual/semantic review are
            # separate. Even a complete trace still needs visual evidence review.
            "visual_evidence_pending": True,
            "capture_integrity_pass": not failures and not observer_errors,
            "capture_failure_count": len(failures),
            "observer_error_count": len(observer_errors),
            "observer_errors": observer_errors,
            "failures": [{"global_step": item["global_step"], "action": item["action"],
                          "frame_status": item["frame_status"],
                          "native_exception": item["native_exception"],
                          "errorMessage": item["errorMessage"]} for item in failures],
            "cameras": self._cameras, "role_ids": self._role_ids,
            "auditor_runs": self._runs,
            "capture_groups": [{k: v for k, v in group.items() if k != "_signature"} for group in self._capture_groups],
            "model_frames": self._public_runs(),
        }
        (self.directory / "trace_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        self._finished = index
        return dict(index)


__all__ = ["FullStepTrace"]
