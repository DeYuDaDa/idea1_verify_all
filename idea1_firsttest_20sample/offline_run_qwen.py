"""Run an offline multimodal Qwen pass on public AI2-THOR inputs only.

This module never opens hidden_gold, private_logs, pair_receipts, or simulator
metadata. It consumes only data/input JSON and referenced data/media RGB files.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_SERVER_HOME = Path(os.environ.get("SERVER_HOME") or Path.home())
_SERVER_PROFILE = os.environ.get("THOR_SERVER_PROFILE", "auto")
_AUTODL_ROOT = _SERVER_HOME / "autodl-tmp"
_DATA_ROOT_DEFAULT = Path(os.environ.get("DATA_ROOT") or (
    _AUTODL_ROOT / "idea1_firsttest_20sample"
    if _SERVER_PROFILE == "autodl" or (_SERVER_PROFILE == "auto" and _AUTODL_ROOT.is_dir() and os.access(_AUTODL_ROOT, os.W_OK))
    else _SERVER_HOME / "experiment_data" / "idea1_firsttest_20sample"
))
DEFAULT_MODEL = Path(os.environ.get("QWEN_MODEL_DIR") or (
    _AUTODL_ROOT / "model" / "qwen3.5-4b"
    if _SERVER_PROFILE == "autodl" or (_SERVER_PROFILE == "auto" and _AUTODL_ROOT.is_dir() and os.access(_AUTODL_ROOT, os.W_OK))
    else _SERVER_HOME / "model" / "qwen3.5-4b"
))
DEFAULT_OUTPUTS = _DATA_ROOT_DEFAULT / "model_outputs"


class RunnerError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8"))


def _json_read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Could not read public input {path}: {type(exc).__name__}: {exc}") from exc


def _check_public_model_input(model_input: Any, source: Path) -> dict[str, Any]:
    if not isinstance(model_input, dict):
        raise RunnerError(f"model_input must be an object: {source}")
    if str(model_input.get("protocol", "")).startswith("hard-selective-"):
        raise RunnerError("Hard-group inputs use frozen prepared_requests; this legacy Qwen runner cannot "
                          "serialize their full history/identity/state schema. No inference was started.")
    # Reuse only the public-data leak scanner; it never opens any gold files.
    from exporter import _scan_for_public_leaks
    leaks = _scan_for_public_leaks(model_input)
    if leaks:
        raise RunnerError(f"Public input contains forbidden final-state/gold keys: {source}: {leaks}")
    for key in ("objects", "history", "rules", "event", "frames", "questions"):
        if key not in model_input:
            raise RunnerError(f"Missing model_input.{key} in {source}")
    if not isinstance(model_input["questions"], list) or not model_input["questions"]:
        raise RunnerError(f"model_input.questions must be a nonempty list in {source}")
    if not isinstance(model_input["frames"], list) or not model_input["frames"]:
        raise RunnerError(f"model_input.frames must be a nonempty list in {source}")
    return model_input


def _safe_media_path(root: Path, relative: Any, source: Path) -> Path:
    if not isinstance(relative, str) or not relative:
        raise RunnerError(f"Invalid frame path in {source}")
    rel = Path(relative)
    if rel.is_absolute():
        raise RunnerError(f"Frame paths must be relative: {relative}")
    candidate = (root / rel).resolve()
    media_root = (root / "data" / "media").resolve()
    try:
        candidate.relative_to(media_root)
    except ValueError as exc:
        raise RunnerError(f"Frame path is outside data/media: {relative}") from exc
    if candidate.suffix.lower() != ".png" or not candidate.is_file():
        raise RunnerError(f"Missing/non-PNG public RGB frame: {relative}")
    return candidate


def load_public_samples(export_root: str | Path, limit: int | None = 1) -> list[dict[str, Any]]:
    """Load only data/input records and their referenced data/media bytes."""
    root = Path(export_root).expanduser().resolve()
    public_dir = root / "data" / "input"
    if not public_dir.is_dir():
        raise RunnerError(f"Public input directory does not exist: {public_dir}")
    paths = sorted(public_dir.glob("*.json"))
    resolved_public_dir = public_dir.resolve()
    for source in paths:
        if source.is_symlink():
            raise RunnerError(f"Public input JSON symlinks are not allowed: {source}")
        try:
            source.resolve().relative_to(resolved_public_dir)
        except ValueError as exc:
            raise RunnerError(f"Input JSON resolves outside data/input: {source}") from exc
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        paths = paths[:limit]
    if not paths:
        raise RunnerError(f"No public input JSON files found in {public_dir}")

    samples = []
    seen_sample_ids: set[str] = set()
    for source in paths:
        record = _json_read(source)
        if not isinstance(record, dict) or not isinstance(record.get("sample_id"), str):
            raise RunnerError(f"Public input needs a string sample_id: {source}")
        # This is the public_record shape written by exporter.export_case().
        allowed_record_keys = {"sample_id", "pair_id", "variant", "model_input"}
        extra_record_keys = sorted(set(record) - allowed_record_keys)
        if extra_record_keys:
            raise RunnerError(f"Unexpected top-level keys in public input {source}: {extra_record_keys}")
        sample_id = record["sample_id"]
        if sample_id in seen_sample_ids:
            raise RunnerError(f"Duplicate public sample_id: {sample_id}")
        seen_sample_ids.add(sample_id)
        model_input = _check_public_model_input(record.get("model_input"), source)
        media = []
        for frame_index, frame in enumerate(model_input["frames"]):
            if not isinstance(frame, dict):
                raise RunnerError(f"Invalid frame entry {frame_index} in {source}")
            media_path = _safe_media_path(root, frame.get("path"), source)
            media.append({
                "index": frame_index,
                "stage": str(frame.get("stage", "")),
                "relative_path": frame["path"],
                "path": media_path,
                "sha256": sha256_file(media_path),
            })
        input_hash = sha256_file(source)
        source_hash = canonical_hash({
            "public_input_sha256": input_hash,
            "media_sha256": [item["sha256"] for item in media],
        })
        samples.append({
            "sample_id": sample_id,
            "source_path": source,
            "source_sha256": input_hash,
            "source_fingerprint": source_hash,
            "model_input": model_input,
            "media": media,
        })
    return samples


def build_prompt(model_input: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    """Build text from an explicit public-field allowlist; never expose IDs/paths."""
    questions = []
    qid_to_fact_id: dict[str, str] = {}
    for index, question in enumerate(model_input.get("questions", []), 1):
        if not isinstance(question, Mapping):
            raise RunnerError("Each public question must be an object")
        qid = f"q{index:03d}"
        source_fact_id = question.get("fact_id")
        qid_to_fact_id[qid] = str(source_fact_id) if source_fact_id is not None else qid
        questions.append({
            "id": qid,
            "subject": str(question.get("subject", "")),
            "predicate": str(question.get("predicate", "")),
            "question": str(question.get("question", "")),
            "answer_mode": str(question.get("answer_mode", "current_value")),
        })

    objects = []
    for obj in model_input.get("objects", []):
        if not isinstance(obj, Mapping):
            continue
        objects.append({"alias": str(obj.get("alias", "")),
                        "object_type": str(obj.get("object_type", ""))})
    history = []
    for episode in model_input.get("history", []):
        if not isinstance(episode, Mapping):
            continue
        facts = []
        for fact in episode.get("facts", []) or []:
            if isinstance(fact, Mapping):
                facts.append({key: fact[key] for key in ("subject", "predicate", "value") if key in fact})
        history.append({"stage": str(episode.get("stage", "")), "facts": facts})
    event = model_input.get("event", {})
    if not isinstance(event, Mapping):
        raise RunnerError("Public event must be an object")
    safe_event = {key: event[key] for key in ("action", "subject", "destination", "success", "settle_steps")
                  if key in event}
    frames = [{"index": item, "stage": str(frame.get("stage", ""))}
              for item, frame in enumerate(model_input.get("frames", []), 1)
              if isinstance(frame, Mapping)]
    payload = {
        "protocol_note": str(model_input.get("protocol_note", "")),
        "objects": objects,
        "history": history,
        "rules": [str(rule) for rule in (model_input.get("rules", []) or [])],
        "event": safe_event,
        "frames": frames,
        "questions": questions,
    }
    prompt = (
        "Answer each question using the supplied public history, rules, event, and ordered images. "
        "Do not infer hidden simulator metadata. For insufficient evidence answer the string \"unknown\"; "
        "for an inapplicable property answer \"not_applicable\". For answer_mode change_status, use exactly "
        "\"changed\", \"preserved\", or \"unknown\". Return only one JSON object mapping every question id "
        "to its answer; arrays are allowed for relation lists. Do not add Markdown or explanations.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return prompt, qid_to_fact_id


def parse_structured_output(raw: str, expected_qids: list[str]) -> dict[str, Any]:
    """Strict JSON object parser; does not salvage prose or a partial object."""
    try:
        parsed = json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError):
        return {"format_status": "json_parse_error", "parsed": None, "answers": {},
                "missing_question_ids": list(expected_qids), "unexpected_question_ids": [],
                "invalid_answer_ids": []}
    if not isinstance(parsed, dict):
        return {"format_status": "json_not_object", "parsed": parsed, "answers": {},
                "missing_question_ids": list(expected_qids), "unexpected_question_ids": [],
                "invalid_answer_ids": []}
    answers = {}
    invalid = []
    for key, value in parsed.items():
        if key not in expected_qids:
            continue
        if isinstance(value, (str, bool, int, float)) or value is None:
            answers[key] = value.strip() if isinstance(value, str) else value
        elif isinstance(value, list) and all(isinstance(item, (str, bool, int, float)) or item is None for item in value):
            answers[key] = value
        else:
            invalid.append(key)
    missing = [qid for qid in expected_qids if qid not in answers and qid not in invalid]
    unexpected = [str(key) for key in parsed if str(key) not in expected_qids]
    if not missing and not invalid and not unexpected:
        status = "ok"
    elif answers:
        status = "partial"
    else:
        status = "invalid"
    return {"format_status": status, "parsed": parsed, "answers": answers,
            "missing_question_ids": missing, "unexpected_question_ids": unexpected,
            "invalid_answer_ids": invalid}


def _package_versions() -> dict[str, str | None]:
    result = {"python": platform.python_version()}
    for package in ("torch", "torchvision", "transformers", "accelerate", "Pillow"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = None
    return result


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _config_identity(model_dir: Path) -> dict[str, Any]:
    config_path = model_dir / "config.json"
    if not config_path.is_file():
        raise RunnerError(f"Missing model config: {config_path}")
    raw = config_path.read_bytes()
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Invalid local model config: {exc}") from exc
    if config.get("model_type") != "qwen3_5" or "vision_config" not in config:
        raise RunnerError("Local model config is not the expected Qwen3.5 vision model")
    weight_paths = sorted(path for path in model_dir.rglob("*")
                          if path.is_file() and path.suffix.lower() in {".safetensors", ".bin"})
    if not weight_paths:
        raise RunnerError(f"No local safetensors or .bin checkpoint files found in {model_dir}")
    index_paths = sorted(path for path in model_dir.rglob("*.index.json") if path.is_file())
    checkpoint_files = [{"relative_path": path.relative_to(model_dir).as_posix(),
                         "size_bytes": path.stat().st_size,
                         "mtime_ns": path.stat().st_mtime_ns}
                        for path in weight_paths]
    checkpoint_indexes = [{"relative_path": path.relative_to(model_dir).as_posix(),
                           "sha256": sha256_file(path)}
                          for path in index_paths]
    return {"path": str(model_dir), "config_sha256": sha256_bytes(raw),
            "model_type": config.get("model_type"), "architectures": config.get("architectures"),
            "vision_config_present": isinstance(config.get("vision_config"), dict),
            "checkpoint_files_size_mtime_only": checkpoint_files,
            "checkpoint_indexes": checkpoint_indexes,
            "checkpoint_integrity_note": "weight contents are not fully hashed; sizes and mtimes are recorded, index files are SHA-256 hashed"}


def pending_samples(samples: list[dict[str, Any]], completed_ids: set[str]) -> list[dict[str, Any]]:
    """Return selected samples without a completed prediction row."""
    return [sample for sample in samples if sample["sample_id"] not in completed_ids]


def _make_run_manifest(samples: list[dict[str, Any]], model_identity: dict[str, Any],
                       versions: dict[str, Any], settings: dict[str, Any],
                       review_status: str) -> dict[str, Any]:
    return {
        "run_schema_version": 1,
        "status": "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "review_status": review_status,
        "model": model_identity,
        "versions": versions,
        "settings": settings,
        "samples": [{"sample_id": sample["sample_id"],
                     "input_sha256": sample["source_sha256"],
                     "source_fingerprint": sample["source_fingerprint"],
                     "media": [{"relative_path": item["relative_path"], "sha256": item["sha256"]}
                               for item in sample["media"]]}
                    for sample in samples],
        "inference_input_boundary": "data/input JSON plus referenced data/media PNG only; no hidden/private records",
        "gold_or_score_read": False,
    }


def _resolve_run_dir(outputs_root: Path, run_dir: Path | None, resume: bool) -> Path:
    if resume:
        if run_dir is None:
            raise RunnerError("--resume requires --run-dir pointing to an existing run")
        resolved = run_dir.expanduser().resolve()
        if not resolved.is_dir():
            raise RunnerError(f"Resume run directory does not exist: {resolved}")
        return resolved
    if run_dir is not None:
        resolved = run_dir.expanduser().resolve()
    else:
        resolved = outputs_root.expanduser().resolve() / f"run_{_utc_stamp()}"
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _read_existing_predictions(path: Path, samples: list[dict[str, Any]]) -> set[str]:
    if not path.exists():
        return set()
    expected = {sample["sample_id"]: sample["source_fingerprint"] for sample in samples}
    completed: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RunnerError(f"Malformed existing prediction line {line_number}; refusing to truncate/resume") from exc
            sample_id = row.get("sample_id")
            if sample_id not in expected or row.get("source_fingerprint") != expected[sample_id]:
                raise RunnerError(f"Existing prediction line {line_number} does not match selected public sources")
            if row.get("status") != "error":
                completed.add(sample_id)
    return completed


def _load_images(sample: dict[str, Any]):
    from PIL import Image
    images = []
    for frame in sample["media"]:
        with Image.open(frame["path"]) as image:
            images.append(image.convert("RGB"))
    return images


def _infer_one(model, processor, sample: dict[str, Any], device: str, max_new_tokens: int,
               prompt_bundle: tuple[str, dict[str, str]] | None = None) -> dict[str, Any]:
    prompt, qid_to_fact_id = prompt_bundle if prompt_bundle is not None else build_prompt(sample["model_input"])
    images = _load_images(sample)
    try:
        content = [{"type": "image", "image": image} for image in images]
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]
        processing_started = time.perf_counter()
        inputs = processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_dict=True,
            return_tensors="pt", enable_thinking=False,
        )
        processing_seconds = time.perf_counter() - processing_started
        inputs = inputs.to(device)
        input_tokens = int(inputs["input_ids"].shape[-1])
        import torch
        torch.cuda.synchronize()
        inference_started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(**inputs, max_new_tokens=max_new_tokens,
                                       do_sample=False, use_cache=True)
        torch.cuda.synchronize()
        inference_seconds = time.perf_counter() - inference_started
        generated_tokens = generated[0, input_tokens:]
        raw_output = processor.tokenizer.decode(generated_tokens, skip_special_tokens=True,
                                                clean_up_tokenization_spaces=False)
        expected_qids = list(qid_to_fact_id)
        parsed = parse_structured_output(raw_output, expected_qids)
        return {
            "status": "complete",
            "question_id_map": qid_to_fact_id,
            **parsed,
            "raw_output": raw_output,
            "input_tokens": input_tokens,
            "output_tokens": int(generated_tokens.numel()),
            "processing_seconds": round(processing_seconds, 4),
            "inference_seconds": round(inference_seconds, 4),
        }
    finally:
        for image in images:
            image.close()


def run(args: argparse.Namespace) -> Path:
    if args.all and args.limit is not None:
        raise RunnerError("Choose either --all or --limit, not both")
    limit = None if args.all else (args.limit if args.limit is not None else 1)
    if limit is not None and limit < 1:
        raise RunnerError("--limit must be positive")
    if not args.review_approved and not args.debug_unreviewed:
        raise RunnerError("Pass --review-approved after external review, or --debug-unreviewed for an explicitly unreviewed debug run")
    if args.review_approved and os.environ.get("QWEN_EXTERNAL_STRICT_VALIDATION") != "pass":
        raise RunnerError("--review-approved is accepted only when the step-20 wrapper completed strict validation in thor20")
    review_status = "externally_review_approved" if args.review_approved else "debug_unreviewed_bypass"
    export_root = Path(args.export_root).expanduser().resolve()
    model_dir = Path(args.model_dir).expanduser().resolve()
    samples = load_public_samples(export_root, limit)
    model_identity = _config_identity(model_dir)
    versions = _package_versions()
    settings = {"limit": limit, "all_requested": bool(args.all), "max_new_tokens": args.max_new_tokens,
                "batch_size": 1, "do_sample": False, "enable_thinking": False,
                "dtype": "bfloat16", "attn_implementation": "sdpa"}
    expected_manifest = _make_run_manifest(samples, model_identity, versions, settings, review_status)
    run_dir = _resolve_run_dir(Path(args.outputs_root), args.run_dir, args.resume)
    manifest_path = run_dir / "run_manifest.json"
    predictions_path = run_dir / "predictions.jsonl"
    if args.resume:
        if not manifest_path.is_file() or not predictions_path.is_file():
            raise RunnerError("Resume requires both run_manifest.json and predictions.jsonl")
        old_manifest = _json_read(manifest_path)
        for key in ("model", "versions", "settings", "review_status", "samples", "inference_input_boundary", "gold_or_score_read"):
            if old_manifest.get(key) != expected_manifest.get(key):
                raise RunnerError(f"Resume refused: existing run {key} differs from current inputs/settings")
        completed = _read_existing_predictions(predictions_path, samples)
    else:
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(expected_manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        predictions_path.touch(exist_ok=False)
        completed = set()

    if args.limit is not None and args.limit < 1:
        raise RunnerError("--limit must be positive")
    if args.max_new_tokens < 1:
        raise RunnerError("--max-new-tokens must be positive")
    pending = pending_samples(samples, completed)
    if pending:
        import torch
        from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration
        if not torch.cuda.is_available():
            raise RunnerError("PyTorch cannot access CUDA; model inference requires the reviewed CUDA environment")
        if not torch.cuda.is_bf16_supported():
            raise RunnerError("This run requires BF16 support on the selected GPU")
        processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
        model = Qwen3_5ForConditionalGeneration.from_pretrained(
            model_dir, local_files_only=True, dtype=torch.bfloat16,
            attn_implementation="sdpa",
        ).to("cuda:0")
        model.eval()
        torch.cuda.synchronize()
        for sample in pending:
            started = time.perf_counter()
            request_text, expected_map = build_prompt(sample["model_input"])
            try:
                outcome = _infer_one(model, processor, sample, "cuda:0", args.max_new_tokens,
                                     prompt_bundle=(request_text, expected_map))
                status = "complete"
                error = None
            except Exception as exc:
                outcome = {"status": "error", "question_id_map": expected_map, "format_status": "not_run",
                           "answers": {}, "missing_question_ids": list(expected_map), "unexpected_question_ids": [],
                           "invalid_answer_ids": [], "raw_output": None, "input_tokens": None,
                           "output_tokens": None, "processing_seconds": None, "inference_seconds": None}
                status = "error"
                error = f"{type(exc).__name__}: {exc}"
            row = {"sample_id": sample["sample_id"], "status": status,
                   "review_status": review_status, "source_sha256": sample["source_sha256"],
                   "source_fingerprint": sample["source_fingerprint"],
                   "media_sha256": [item["sha256"] for item in sample["media"]],
                   "model_config_sha256": model_identity["config_sha256"],
                   "request_text": request_text,
                   "request_content_order": "ordered_images_then_text",
                   "request_text_boundary": "User text supplied to apply_chat_template; not expanded template or image patches. An error row may precede successful processor/model execution.",
                   "versions": versions, "settings": settings, "error": error,
                   "total_seconds": round(time.perf_counter() - started, 4), **outcome}
            with predictions_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if status != "error":
                completed.add(sample["sample_id"])

    manifest = _json_read(manifest_path)
    manifest["status"] = "complete" if len(completed) == len(samples) else "incomplete_with_errors"
    manifest["completed_samples"] = sorted(completed)
    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(manifest_path, manifest)
    return run_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-root", type=Path, required=True,
                        help="Reviewed export root containing data/input and data/media")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--outputs-root", type=Path, default=DEFAULT_OUTPUTS)
    parser.add_argument("--run-dir", type=Path, help="Existing run directory for --resume, or a new empty path")
    parser.add_argument("--resume", action="store_true", help="Append to a matching run; source/settings hashes must match")
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--limit", type=int, default=None, help="Run first N public samples (default: 1 smoke sample)")
    size.add_argument("--all", action="store_true", help="Explicitly request every public sample")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    review = parser.add_mutually_exclusive_group(required=True)
    review.add_argument("--review-approved", action="store_true",
                        help="Caller confirms external review passed; runner does not read review/hidden records")
    review.add_argument("--debug-unreviewed", action="store_true",
                        help="Explicitly bypass review for a debug run; status is recorded in output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_new_tokens < 1:
        raise SystemExit("--max-new-tokens must be positive")
    try:
        run_dir = run(args)
    except (RunnerError, FileExistsError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(json.dumps({"run_dir": str(run_dir), "predictions": str(run_dir / "predictions.jsonl"),
                      "manifest": str(run_dir / "run_manifest.json")}, ensure_ascii=False, indent=2))
    manifest = _json_read(run_dir / "run_manifest.json")
    return 0 if manifest.get("status") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
