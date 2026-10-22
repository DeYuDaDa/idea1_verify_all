"""Private, bounded native-mechanism experiments; no simulator at import time.

Capture reads the current event without moving the camera or advancing physics.
Neither native metadata nor bbox diagnostics certify a model-visible premise.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from interactions import Interactions
from runtime import ControllerSession, StepResult


class ProbeUnavailable(RuntimeError):
    """The required setup/measurement is unavailable; not a mechanism refutation."""


@dataclass(frozen=True)
class ProbeCase:
    case_id: str
    fact_id: str
    family: str
    run: Callable[["ProbeContext"], dict]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(ControllerSession._jsonable(value),
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def position_distance(a: dict, b: dict) -> float:
    return sum((float(a[k]) - float(b[k])) ** 2 for k in ("x", "y", "z")) ** 0.5


class ProbeContext:
    def __init__(self, session: ControllerSession, out: Path, *,
                 sample_steps: Iterable[int] = (0, 1, 4, 12, 36), seed: int = 17):
        self.session = session
        self.ops = Interactions(session, seed=seed)
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.roles: dict[str, str] = {}
        self.checks: list[dict] = []
        self.captures: list[dict] = []
        self._action_segments = [session.records]
        self.sample_steps = tuple(sorted(set(int(n) for n in sample_steps)))
        if not self.sample_steps or self.sample_steps[0] < 0:
            raise ValueError("sample_steps must contain nonnegative integers")
        self.started = time.monotonic()

    def bind(self, alias: str, object_id: str) -> str:
        self.obj(object_id)
        self.roles[alias] = object_id
        return object_id

    def select(self, alias: str, object_type: str, capability=None, exclude=()) -> str:
        excluded = {self.roles.get(str(x), str(x)) for x in exclude}
        caps = [capability] if isinstance(capability, str) else list(capability or [])
        candidates = [o for o in self.session.snapshot().get("objects", [])
                      if o.get("objectType") == object_type and o.get("objectId") not in excluded
                      and all(o.get(cap) is True for cap in caps)]
        self.require(bool(candidates), f"No existing {object_type} with capabilities {caps}; exclude={sorted(excluded)}")
        return self.bind(alias, sorted(candidates, key=lambda o: o["objectId"])[0]["objectId"])

    def obj(self, alias_or_id: str) -> dict:
        oid = self.roles.get(alias_or_id, alias_or_id)
        for obj in self.session.snapshot().get("objects", []):
            if obj.get("objectId") == oid:
                return copy.deepcopy(obj)
        raise ProbeUnavailable(f"Object not present: {alias_or_id}")

    def field(self, alias: str, field: str) -> Any:
        obj = self.obj(alias)
        if field == "temperature":
            return obj.get("temperature", obj.get("ObjectTemperature"))
        return copy.deepcopy(obj.get(field))

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            raise ProbeUnavailable(message)

    def check(self, name: str, condition: bool, detail: Any = None) -> dict:
        row = {"name": name, "passed": bool(condition), "detail": copy.deepcopy(detail)}
        self.checks.append(row)
        return row

    def step(self, action: str, **kwargs) -> StepResult:
        result = self.session.step(action, raise_on_failure=True, **kwargs)
        self.require(result.record.get("lastActionSuccess") is True, f"{action}: missing success confirmation")
        return result

    def move_setup(self, child: str, parent: str):
        child_id, parent_id = self.roles.get(child, child), self.roles.get(parent, parent)
        return self.ops.place_initial(child_id, parent_id)

    def pickup(self, alias: str):
        return self.ops.pickup_event(self.roles.get(alias, alias))

    def put_event(self, child: str, parent: str):
        return self.ops.put_event(self.roles.get(child, child), self.roles.get(parent, parent))

    def toggle(self, alias: str, on: bool):
        return self.ops.set_toggle(self.roles.get(alias, alias), on)

    def capture(self, label: str, image: bool = True) -> dict:
        from frame_evidence import describe_frame
        if self.session.records is not self._action_segments[-1]:
            # ControllerSession.reset assigns a fresh list. Keeping the old list
            # reference preserves setup actions of earlier intervention arms.
            self._action_segments.append(self.session.records)
        metadata = self.session.snapshot()
        index = len(self.captures)
        safe_label = "".join(c if c.isalnum() or c in "_-" else "_" for c in str(label))[:100]
        row = {"label": label, "capture_index": index,
               "action_index": len(self.session.records) - 1,
               "action_segment": len(self._action_segments) - 1,
               "elapsed_wall_seconds": time.monotonic() - self.started,
               "metadata": metadata, "roles": dict(self.roles),
               "raw_simulator_time_fields": {k: metadata[k] for k in
                    ("currentTime", "simulationTime", "time") if k in metadata},
               "native_time_units_verified": False,
               "visual_evidence_review": "not_assessed"}
        if image:
            try:
                event = self.session.controller.last_event
                paths = self.session.save_pngs(StepResult(event, metadata, {}), self.out / "rgb",
                                               stem=f"{index:04d}_{safe_label}", include_instance=False)
                path = Path(paths["rgb"])
                relative = path.relative_to(self.out).as_posix()
                row["rgb_path"] = relative
                row["frame_diagnostics"] = describe_frame(
                    event, metadata, self.roles, stage=label, relative_path=relative,
                    png_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    capture_action_index=row["action_index"])
            except Exception as exc:
                # Keep native mechanism evidence even if preview generation fails.
                row["capture_error"] = f"{type(exc).__name__}: {exc}"
        self.captures.append(row)
        write_json(self.out / "snapshots" / f"{index:04d}_{safe_label}.json", row)
        return row

    def observe(self, steps=None, wall_seconds: float = 0) -> list[dict]:
        requested = self.sample_steps if steps is None else tuple(sorted(set(int(n) for n in steps)))
        if not requested or min(requested) < 0 or wall_seconds < 0:
            raise ValueError("Invalid observation steps/time")
        prefix = f"trajectory_{len(self.captures):04d}"
        rows = []
        start = time.monotonic()
        for n in range(max(requested) + 1):
            if n:
                self.step("Pass")
            if n in requested:
                row = self.capture(f"{prefix}_pass_{n}")
                row["observation_passes"] = n
                row["observation_elapsed_wall_seconds"] = time.monotonic() - start
                rows.append(row)
        # This is a wall-time observation, not an assertion of equal physics time.
        if wall_seconds:
            while time.monotonic() - start < wall_seconds:
                time.sleep(min(0.1, max(0, wall_seconds - (time.monotonic() - start))))
                self.step("Pass")
            row = self.capture(f"{prefix}_wall_window")
            row["observation_elapsed_wall_seconds"] = time.monotonic() - start
            rows.append(row)
        return rows

    def flush(self) -> None:
        if self.session.records is not self._action_segments[-1]:
            self._action_segments.append(self.session.records)
        write_json(self.out / "actions.json", self.session.records)
        write_json(self.out / "actions_by_reset.json", self._action_segments)
        write_json(self.out / "capture_index.json", [
            {k: v for k, v in row.items() if k != "metadata"} for row in self.captures])
        write_json(self.out / "checks.json", self.checks)
