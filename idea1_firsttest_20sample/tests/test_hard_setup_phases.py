from __future__ import annotations

import tempfile
import unittest
from unittest.mock import Mock

from hard_context import HardContext
from hard_scenarios import HardConstructionError


class FakeSession:
    def __init__(self):
        self.records = []
        self.objects = [
            {"objectId": "child", "parentReceptacles": []},
            {"objectId": "parent", "receptacleObjectIds": []},
        ]

    def snapshot(self):
        return {"objects": self.objects}


class FakeTrace:
    def __init__(self):
        self._phase = {"label": "初始化与原生搭建", "public": False, "kind": "setup"}
        self.phases = []
        self.boundaries = []

    def set_phase(self, label, public=False, kind="history"):
        self._phase = {"label": label, "public": public, "kind": kind}
        self.phases.append(dict(self._phase))

    def mark(self, label, kind="boundary"):
        boundary = {"label": label, "kind": kind, "phase_label": self._phase["label"]}
        self.boundaries.append(boundary)
        return boundary


class HardSetupPhaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.session = FakeSession()
        self.ctx = HardContext(self.session, self.tempdir.name)
        self.ctx.roles.update({"X": "child", "P": "parent"})
        self.ctx.trace = FakeTrace()
        self.ctx.ops.place_initial = Mock()
        self.ctx.ops.settle = Mock(return_value=[])

    def _place_and_verify_both_directions(self, child="child", parent="parent"):
        self.session.objects[0]["parentReceptacles"] = [parent]
        self.session.objects[1]["receptacleObjectIds"] = [child]

    def test_setup_stage_is_recorded_in_context_and_trace(self):
        self.ctx.mark_setup_stage("私有可行性校准")

        self.assertEqual(self.ctx.executed_phases[-1]["label"], "私有可行性校准")
        self.assertFalse(self.ctx.executed_phases[-1]["public"])
        self.assertEqual(self.ctx.trace._phase["label"], "私有可行性校准")
        self.assertEqual(self.ctx.trace.boundaries[-1]["kind"], "setup_stage_begin")

    def test_setup_stage_falls_back_to_trace_without_phase_callback(self):
        self.ctx.on_phase = None

        self.ctx.mark_setup_stage("私有构造")

        self.assertEqual(self.ctx.trace._phase["label"], "私有构造")
        self.assertEqual(self.ctx.executed_phases[-1]["label"], "私有构造")

    def test_oracle_restore_is_forbidden_after_public_history_starts(self):
        self.ctx.history_started = True

        with self.assertRaises(HardConstructionError):
            self.ctx.restore_native_object("X", "P")

        self.ctx.ops.place_initial.assert_not_called()

    def test_restore_passes_only_when_both_native_relation_directions_hold(self):
        self.ctx.ops.place_initial.side_effect = self._place_and_verify_both_directions

        self.ctx.restore_native_object("X", "P")

        self.assertEqual(self.ctx.trace.boundaries[0]["kind"], "restore_begin")
        self.assertEqual(self.ctx.trace.boundaries[1]["kind"], "restore_success")
        self.assertEqual(self.ctx.trace._phase["label"], "初始化与原生搭建")
        self.assertEqual(self.ctx.executed_phases[-1]["label"], "初始化与原生搭建")

    def test_restore_rejects_one_sided_native_relation(self):
        def one_sided(child, parent):
            self.session.objects[0]["parentReceptacles"] = [parent]
            self.session.objects[1]["receptacleObjectIds"] = []

        self.ctx.ops.place_initial.side_effect = one_sided

        with self.assertRaises(HardConstructionError):
            self.ctx.restore_native_object("X", "P")

        self.assertEqual(self.ctx.trace.boundaries[-1]["kind"], "restore_failure")
        self.assertIn("HardConstructionError", self.ctx.trace.boundaries[-1]["label"])
        self.assertEqual(self.ctx.trace._phase["label"], "初始化与原生搭建")

    def test_native_restore_exception_keeps_failure_marker_and_restores_private_phase(self):
        self.ctx.mark_setup_stage("端点校准")
        self.ctx.ops.place_initial.side_effect = RuntimeError("native placement failed")

        with self.assertRaisesRegex(RuntimeError, "native placement failed"):
            self.ctx.restore_native_object("X", "P")

        self.assertEqual(self.ctx.trace.boundaries[-1]["kind"], "restore_failure")
        self.assertEqual(self.ctx.trace._phase["label"], "端点校准")
        self.assertEqual(self.ctx.executed_phases[-1]["label"], "端点校准")
        self.assertFalse(self.ctx.public_phase)


if __name__ == "__main__":
    unittest.main()
