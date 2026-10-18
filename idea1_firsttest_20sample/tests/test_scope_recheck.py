import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import prepare_scope_recheck as recheck
import offline_run_qwen


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_public_fixture(root, omit=None):
    export = root / "exports_scope_v2_fixture"
    input_dir = export / "data" / "input"
    media_dir = export / "data" / "media"
    media_dir.mkdir(parents=True)
    aliases_by_sample = {}
    targets_by_sample = {}
    for sample_id, alias, predicate in recheck.TARGETS:
        aliases_by_sample.setdefault(sample_id, set()).add(alias)
        targets_by_sample.setdefault(sample_id, []).append((alias, predicate))

    for index, (sample_id, target_questions) in enumerate(targets_by_sample.items(), 1):
        objects = sorted(aliases_by_sample[sample_id])
        questions = []
        for qindex, (alias, predicate) in enumerate(target_questions, 1):
            answer_mode = "change_status" if predicate == "position" else "current_value"
            questions.append({
                "fact_id": f"{alias}.{predicate}",
                "subject": alias,
                "predicate": predicate,
                "answer_mode": answer_mode,
                "question": f"Original question for {alias} {predicate}?",
            })
        if omit == (sample_id, target_questions[-1][0], target_questions[-1][1]):
            questions.pop()
        frame_name = f"source_{index:02d}.png"
        (media_dir / frame_name).write_bytes(f"fixture RGB bytes {index}".encode("ascii"))
        write_json(input_dir / f"{sample_id}.json", {
            "sample_id": sample_id,
            "pair_id": sample_id[:-2],
            "variant": sample_id[-1],
            "model_input": {
                "protocol_note": "Use the public history, event and image.",
                "objects": [{"alias": alias, "object_type": alias.rsplit("_", 1)[0]}
                            for alias in objects],
                "history": [],
                "rules": ["Follow only the visible event and public history."],
                "event": {"action": "FixtureEvent", "success": True},
                "frames": [{"stage": "event_settled", "path": f"data/media/{frame_name}"}],
                "questions": questions,
            },
        })
    write_json(export / "hidden_gold" / "P20_A.json", {"answer": "private sentinel"})
    (media_dir / "unreferenced_private.png").write_bytes(b"not referenced")
    return export


class ScopeRecheckTests(unittest.TestCase):
    def test_prepare_publishes_24_single_question_public_records_and_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            source = make_public_fixture(data_root)
            output = data_root / "scope_recheck_20261018T000000Z"

            result = recheck.prepare_export(source, data_root, output)

            self.assertEqual(result["question_count"], 24)
            self.assertEqual(len(list((output / "data" / "input").glob("*.json"))), 24)
            self.assertEqual(len(list((output / "data" / "media").glob("*.png"))), 24)
            self.assertFalse((output / "hidden_gold").exists())
            self.assertFalse((output / "data" / "media" / "unreferenced_private.png").exists())
            records = [json.loads(path.read_text(encoding="utf-8"))
                       for path in sorted((output / "data" / "input").glob("*.json"))]
            self.assertEqual(len({record["sample_id"] for record in records}), 24)
            self.assertTrue(all(len(record["model_input"]["questions"]) == 1 for record in records))
            self.assertFalse(any("P20_A" in record["sample_id"] or "B19_B" in record["sample_id"]
                                 for record in records))
            self.assertTrue(all("Original question" in record["model_input"]["questions"][0]["question"]
                                and "Output contract:" in record["model_input"]["questions"][0]["question"]
                                and record["model_input"]["questions"][0]["fact_id"]
                                for record in records))
            for record in records:
                prompt, _ = offline_run_qwen.build_prompt(record["model_input"])
                self.assertNotIn("private sentinel", prompt)
                self.assertNotIn("hidden_gold", prompt)
                self.assertNotIn("P20_A", prompt)
                self.assertNotIn("B19_B", prompt)
                self.assertNotIn("Gold answer", prompt)
            provenance = json.loads((output / "provenance" / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(len(provenance), 24)
            self.assertTrue(all(item["original_question"] and item["original_fact_id"]
                                and item["original_input_sha256"] for item in provenance))
            bundled_text = "\n".join(path.read_text(encoding="utf-8")
                                      for path in output.rglob("*.json"))
            self.assertNotIn("private sentinel", bundled_text)
            manifest = json.loads((output / "recheck_manifest.json").read_text(encoding="utf-8"))
            self.assertIs(manifest["hidden_gold_read"], False)
            self.assertFalse(any(path.name == "hidden_gold" for path in output.rglob("*")))

    def test_answer_contracts_are_explicit_and_do_not_contain_answers(self):
        self.assertIn('"changed", "preserved", or "unknown"',
                      recheck.answer_contract("change_status", "position"))
        self.assertIn("JSON boolean true or false", recheck.answer_contract("current_value", "isToggled"))
        self.assertIn('"Hot", "RoomTemp", "Cold", or "unknown"',
                      recheck.answer_contract("current_value", "temperature"))
        liquid = recheck.answer_contract("current_value", "fillLiquid")
        self.assertIn('"water"', liquid)
        self.assertIn('"coffee"', liquid)
        self.assertIn('"hot coffee"', liquid)
        self.assertIn("JSON null", liquid)
        self.assertIn('"unknown"', liquid)
        for contract in (liquid, recheck.answer_contract("current_value", "isDirty")):
            self.assertNotIn("gold", contract.lower())
            self.assertNotIn("correct answer", contract.lower())
            self.assertNotIn("expected answer", contract.lower())

    def test_missing_target_fails_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            source = make_public_fixture(data_root, omit=("B19_B", "Laptop_1", "isToggled"))
            output = data_root / "scope_recheck_20261018T000001Z"

            with self.assertRaisesRegex(ValueError, "Expected exactly one Laptop_1.isToggled"):
                recheck.prepare_export(source, data_root, output)

            self.assertFalse(output.exists())
            self.assertEqual(list(data_root.glob(".scope_recheck_20261018T000001Z.stage-*")), [])

    def test_package_contains_only_the_designated_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            source = make_public_fixture(data_root)
            export = data_root / "scope_recheck_20261018T000002Z"
            recheck.prepare_export(source, data_root, export)
            selected_run = export / "model_outputs" / "run_scope_recheck_selected"
            old_run = data_root / "model_outputs" / "run_old"
            selected_run.mkdir(parents=True)
            old_run.mkdir(parents=True)
            write_json(selected_run / "run_manifest.json", {"run": "selected"})
            (selected_run / "predictions.jsonl").write_text("selected\n", encoding="utf-8")
            write_json(old_run / "run_manifest.json", {"run": "old"})
            (old_run / "predictions.jsonl").write_text("old\n", encoding="utf-8")
            archive_path = data_root / "logs" / "scope_recheck.zip"

            recheck.package_run(data_root, export, selected_run, archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("model_output/run_scope_recheck_selected/predictions.jsonl", names)
                self.assertIn("model_output/run_scope_recheck_selected/run_manifest.json", names)
                self.assertFalse(any("run_old" in name for name in names))


if __name__ == "__main__":
    unittest.main()
