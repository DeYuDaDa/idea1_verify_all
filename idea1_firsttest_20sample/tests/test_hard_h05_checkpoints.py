import json
import tempfile
import unittest
from pathlib import Path

from hard_checkpoint import ScenarioCheckpointBook


class FakeSession:
    def __init__(self):
        self.records = []
        self.state = {"agent": {"position": {"x": 1, "y": 0, "z": 2}},
                      "inventoryObjects": [],
                      "objects": [{"objectId": "potato-1", "objectType": "Potato",
                                   "isCooked": False, "temperature": "RoomTemp",
                                   "parentReceptacles": ["counter-1"]}]}

    def snapshot(self):
        return self.state


class FakeTrace:
    def __init__(self, root):
        self.directory = Path(root)
        (self.directory / "frames").mkdir(exist_ok=True)
        (self.directory / "frames/example.png").write_bytes(b"fixture-not-unity")
        self.rows = []

    @property
    def events(self):
        return self.rows

    def capture_current(self, label):
        self.rows.append({"global_step": len(self.rows), "action_index": len(self.rows),
                          "record_kind": "checkpoint", "capture_label": label,
                          "frame_status": "captured",
                          "frames": [{"view_id": "agent", "path": "frames/example.png"}]})
        return self.rows[-1]


class FakeContext:
    def __init__(self, out):
        self.out = Path(out)
        self.session = FakeSession()
        self.trace = FakeTrace(out)
        self.roles = {"Z": "potato-1"}


class ScenarioCheckpointBookTests(unittest.TestCase):
    def make_book(self, root):
        ctx = FakeContext(root)
        book = ScenarioCheckpointBook(ctx, scenario="H05", variant=1,
                                      plan=[{"checkpoint_id": "start", "label": "start"}])
        return ctx, book

    def test_begin_finish_persists_facts_receipts_and_global_frame_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx, book = self.make_book(directory)
            book.begin("start")
            ctx.session.records.append({"index": 12, "action": "Pass", "kwargs": {},
                                        "lastActionSuccess": True})
            row = book.finish([{"name": "uncooked", "expected": False, "actual": False}])
            self.assertEqual(row["status"], "passed")
            self.assertEqual(row["finish"]["native_receipts"][0]["action"], "Pass")
            self.assertEqual(row["finish"]["capture"]["global_step"], 1)
            self.assertEqual(ctx.review_checkpoints[0]["checkpoint_id"], "start")
            saved = json.loads((Path(directory) / "scenario_checkpoints.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["checkpoints"][0]["facts"][0]["actual"], False)

    def test_failed_fact_keeps_first_error_when_later_error_arrives(self):
        with tempfile.TemporaryDirectory() as directory:
            _, book = self.make_book(directory)
            book.begin("start")
            row = book.finish([{"name": "cooked", "expected": True, "actual": False}])
            first = book.first_error
            self.assertEqual(row["status"], "failed")
            book.fail("later failure")
            self.assertEqual(book.first_error, first)
            saved = json.loads((Path(directory) / "scenario_checkpoints.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["first_error"], first)

    def test_fail_marks_active_node_and_preserves_snapshot_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx, book = self.make_book(directory)
            book.begin("start")
            ctx.session.records.append({"index": 2, "action": "PutObject", "kwargs": {"objectId": "counter-1"},
                                        "lastActionSuccess": False, "errorMessage": "blocked"})
            book.fail("native placement blocked")
            row = book.records[0]
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["failure"], "native placement blocked")
            self.assertEqual(row["failure_receipts"][0]["errorMessage"], "blocked")
            self.assertEqual(row["failure_capture"]["global_step"], 1)


if __name__ == "__main__":
    unittest.main()
