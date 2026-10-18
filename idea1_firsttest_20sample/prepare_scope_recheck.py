#!/usr/bin/env python3
"""Prepare a public-only, single-question diagnostic export or collect its run."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import offline_run_qwen


PURPOSE = "exploratory single-question recheck; not an approved benchmark"

# Keep this list explicit. Each target is resolved against the public input's
# actual question and object aliases before any output directory is published.
TARGETS = (
    ("P20_A", "Apple_1", "position"),
    ("P20_A", "Plate_1", "position"),
    ("P20_B", "Apple_1", "position"),
    ("P20_B", "Plate_1", "position"),
    ("W09_A", "Bowl_1", "isFilledWithLiquid"),
    ("W09_A", "Faucet_1", "isToggled"),
    ("W09_B", "Bowl_1", "isFilledWithLiquid"),
    ("W09_B", "Faucet_1", "isToggled"),
    ("W10_A", "Bowl_1", "isDirty"),
    ("W10_A", "Faucet_1", "isToggled"),
    ("W10_B", "Bowl_1", "isDirty"),
    ("W10_B", "Faucet_1", "isToggled"),
    ("C14_A", "Mug_1", "fillLiquid"),
    ("C14_A", "CoffeeMachine_1", "isToggled"),
    ("C14_B", "Mug_1", "fillLiquid"),
    ("C14_B", "CoffeeMachine_1", "isToggled"),
    ("M02_A", "Potato_1", "temperature"),
    ("M02_A", "Microwave_1", "isToggled"),
    ("M02_B", "Potato_1", "temperature"),
    ("M02_B", "Microwave_1", "isToggled"),
    ("B19_A", "Laptop_1", "isBroken"),
    ("B19_A", "Laptop_1", "isToggled"),
    ("B19_B", "Laptop_1", "isBroken"),
    ("B19_B", "Laptop_1", "isToggled"),
)

BOOLEAN_PREDICATES = {"isBroken", "isToggled", "isFilledWithLiquid", "isDirty"}


def answer_contract(answer_mode: str, predicate: str) -> str:
    if answer_mode == "change_status":
        return ('Return one JSON string: "changed", "preserved", or "unknown" '
                "when the supplied public history, rules, event, and images are insufficient.")
    if predicate in BOOLEAN_PREDICATES:
        return ('Return a JSON boolean true or false; use the JSON string "unknown" '
                "when the supplied public history, rules, event, and images are insufficient.")
    if predicate == "temperature":
        return ('Return one JSON string: "Hot", "RoomTemp", "Cold", or "unknown" '
                "when the supplied public history, rules, event, and images are insufficient.")
    if predicate == "fillLiquid":
        return ('Return a JSON string naming the liquid as supported by the question and evidence '
                '(for example, "water", "coffee", or a more specific label such as "hot coffee"). '
                'Use JSON null if empty, or the JSON string "unknown" if the supplied public history, '
                'rules, event, and images are insufficient. '
                'Preserve supported qualifiers; do not normalize them away.')
    raise ValueError(f"No explicit answer contract for {answer_mode!r}/{predicate!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _select(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {sample["sample_id"]: sample for sample in samples}
    if len(by_id) != len(samples):
        raise ValueError("Public loader returned duplicate sample IDs")

    selected = []
    for original_id, alias, predicate in TARGETS:
        sample = by_id.get(original_id)
        if sample is None:
            raise ValueError(f"Required public sample is missing: {original_id}")
        model_input = sample["model_input"]
        aliases = [obj.get("alias") for obj in model_input.get("objects", [])
                   if isinstance(obj, dict)]
        if aliases.count(alias) != 1:
            raise ValueError(f"Expected exactly one public object alias {alias!r} in {original_id}")
        matches = [(index, question) for index, question in enumerate(model_input["questions"], 1)
                   if isinstance(question, dict)
                   and question.get("subject") == alias
                   and question.get("predicate") == predicate]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {alias}.{predicate} question in {original_id}; found {len(matches)}")
        index, question = matches[0]
        answer_mode = question.get("answer_mode", "current_value")
        if answer_mode not in {"current_value", "change_status"}:
            raise ValueError(f"Unsupported answer mode for {original_id} {alias}.{predicate}: {answer_mode!r}")
        if not isinstance(question.get("fact_id"), str) or not question["fact_id"]:
            raise ValueError(f"Question has no public fact_id: {original_id} {alias}.{predicate}")
        # Fail closed for a target whose prompt contract was not explicitly designed.
        contract = answer_contract(answer_mode, predicate)
        selected.append({
            "sample": sample,
            "original_sample_id": original_id,
            "original_qid": f"q{index:03d}",
            "original_question": question["question"],
            "question": question,
            "answer_contract": contract,
        })
    if len(selected) != 24:
        raise ValueError(f"Expected 24 selected questions, found {len(selected)}")
    return selected


def prepare_export(export_root: Path, data_root: Path, output_dir: Path) -> dict[str, Any]:
    """Validate all targets, then atomically publish a neutral public-only export."""
    source = export_root.expanduser().resolve(strict=True)
    data = data_root.expanduser().resolve(strict=True)
    output = output_dir.expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"Source export is not a directory: {source}")
    if not data.is_dir():
        raise ValueError(f"DATA_ROOT must already exist: {data}")
    if not _inside(output, data) or output == data:
        raise ValueError("Output directory must be a new child of DATA_ROOT")
    if _inside(output, source) or _inside(source, output):
        raise ValueError("Diagnostic output and source export must be separate trees")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite diagnostic output: {output}")

    # This runner API reads only data/input JSON and referenced data/media PNGs.
    # Target validation completes before the output directory is created.
    samples = offline_run_qwen.load_public_samples(source, limit=None)
    selected = _select(samples)

    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=data))
    try:
        input_dir = stage / "data" / "input"
        media_dir = stage / "data" / "media"
        input_dir.mkdir(parents=True)
        media_dir.mkdir(parents=True)
        provenance_dir = stage / "provenance"
        provenance_dir.mkdir()

        provenance = []
        media_counter = 0
        for index, item in enumerate(selected, 1):
            diagnostic_id = f"recheck_{index:03d}"
            sample = item["sample"]
            model_input = copy.deepcopy(sample["model_input"])
            original_question = copy.deepcopy(item["question"])
            original_question["question"] = (
                item["original_question"] + "\n\nOutput contract: " + item["answer_contract"]
            )
            model_input["questions"] = [original_question]

            media_by_path = {media["relative_path"]: media for media in sample["media"]}
            remapped_frames = []
            copied_media = []
            for frame in model_input["frames"]:
                original_path = frame["path"]
                media = media_by_path.get(original_path)
                if media is None:
                    raise ValueError(f"Referenced public frame was not loaded: {sample['sample_id']} {original_path}")
                media_counter += 1
                neutral_name = f"frame_{media_counter:04d}.png"
                target_media = media_dir / neutral_name
                shutil.copyfile(media["path"], target_media)
                copied_sha256 = _sha256(target_media)
                if copied_sha256 != media["sha256"]:
                    raise ValueError(f"Copied public frame hash mismatch: {sample['sample_id']} {original_path}")
                copied_media.append({"source_path": original_path,
                                     "relative_path": f"data/media/{neutral_name}",
                                     "source_sha256": media["sha256"],
                                     "copied_sha256": copied_sha256})
                new_frame = copy.deepcopy(frame)
                new_frame["path"] = f"data/media/{neutral_name}"
                remapped_frames.append(new_frame)
            model_input["frames"] = remapped_frames

            public_record = {"sample_id": diagnostic_id, "model_input": model_input}
            _write_json(input_dir / f"{diagnostic_id}.json", public_record)
            provenance.append({
                "diagnostic_id": diagnostic_id,
                "original_sample_id": item["original_sample_id"],
                "original_qid": item["original_qid"],
                "original_input_sha256": sample["source_sha256"],
                "original_fact_id": item["question"]["fact_id"],
                "original_question": item["original_question"],
                "purpose": PURPOSE,
                "copied_media": copied_media,
            })

        _write_json(provenance_dir / "provenance.json", provenance)
        created = datetime.now(timezone.utc).isoformat()
        _write_json(stage / "recheck_manifest.json", {
            "created_utc": created,
            "purpose": PURPOSE,
            "source_export": str(source),
            "source_reader": "offline_run_qwen.load_public_samples",
            "public_only": True,
            "hidden_gold_read": False,
            "selected_question_count": len(selected),
            "diagnostic_sample_ids": [f"recheck_{index:03d}" for index in range(1, len(selected) + 1)],
        })
        stage.rename(output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return {"output_dir": str(output), "question_count": len(selected),
            "media_copy_count": media_counter, "purpose": PURPOSE}


def package_run(data_root: Path, export_dir: Path, run_dir: Path,
                output_zip: Path, operation_log: Path | None = None) -> dict[str, Any]:
    """Archive only this diagnostic export and its explicitly designated run."""
    root = data_root.expanduser().resolve(strict=True)
    export = export_dir.expanduser().resolve(strict=True)
    run = run_dir.expanduser().resolve()
    archive_path = output_zip.expanduser().resolve()
    logs = (root / "logs").resolve()
    if not _inside(export, root) or not _inside(run, root) or not _inside(archive_path, logs):
        raise ValueError("Export/run must be under DATA_ROOT and ZIP must be under DATA_ROOT/logs")
    if archive_path.exists():
        raise FileExistsError(f"Refusing to overwrite archive: {archive_path}")

    entries: dict[Path, str] = {}
    missing = []
    # Reuse the public-only loader; hidden_gold and other private export folders
    # are neither walked nor added to the archive.
    samples = offline_run_qwen.load_public_samples(export, limit=None)
    for sample in samples:
        entries[Path(sample["source_path"]).resolve()] = (
            "diagnostic_export/data/input/" + Path(sample["source_path"]).name
        )
        for media in sample["media"]:
            path = Path(media["path"]).resolve()
            entries[path] = "diagnostic_export/" + Path(media["relative_path"]).as_posix()
    for relative in ("provenance/provenance.json", "recheck_manifest.json"):
        path = export / relative
        if path.is_file():
            entries[path.resolve()] = "diagnostic_export/" + relative
        else:
            missing.append("diagnostic export " + relative)

    for name in ("run_manifest.json", "predictions.jsonl"):
        path = run / name
        if path.is_file():
            entries[path.resolve()] = f"model_output/{run.name}/{name}"
        else:
            missing.append(f"designated model run {run.name}/{name}")
    if operation_log is not None:
        log = operation_log.expanduser().resolve()
        if log.is_file() and _inside(log, root):
            entries[log] = "operation_log/" + log.name
        else:
            missing.append("current operation log")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    file_manifest = [{"path": arc, "bytes": path.stat().st_size, "sha256": _sha256(path)}
                     for path, arc in sorted(entries.items(), key=lambda pair: pair[1])]
    bundle_manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "collector_scope": "diagnostic public inputs, sidecar provenance, and designated run only",
        "hidden_gold_read": False,
        "export_dir": str(export),
        "run_dir": str(run),
        "missing": missing,
        "files": file_manifest,
    }
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path, arc in sorted(entries.items(), key=lambda pair: pair[1]):
            archive.write(path, arc)
        archive.writestr("bundle_manifest.json", json.dumps(bundle_manifest, ensure_ascii=False, indent=2) + "\n")
    return {"archive": str(archive_path), "files": len(entries), "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="prepare 24 public one-question records")
    prepare.add_argument("--data-root", type=Path, required=True)
    prepare.add_argument("--export-root", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    package = subparsers.add_parser("package", help="collect one diagnostic export and its designated run")
    package.add_argument("--data-root", type=Path, required=True)
    package.add_argument("--export-dir", type=Path, required=True)
    package.add_argument("--run-dir", type=Path, required=True)
    package.add_argument("--output-zip", type=Path, required=True)
    package.add_argument("--operation-log", type=Path)
    args = parser.parse_args()

    if args.command == "prepare":
        result = prepare_export(args.export_root, args.data_root, args.output_dir)
    else:
        result = package_run(args.data_root, args.export_dir, args.run_dir,
                             args.output_zip, args.operation_log)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
