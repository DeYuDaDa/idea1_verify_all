import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from full_step_trace import FullStepTrace
from runtime import ActionFailure, ControllerSession


def make_event(value=0, third_party=None):
    return SimpleNamespace(
        frame=np.full((2, 3, 3), value, dtype=np.uint8),
        third_party_camera_frames=third_party or [],
        metadata={"sceneName": "MockScene", "lastActionSuccess": True,
                  "errorMessage": "", "thirdPartyCameras": []},
    )


class MockController:
    def __init__(self, event):
        self.last_event = event
        self.calls = 0
        self.next_event = event
        self.raise_error = None

    def step(self, *, action, **kwargs):
        self.calls += 1
        if self.raise_error is not None:
            raise self.raise_error
        self.last_event = self.next_event
        return self.next_event

    def reset(self, **kwargs):
        self.calls += 1
        self.last_event = self.next_event
        return self.next_event


def make_session(event=None):
    session = ControllerSession.__new__(ControllerSession)
    session.controller = MockController(event or make_event())
    session.scene = "MockScene"
    # __new__ skips the real constructor (and therefore Unity). Supply its
    # configuration fields so reset can record an authentic Initialize ledger.
    session.platform = "CloudRendering"
    session.width = 3
    session.height = 2
    session.quality = "Low"
    session.render_depth = False
    session.render_instance_segmentation = True
    session.field_of_view = 75
    session.records = []
    session._step_observers = []
    session.observer_errors = []
    return session


class FullStepTraceTests(unittest.TestCase):
    def test_native_failure_is_recorded_and_stale_event_is_not_a_new_frame(self):
        session = make_session()
        with tempfile.TemporaryDirectory() as temporary:
            trace = FullStepTrace(session, temporary)
            prior = session.controller.last_event
            session.controller.raise_error = RuntimeError("native boom")
            with self.assertRaises(ActionFailure):
                session.step("BadAction", raise_on_failure=True)
            row = trace.events[-1]
            self.assertIs(session.controller.last_event, prior)
            self.assertFalse(row["new_event_received"])
            self.assertEqual(row["frame_status"], "stale_exception_event_not_new_picture")
            self.assertEqual(row["frames"], [])
            self.assertEqual(row["native_exception"], "RuntimeError: native boom")
            self.assertTrue(trace.finish()["visual_evidence_pending"])

    def test_reset_uses_unique_global_steps_despite_action_index_restart(self):
        session = make_session()
        with tempfile.TemporaryDirectory() as temporary:
            trace = FullStepTrace(session, temporary)
            trace.capture_current("initial")
            session.controller.next_event = make_event(1)
            session.reset("MockScene")
            rows = trace.events
            self.assertEqual([row["global_step"] for row in rows], [0, 1])
            self.assertEqual(rows[0]["action_index"], 0)
            self.assertEqual(rows[1]["action_index"], 0)
            self.assertEqual(rows[1]["reset_index"], 1)
            self.assertEqual(session.records[0]["kwargs"], {
                "scene": "MockScene", "platform": "CloudRendering",
                "width": 3, "height": 2, "fieldOfView": 75, "quality": "Low",
                "renderDepthImage": False, "renderInstanceSegmentation": True,
            })
            self.assertEqual(session.observer_errors, [])
            trace.finish()

    def test_exact_pixel_rle_retains_reappearance_and_phase_boundaries(self):
        session = make_session()
        with tempfile.TemporaryDirectory() as temporary:
            trace = FullStepTrace(session, temporary)
            trace.set_phase("private setup")
            for value in (0, 0, 1, 0):
                session.controller.next_event = make_event(value)
                session.step("Pass")
            trace.set_phase("public history", public=True)
            for value in (0, 0):
                session.controller.next_event = make_event(value)
                session.step("Pass")
            trace.mark("target event", kind="target")
            session.controller.next_event = make_event(0)
            session.step("PutObject")
            runs = trace.runs
            agent_runs = [run for run in runs if run["view_id"] == "agent"]
            self.assertEqual([run["run_length"] for run in agent_runs], [2, 1, 1, 2, 1])
            self.assertEqual([run["duplicate_count"] for run in agent_runs], [1, 0, 0, 1, 0])
            self.assertEqual(agent_runs[0]["pixel_sha256"], agent_runs[2]["pixel_sha256"])
            self.assertTrue(all(Path(temporary, run["path"]).exists() for run in agent_runs))
            self.assertTrue(trace.model_frames())
            self.assertTrue(all("phase_label" not in frame for frame in trace.model_frames()))
            self.assertEqual(len(trace.finish()["model_frames"]), len(trace.model_frames()))

    def test_capture_current_sends_no_native_command_and_pixel_change_is_kept(self):
        session = make_session(make_event(0))
        with tempfile.TemporaryDirectory() as temporary:
            trace = FullStepTrace(session, temporary)
            before = session.controller.calls
            first = trace.capture_current()
            session.controller.last_event = make_event(2)
            second = trace.capture_current("changed")
            self.assertEqual(session.controller.calls, before)
            self.assertNotEqual(first["frames"][0]["pixel_sha256"],
                                second["frames"][0]["pixel_sha256"])
            self.assertEqual(len(trace.runs), 2)
            trace.finish()

    def test_capture_groups_deduplicate_only_complete_synchronized_view_sets(self):
        session = make_session(make_event(0, [np.full((2, 3, 3), 9, dtype=np.uint8)]))
        session.controller.last_event.metadata["thirdPartyCameras"] = [{"thirdPartyCameraId": 0}]
        with tempfile.TemporaryDirectory() as temporary:
            trace = FullStepTrace(session, temporary)
            trace.set_cameras([{"camera_id": 0, "view_id": "distant_overview",
                                "purpose": "distant_room_overview"}])
            trace.set_phase("public history", public=True)
            # Agent is unchanged while the overview changes: retain this whole
            # timestep as a distinct synchronized group.
            for agent, overview in ((0, 9), (0, 8), (0, 8)):
                session.controller.next_event = make_event(agent, [np.full((2, 3, 3), overview, dtype=np.uint8)])
                session.controller.next_event.metadata["thirdPartyCameras"] = [{"thirdPartyCameraId": 0}]
                session.step("Pass")
            index = trace.finish()
            groups = index["capture_groups"]
            self.assertEqual([g["run_length"] for g in groups], [1, 2])
            self.assertEqual([v["view_id"] for v in groups[0]["views"]], ["agent", "distant_overview"])
            self.assertEqual(groups[0]["views"][0]["pixel_sha256"], groups[1]["views"][0]["pixel_sha256"])
            self.assertNotEqual(groups[0]["views"][1]["pixel_sha256"], groups[1]["views"][1]["pixel_sha256"])
            self.assertEqual(len(index["model_frames"]), 2)
            self.assertTrue(all(frame["view_id"] == "agent" for frame in index["model_frames"]))
            self.assertFalse(any("distant_overview" in str(frame) for frame in index["model_frames"]))

    def test_observer_exception_does_not_mask_native_error(self):
        session = make_session()
        def bad_observer(_result):
            raise ValueError("observer failed")
        session.add_step_observer(bad_observer)
        session.controller.raise_error = RuntimeError("original native error")
        with self.assertRaises(ActionFailure) as caught:
            session.step("BadAction")
        self.assertEqual(str(caught.exception), "RuntimeError: original native error")
        self.assertEqual(len(session.observer_errors), 1)


if __name__ == "__main__":
    unittest.main()
