"""Private scenario checkpoints for native hard-group verification.

Checkpoint records are audit-only. They are written beside the attempt trace and
are not intended to be copied into model input or hidden Gold.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


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


class ScenarioCheckpointBook:
    """Persist planned, started, and completed native state checkpoints."""

    def __init__(self, ctx: Any, *, scenario: str, variant: int,
                 plan: Iterable[Mapping[str, Any]]) -> None:
        self.ctx = ctx
        self.scenario = str(scenario)
        self.variant = int(variant)
        self.path = Path(ctx.out) / "scenario_checkpoints.json"
        self.first_error: str | None = None
        self.active_id: str | None = None
        self.records = [
            {"checkpoint_id": str(item["checkpoint_id"]), "label": str(item.get("label", item["checkpoint_id"])),
             "expected": _jsonable(item.get("expected", {})), "status": "planned"}
            for item in plan
        ]
        self._by_id = {row["checkpoint_id"]: row for row in self.records}
        if len(self._by_id) != len(self.records):
            raise ValueError("checkpoint ids must be unique")
        self._persist()

    def _role_snapshot(self) -> dict[str, Any]:
        metadata = self.ctx.session.snapshot()
        by_id = {str(row.get("objectId")): row for row in metadata.get("objects", [])
                 if isinstance(row, Mapping)}
        fields = ("objectId", "objectType", "position", "isCooked", "temperature", "isOpen",
                  "isToggled", "isPickedUp", "parentReceptacles", "receptacleObjectIds", "distance")
        roles = {}
        for alias, object_id in sorted(getattr(self.ctx, "roles", {}).items()):
            row = by_id.get(str(object_id))
            if row is not None:
                roles[str(alias)] = {key: _jsonable(row.get(key)) for key in fields if key in row}
        return {"agent": _jsonable(metadata.get("agent")),
                "inventory": _jsonable(metadata.get("inventoryObjects", [])), "roles": roles}

    def _receipt_index(self) -> int:
        return len(getattr(self.ctx.session, "records", []))

    def _native_receipts(self, start: int, end: int | None = None) -> list[dict[str, Any]]:
        rows = getattr(self.ctx.session, "records", [])[start:end]
        keys = ("index", "action", "kwargs", "lastActionSuccess", "errorMessage", "time_utc", "wall_time")
        return [{key: _jsonable(row.get(key)) for key in keys if key in row} for row in rows]

    def _capture(self, label: str) -> dict[str, Any]:
        trace = getattr(self.ctx, "trace", None)
        if trace is None:
            return {"status": "trace_unavailable", "label": label}
        trace.capture_current(label)
        events = trace.events
        event = events[-1] if events else {}
        return {"status": event.get("frame_status", "unknown"),
                "label": label, "global_step": event.get("global_step"),
                "action_index": event.get("action_index"),
                "frames": _jsonable(event.get("frames", [])),
                "record_kind": event.get("record_kind")}

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": "scenario-checkpoints/v1", "scenario": self.scenario,
                   "variant": self.variant, "first_error": self.first_error,
                   "checkpoints": self.records}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        # Public to the exporter, but remains audit-only unless explicitly
        # selected by that exporter.
        review = []
        for row in self.records:
            begin, finish = row.get("begin", {}), row.get("finish", {})
            evidence = []
            for item in [begin.get("capture"), finish.get("capture"), finish.get("frame_ref"),
                         *finish.get("observations", []), row.get("failure_capture")]:
                if item and item.get("global_step") is not None:
                    evidence.append({**item, "label": item.get("label", row["label"] +
                                     (f" / Pass {item['pass']}" if "pass" in item else " / 原生事件返回"))})
            review.append({**_jsonable(row), "id": row["checkpoint_id"], "title": row["label"],
                "status": "not_executed" if row["status"] == "planned" else row["status"],
                "public": row.get("public", row["checkpoint_id"] != "private_calibration"),
                "facts": [{**f, "fact": f["name"]} for f in row.get("facts", [])],
                "evidence": evidence, "state": finish.get("snapshot", row.get("failure_snapshot")),
                "native_receipts": finish.get("native_receipts", row.get("failure_receipts", [])),
                "error": row.get("failure"), "visual_review": "pending_human_review"})
        self.ctx.review_checkpoints = review

    def begin(self, checkpoint_id: str) -> dict[str, Any]:
        row = self._by_id[checkpoint_id]
        if row.get("status") in {"passed", "failed"}:
            raise ValueError(f"checkpoint already finished: {checkpoint_id}")
        if self.active_id is not None:
            raise ValueError(f"checkpoint {self.active_id} is still active")
        self.active_id = checkpoint_id
        row["status"] = "running"
        row["public"] = bool(getattr(self.ctx, "public_phase", False))
        row["begin"] = {"snapshot": self._role_snapshot(), "receipt_index": self._receipt_index(),
                        "capture": self._capture(f"scenario checkpoint begin: {row['label']}")}
        self._persist()
        return row

    def finish(self, facts: Iterable[Mapping[str, Any]], *, snapshot: Mapping[str, Any] | None = None,
               frame_action_index: int | None = None,
               observation_refs: Iterable[Mapping[str, Any]] | None = None,
               capture: bool = True) -> dict[str, Any]:
        if self.active_id is None:
            raise ValueError("finish called without an active checkpoint")
        row = self._by_id[self.active_id]
        normalized = [{"name": str(fact["name"]), "expected": _jsonable(fact.get("expected")),
                       "actual": _jsonable(fact.get("actual")),
                       "passed": _jsonable(fact.get("expected")) == _jsonable(fact.get("actual"))}
                      for fact in facts]
        passed = all(fact["passed"] for fact in normalized)
        end_index = self._receipt_index()
        finish_capture = (self._capture(f"scenario checkpoint finish: {row['label']}")
                          if capture else {"status": "frame_reference_only", "label": row["label"]})
        frame_ref = None
        if frame_action_index is not None:
            trace = getattr(self.ctx, "trace", None)
            if trace is not None:
                event = next((item for item in trace.events
                              if item.get("action_index") == frame_action_index), None)
                if event is not None:
                    frame_ref = {"action_index": frame_action_index, "global_step": event.get("global_step"),
                                 "frames": _jsonable(event.get("frames", [])),
                                 "frame_status": event.get("frame_status")}
        trace = getattr(self.ctx, "trace", None)
        trace_events = trace.events if trace is not None else []
        observations = []
        for raw in observation_refs or []:
            ref = _jsonable(raw)
            action_index = ref.get("action_index") if isinstance(ref, Mapping) else None
            event = next((item for item in trace_events if item.get("action_index") == action_index), None)
            if event is not None:
                ref["global_step"] = event.get("global_step")
                ref["frame_status"] = event.get("frame_status")
                ref["frames"] = _jsonable(event.get("frames", []))
            observations.append(ref)
        evidence = [row.get("begin", {}).get("capture"), finish_capture, frame_ref, *observations]
        usable = [e for e in evidence if e and e.get("global_step") is not None]
        media_ok = bool(usable) and all(
            e.get("frame_status", e.get("status")) == "captured"
            and any(f.get("view_id") == "agent" and f.get("path")
                    and (Path(trace.directory) / f["path"]).is_file()
                    for f in e.get("frames", [])) for e in usable) if trace is not None else False
        if frame_action_index is not None:
            media_ok = media_ok and frame_ref is not None
        normalized.append({"name": "检查点关联真实图片且文件存在", "expected": True,
                           "actual": media_ok, "passed": media_ok})
        passed = all(fact["passed"] for fact in normalized)
        row.update({"status": "passed" if passed else "failed", "facts": normalized,
                    "finish": {"snapshot": _jsonable(snapshot) if snapshot is not None else self._role_snapshot(),
                               "receipt_index": end_index, "native_receipts": self._native_receipts(
                                   row["begin"]["receipt_index"], end_index),
                               "capture": finish_capture, "frame_ref": frame_ref,
                                "observations": observations}})
        if not passed and self.first_error is None:
            failures = [f"{fact['name']}: expected {fact['expected']!r}, actual {fact['actual']!r}"
                        for fact in normalized if not fact["passed"]]
            self.first_error = f"Checkpoint {self.active_id} failed: " + "; ".join(failures)
        self.active_id = None
        self._persist()
        return row

    def fail(self, error: Any) -> None:
        if self.first_error is None:
            self.first_error = str(error)
        if self.active_id is not None:
            row = self._by_id[self.active_id]
            row["status"] = "failed"
            row["failure"] = str(error)
            row["failure_snapshot"] = self._role_snapshot()
            row["failure_receipts"] = self._native_receipts(row.get("begin", {}).get("receipt_index", 0))
            row["failure_capture"] = self._capture(f"scenario checkpoint failed: {row['label']}")
            self.active_id = None
        self._persist()

