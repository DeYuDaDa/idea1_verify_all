import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import hard_generate
from hard_scenarios import cases


class HardGenerateModesTests(unittest.TestCase):
    def test_frozen_ids_match_human_acceptance_record(self):
        import json
        policy = json.loads((Path(hard_generate.__file__).parent / "hard_accepted_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(set(policy["case_ids"]), hard_generate.FROZEN_CASES)

    def test_all_plan_excludes_frozen_accepted_cases(self):
        output = io.StringIO()
        with patch("hard_generate.sys.platform", "win32"), contextlib.redirect_stdout(output):
            self.assertEqual(hard_generate.main(["--all", "--plan-only"]), 0)
        import json
        case_ids = {row["case_id"] for row in json.loads(output.getvalue())["cases"]}
        self.assertTrue({"H04-2", "H04-3"}.isdisjoint(case_ids))

    def test_explicit_frozen_case_is_rejected_for_execution(self):
        with patch("hard_generate.sys.platform", "win32"):
            with self.assertRaises(SystemExit) as raised:
                hard_generate.main(["--cases", "H04-2"])
        self.assertEqual(raised.exception.code, 2)

    def test_programmatic_guard_precedes_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "must_not_be_created"
            frozen_case = next(case for case in cases() if case.case_id == "H04-3")
            with self.assertRaisesRegex(ValueError, "H04-3"):
                hard_generate.generate([frozen_case], output, {}, build_cache=Path(temp))
            self.assertFalse(output.exists())

    def test_camera_preflight_is_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            def require(ok, msg):
                if not ok:
                    self.fail(msg)
            ctx = SimpleNamespace(debug_views=False, out=Path(temp), require=require)
            with patch("hard_generate.configure_evidence_cameras") as configure:
                report = hard_generate._camera_preflight(ctx, object())
            configure.assert_not_called()
            self.assertEqual(report["status"], "not_requested")
            self.assertEqual(report["camera_kind"], "none_agent_first_person_only")

            ctx.debug_views = True
            with patch("hard_generate.configure_evidence_cameras", return_value={"status": "screened"}) as configure:
                report = hard_generate._camera_preflight(ctx, object())
            configure.assert_called_once()
            self.assertEqual(report["status"], "screened")


if __name__ == "__main__":
    unittest.main()
