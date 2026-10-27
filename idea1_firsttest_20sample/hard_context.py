"""Stateful native context for the hard-group stories; no simulator on import."""
from __future__ import annotations

import copy
from pathlib import Path

from interactions import Interactions
from mechanism_probe_common import native_temperature
from hard_scenarios import HardConstructionError


class HardContext:
    def __init__(self, session, out_dir, *, seed=17, on_start_history=None, on_phase=None):
        self.session = session
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.ops = Interactions(session, seed=seed)
        self.roles = {}
        self.waypoints = {}
        self.questions = []
        self.checks = []
        self.executed_phases = []
        self.public_declarations = []
        self.initial_metadata = {}
        self.before_target = {}
        self.after_target = {}
        self.target_event = {}
        self.group_spec = None
        self.history_started = False
        self.public_phase = False
        self.on_start_history = on_start_history
        self.on_phase = on_phase
        self.trace = None
        self.case_id = self.group_id = self.family = ""

    def obj(self, alias_or_id):
        oid = self.roles.get(alias_or_id, alias_or_id)
        row = next((o for o in self.session.snapshot().get("objects", [])
                    if o.get("objectId") == oid), None)
        self.require(row is not None, f"Object is not present: {alias_or_id}")
        return copy.deepcopy(row)

    def field(self, alias, predicate):
        obj = self.obj(alias)
        return native_temperature(obj) if predicate in {"temperature", "ObjectTemperature"} else obj.get(predicate)

    def bind(self, alias, object_id):
        self.obj(object_id)
        self.roles[alias] = object_id
        return object_id

    def select(self, alias, object_type, capability=None, exclude=()):
        caps = [capability] if isinstance(capability, str) else list(capability or [])
        excluded = {self.roles.get(v, v) for v in exclude}
        rows = sorted((o for o in self.session.snapshot().get("objects", [])
                       if o.get("objectType") == object_type and o.get("objectId") not in excluded
                       and all(o.get(cap) is True for cap in caps)), key=lambda o: o["objectId"])
        self.require(bool(rows), f"No existing {object_type} with capabilities {caps}")
        return self.bind(alias, rows[0]["objectId"])

    def require(self, condition, message):
        if not condition:
            raise HardConstructionError(message)

    def check(self, name, condition, detail=None):
        row = {"name": name, "passed": bool(condition), "detail": copy.deepcopy(detail)}
        self.checks.append(row)
        return row

    def phase(self, label, public=False, kind="history"):
        if public and not self.history_started:
            raise HardConstructionError("A public phase cannot precede start_history/preflight")
        self.public_phase = bool(public)
        self.executed_phases.append({"label": label, "public": bool(public), "kind": kind,
                                     "action_index_before": len(self.session.records) - 1})
        if self.on_phase:
            self.on_phase(label, public, kind)

    def start_history(self):
        self.require(not self.history_started, "Public history cannot be restarted in the same attempt")
        if self.on_start_history:
            self.on_start_history(self)
        self.history_started = True
        self.initial_metadata = self.session.snapshot()
        self.phase("公开初态与身份", public=True, kind="history")
        if self.trace:
            self.trace.set_role_ids(self.roles)
            self.trace.capture_current("公开初态")

    def step(self, action, **kwargs):
        result = self.session.step(action, raise_on_failure=True, **kwargs)
        self.require(result.record.get("lastActionSuccess") is True,
                     f"Missing native success confirmation for {action}")
        return result

    def move_setup(self, child, parent):
        self.require(not self.history_started, "Setup placement is forbidden inside public history")
        return self.ops.place_initial(self.roles.get(child, child), self.roles.get(parent, parent))

    def capture(self, label, image=True):
        # Adapter used only by native nested setup. Reading the current event
        # adds no Unity action, including for legacy metadata-only checkpoints.
        if self.trace:
            self.trace.mark(label, kind="setup_checkpoint")
            self.trace.capture_current(label)
        return {"label": label, "image_requested": bool(image), "metadata": self.session.snapshot()}
