"""Prepare and fail-closed check a human evidence-quality review packet.

This module reads exported JSON and PNG bytes only. It never starts AI2-THOR or
a model, and it never uses hidden gold as reviewer-facing evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from review import sample_fingerprint


VERSION = 1
MODES = {"direct_visual", "visual_history_and_rules", "oracle_history_and_rules"}
DECISIONS = {"pending", "approve", "reject"}
EVENT_FIELDS = {"action", "subject", "destination", "success"}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Not a readable PNG header: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if width < 1 or height < 1:
        raise ValueError(f"Invalid PNG dimensions: {path}")
    # A valid header alone does not establish that the pixels can be decoded.
    # Pillow is already a dependency of the simulator export environment.
    from PIL import Image
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ValueError(f"Not a PNG image: {path}")
        image.verify()
    with Image.open(path) as image:
        image.load()
        if image.size != (width, height):
            raise ValueError(f"PNG header/decode size mismatch: {path}")
    return width, height


def _sample_ids(root: Path) -> list[str]:
    public = {p.stem for p in (root / "data" / "input").glob("*.json")}
    hidden = {p.stem for p in (root / "hidden_gold").glob("*.json")}
    if public != hidden:
        missing_public = sorted(hidden - public)
        missing_hidden = sorted(public - hidden)
        raise ValueError(f"Public/Gold sample sets differ; missing public={missing_public}, missing Gold={missing_hidden}")
    ids = sorted(public)
    if not ids:
        raise ValueError("No matching public and hidden sample records were found")
    return ids


def _validate_frame_path(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute():
        raise ValueError(f"Frame path must be dataset-relative: {relative}")
    path = (root / rel).resolve(strict=True)
    media = (root / "data" / "media").resolve(strict=True)
    try:
        path.relative_to(media)
    except ValueError as exc:
        raise ValueError(f"Frame path is outside data/media: {relative}") from exc
    if not path.is_file():
        raise ValueError(f"Frame is not a file: {relative}")
    return path


def _stage_kind(stage: Any) -> str:
    value = str(stage or "").lower()
    if value in {
        "before_event", "immediately_before_event", "pre_event", "before_activation",
        "cup_inside_earlier", "cup_removed_before_activation",
        "microwave_contents_before_closing", "stove_control_and_support",
        "apple_plate_support",
    }:
        return "before"
    if value in {"event", "event_after", "event_immediate", "event_settled", "after_event", "evaluated_event", "post_event", "immediately_after_event"}:
        return "after"
    return "other"


def _prepare_sample(root: Path, sample_id: str, fingerprint: str,
                    packet_root: Path, copy_map: dict[str, str], duplicate_hashes: dict[str, list[str]]) -> tuple[dict[str, Any], list[str]]:
    public = _read(root / "data" / "input" / f"{sample_id}.json")
    model = public.get("model_input") if isinstance(public, Mapping) else None
    if not isinstance(model, Mapping):
        raise ValueError(f"Missing public model_input: {sample_id}")
    protocol = model.get("protocol")
    frames = model.get("frames", [])
    history = model.get("history", [])
    rules = model.get("rules", [])
    event = model.get("event")
    questions = model.get("questions", [])
    if not isinstance(frames, list) or not isinstance(history, list) or not isinstance(rules, list) or not isinstance(questions, list):
        raise ValueError(f"Malformed public frames/history/rules/questions: {sample_id}")
    if not frames:
        raise ValueError(f"Public sample has no RGB frames: {sample_id}")
    if not questions:
        raise ValueError(f"Public sample has no questions: {sample_id}")
    if not isinstance(event, Mapping):
        raise ValueError(f"Missing public event record: {sample_id}")
    frame_records = []
    warnings = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping) or not isinstance(frame.get("path"), str):
            raise ValueError(f"Invalid public frame record {sample_id}[{index}]")
        rel = frame["path"]
        source = _validate_frame_path(root, rel)
        sha = _sha256(source)
        dims = _png_dimensions(source)
        duplicate_hashes.setdefault(sha, []).append(f"{sample_id}:{rel}")
        preview_name = copy_map.setdefault(sha, f"frame_{len(copy_map)+1:04d}.png")
        dest = packet_root / "preview" / preview_name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            if _sha256(dest) != sha:
                raise ValueError(f"Copied frame hash mismatch: {sample_id} {rel}")
        frame_records.append({"index": index, "path": rel, "stage": frame.get("stage"),
                              "source_sha256": sha, "width": dims[0], "height": dims[1],
                              "preview": f"preview/{preview_name}"})
    if not frame_records:
        warnings.append("No RGB frames are present.")
    # The packet index contains public inputs only. Gold files are never read here.
    safe_public = {"sample_id": sample_id, "protocol": protocol,
                   "protocol_note": model.get("protocol_note"),
                   "objects": model.get("objects", []), "history": history,
                   "rules": rules, "event": event, "questions": questions,
                   "frames": [{k: f.get(k) for k in ("index", "stage", "path", "preview", "source_sha256", "width", "height")} for f in frame_records]}
    sample_form = {"sample_id": sample_id, "sample_fingerprint": fingerprint,
                   "source_protocol": protocol, "frames": frame_records,
                   "history_count": len(history), "rules_count": len(rules),
                   "event_fields": sorted(k for k in event if k in EVENT_FIELDS),
                   "questions": []}
    seen = set()
    for index, q in enumerate(questions, 1):
        if (not isinstance(q, Mapping) or not isinstance(q.get("fact_id"), str) or not q["fact_id"].strip()
                or not isinstance(q.get("subject"), str) or not q["subject"].strip()
                or not isinstance(q.get("predicate"), str) or not q["predicate"].strip()):
            raise ValueError(f"Invalid public question {sample_id} q{index:03d}")
        fact_id = q["fact_id"]
        if fact_id in seen:
            raise ValueError(f"Duplicate fact_id in public questions: {sample_id} {fact_id}")
        seen.add(fact_id)
        sample_form["questions"].append({
            "original_qid": f"q{index:03d}", "fact_id": fact_id,
            "subject": q.get("subject"), "predicate": q.get("predicate"),
            "original_question": q.get("question"), "answer_mode": q.get("answer_mode"),
            "mode": "unassigned", "claim_notes": {"before_condition": "", "event_evidence": "", "effect_or_preservation_reason": ""},
            "evidence_refs": [], "state_discriminability_review": "pending",
            "state_discriminability_reason": "", "relevant_state_evidence_note": "", "calibration_note": "",
            "calibration_not_required_reason": "", "images_readable_and_relevant": False,
            "no_unresolved_visual_text_conflict": False, "decision": "pending", "reviewer_note": ""})
    index_path = packet_root / "public" / f"{sample_id}.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(safe_public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sample_form, warnings


def prepare(export_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    root = Path(export_root).expanduser().resolve(strict=True)
    out = Path(output_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Export root is not a directory: {root}")
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite packet directory: {out}")
    try:
        out.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("Packet output must be outside export root")
    ids = _sample_ids(root)
    # Create only after all sample fingerprints can be computed.
    fingerprints = {sid: sample_fingerprint(root, sid) for sid in ids}
    out.mkdir(parents=True)
    copied: dict[str, str] = {}
    duplicate_hashes: dict[str, list[str]] = {}
    samples = []
    warnings = []
    try:
        for sid in ids:
            entry, sample_warnings = _prepare_sample(root, sid, fingerprints[sid], out, copied, duplicate_hashes)
            samples.append(entry)
            warnings.extend(f"{sid}: {item}" for item in sample_warnings)
        for paths in duplicate_hashes.values():
            if len(paths) > 1:
                warnings.append("Exact duplicate RGB hash (informational): " + ", ".join(paths))
        form = {"evidence_review_version": VERSION,
                "root_fingerprint": hashlib.sha256(json.dumps(fingerprints, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "reviewer": "", "samples": samples,
                "instructions": "Inspect each public history, rule, event and question with its RGB previews. Preserve the declared public protocol; never infer visual input from oracle history. Complete claim notes and typed evidence references per question. Pending or rejected decisions never approve a sample."}
        (out / "review_form.json").write_text(json.dumps(form, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = ["# Evidence quality review", "", "This private packet contains public records and RGB previews only. It contains no model predictions or gold answers.", ""]
        for sample in samples:
            sid = sample["sample_id"]
            pub = _read(out / "public" / f"{sid}.json")
            lines += [f"## {sid}", "", f"Declared protocol: `{sample['source_protocol']}`", "", "### RGB frames", ""]
            for frame in sample["frames"]:
                lines.append(f"- [{frame['stage'] or frame['index']}]({frame['preview']}) — source `{frame['path']}`; SHA-256 `{frame['source_sha256']}`; {frame['width']}×{frame['height']}")
            lines += ["", "### Public history", "", "```json", json.dumps(pub["history"], ensure_ascii=False, indent=2), "```", "", "### Public rules", "", "```json", json.dumps(pub["rules"], ensure_ascii=False, indent=2), "```", "", "### Public event", "", "```json", json.dumps(pub["event"], ensure_ascii=False, indent=2), "```", "", "### Questions", ""]
            for q in pub["questions"]:
                lines.append(f"- `{q.get('fact_id')}` ({q.get('subject')}.{q.get('predicate')}): {q.get('question')}")
            lines.append("")
        (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise
    return {"output_dir": str(out), "form": str(out / "review_form.json"), "sample_count": len(ids), "question_count": sum(len(s["questions"]) for s in samples), "preview_count": len(copied), "warnings": warnings}


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_ref(ref: Any, model: Mapping[str, Any], sample_id: str) -> str | None:
    if not isinstance(ref, Mapping):
        return "evidence reference must be an object"
    kind = ref.get("kind")
    if kind == "frame":
        allowed = {f.get("path") for f in model.get("frames", []) if isinstance(f, Mapping)}
        return None if ref.get("frame_path") in allowed else "frame reference is not in current public input"
    if kind == "history_fact":
        history_index, fact_index = ref.get("history_index"), ref.get("fact_index")
        history = model.get("history", [])
        if not isinstance(history_index, int) or isinstance(history_index, bool) or not 0 <= history_index < len(history):
            return "history_index is invalid"
        facts = history[history_index].get("facts", []) if isinstance(history[history_index], Mapping) else []
        if not isinstance(fact_index, int) or isinstance(fact_index, bool) or not 0 <= fact_index < len(facts):
            return "fact_index is invalid"
        return None
    if kind == "rule":
        idx = ref.get("rule_index")
        rules = model.get("rules", [])
        return None if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(rules) else "rule_index is invalid"
    if kind == "event":
        field = ref.get("field")
        event = model.get("event", {})
        return None if field in EVENT_FIELDS and field in event else "event field is invalid or absent"
    return "unknown evidence reference kind (Gold references are forbidden)"


def check(export_root: str | Path, form_path: str | Path) -> dict[str, Any]:
    root = Path(export_root).expanduser().resolve(strict=True)
    form = _read(Path(form_path).expanduser().resolve(strict=True))
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(form, Mapping) or form.get("evidence_review_version") != VERSION:
        return {"approved": False, "errors": ["Unsupported or malformed evidence review form"], "warnings": []}
    try:
        ids = _sample_ids(root)
        fingerprints = {sid: sample_fingerprint(root, sid) for sid in ids}
        root_hash = hashlib.sha256(json.dumps(fingerprints, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except Exception as exc:
        return {"approved": False, "errors": [f"Cannot fingerprint current export: {exc}"], "warnings": []}
    if form.get("root_fingerprint") != root_hash:
        errors.append("Root fingerprint is stale or does not match the current export")
    if not _nonblank(form.get("reviewer")):
        errors.append("Reviewer name is required")
    entries = form.get("samples")
    if not isinstance(entries, list):
        return {"approved": False, "errors": errors + ["samples must be a list"], "warnings": warnings}
    by_id = {s.get("sample_id"): s for s in entries if isinstance(s, Mapping)}
    if len(by_id) != len(entries) or set(by_id) != set(ids):
        errors.append("Form must cover every current sample exactly once")
    for sid in ids:
        item = by_id.get(sid)
        if not isinstance(item, Mapping):
            continue
        if item.get("sample_fingerprint") != fingerprints[sid]:
            errors.append(f"{sid}: sample fingerprint is stale")
        public = _read(root / "data" / "input" / f"{sid}.json")
        model = public.get("model_input", {}) if isinstance(public, Mapping) else {}
        if not isinstance(model, Mapping):
            errors.append(f"{sid}: current public model_input is malformed")
            continue
        if not isinstance(model.get("frames"), list) or not model["frames"]:
            errors.append(f"{sid}: public sample has no RGB frames")
        if item.get("source_protocol") != model.get("protocol"):
            errors.append(f"{sid}: declared public protocol was changed")
        if not isinstance(item.get("source_protocol"), str) or not item.get("source_protocol"):
            errors.append(f"{sid}: source protocol is missing")
        form_qs = item.get("questions")
        public_qs = model.get("questions", [])
        expected = [(f"q{i:03d}", q.get("fact_id")) for i, q in enumerate(public_qs, 1) if isinstance(q, Mapping)]
        actual = [(q.get("original_qid"), q.get("fact_id")) for q in form_qs if isinstance(q, Mapping)] if isinstance(form_qs, list) else []
        if actual != expected:
            errors.append(f"{sid}: every targeted original question/fact_id must appear once and in order")
            continue
        public_aliases = {obj.get("alias") for obj in model.get("objects", []) if isinstance(obj, Mapping)}
        for q, original in zip(form_qs, public_qs):
            prefix = f"{sid} {q.get('original_qid')} {q.get('fact_id')}"
            if q.get("subject") != original.get("subject") or q.get("predicate") != original.get("predicate"):
                errors.append(f"{prefix}: public question subject/predicate was altered")
            if q.get("subject") not in public_aliases:
                errors.append(f"{prefix}: question subject is not a public object alias")
            mode = q.get("mode")
            if mode not in MODES:
                errors.append(f"{prefix}: mode must be explicitly assigned")
                continue
            notes = q.get("claim_notes")
            if not isinstance(notes, Mapping) or not all(_nonblank(notes.get(k)) for k in ("before_condition", "event_evidence", "effect_or_preservation_reason")):
                errors.append(f"{prefix}: all three specific claim notes are required")
            refs = q.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                errors.append(f"{prefix}: typed evidence references are required")
                refs = []
            ref_errors = [e for e in (_check_ref(ref, model, sid) for ref in refs) if e]
            if ref_errors:
                errors.extend(f"{prefix}: {e}" for e in ref_errors)
            kinds = [r.get("kind") for r in refs if isinstance(r, Mapping)]
            frame_refs = [r for r in refs if isinstance(r, Mapping) and r.get("kind") == "frame"]
            before_paths = {f.get("path") for f in model.get("frames", []) if isinstance(f, Mapping) and _stage_kind(f.get("stage")) == "before"}
            after_paths = {f.get("path") for f in model.get("frames", []) if isinstance(f, Mapping) and _stage_kind(f.get("stage")) == "after"}
            referenced = {r.get("frame_path") for r in frame_refs}
            if mode == "direct_visual":
                ambiguous = before_paths & after_paths
                if ambiguous:
                    errors.append(f"{prefix}: the same frame path is assigned to both before and after stages: {sorted(ambiguous)}")
                if not before_paths.intersection(referenced) or not after_paths.intersection(referenced):
                    errors.append(f"{prefix}: direct_visual requires relevant before and after stage frames")
                if (q.get("state_discriminability_review") != "pass"
                        or not _nonblank(q.get("calibration_note"))
                        or not _nonblank(q.get("relevant_state_evidence_note"))):
                    errors.append(f"{prefix}: direct_visual requires a passing state discriminability review, calibration, and specific relevant-state visual evidence")
            elif mode == "visual_history_and_rules":
                if not (before_paths.intersection(referenced) and "event" in kinds and "rule" in kinds):
                    errors.append(f"{prefix}: visual_history_and_rules requires a before frame, event, and rule")
                if q.get("state_discriminability_review") == "not_required_inferred":
                    if not _nonblank(q.get("state_discriminability_reason")):
                        errors.append(f"{prefix}: inferred visual state requires a reason")
                elif q.get("state_discriminability_review") != "pass" or not _nonblank(q.get("calibration_note")):
                    errors.append(f"{prefix}: visual state review must pass with calibration, or use reasoned not_required_inferred")
            else:
                if not str(model.get("protocol", "")).startswith("oracle_"):
                    errors.append(f"{prefix}: oracle mode requires an explicitly declared oracle_* source protocol")
                if not ("history_fact" in kinds and "rule" in kinds and "event" in kinds):
                    errors.append(f"{prefix}: oracle mode requires history fact, rule, and event references")
                if not _nonblank(q.get("calibration_not_required_reason")):
                    errors.append(f"{prefix}: oracle mode requires an explicit calibration-not-required reason")
            if q.get("images_readable_and_relevant") is not True:
                errors.append(f"{prefix}: readable, relevant images must be confirmed")
            if q.get("no_unresolved_visual_text_conflict") is not True:
                errors.append(f"{prefix}: unresolved visual/text conflict must be explicitly ruled out")
            if q.get("decision") != "approve":
                errors.append(f"{prefix}: reviewer decision is not approve")
        if len(form_qs) == 0:
            errors.append(f"{sid}: sample has no questions")
    # Exact repeated RGBs are surfaced as an informational condition only.
    hashes: dict[str, list[str]] = defaultdict(list)
    for sid in ids:
        model = _read(root / "data" / "input" / f"{sid}.json").get("model_input", {})
        for frame in model.get("frames", []) if isinstance(model, Mapping) else []:
            if isinstance(frame, Mapping) and isinstance(frame.get("path"), str):
                try:
                    source = _validate_frame_path(root, frame["path"])
                    _png_dimensions(source)
                    hashes[_sha256(source)].append(f"{sid}:{frame['path']}")
                except Exception as exc:
                    errors.append(f"{sid}: invalid RGB {frame['path']}: {exc}")
    for paths in hashes.values():
        if len(paths) > 1:
            warnings.append("Exact duplicate RGB hash (informational): " + ", ".join(paths))
    return {"approved": not errors, "errors": errors, "warnings": warnings, "sample_count": len(ids)}


def check_review(export_root: str | Path, form_path: str | Path) -> dict[str, Any]:
    """Stable integration API used by downstream validation wrappers."""
    result = check(export_root, form_path)
    result["status"] = "approved" if result.get("approved") else "blocked"
    try:
        form = _read(Path(form_path).expanduser().resolve(strict=True))
        result["question_count"] = sum(
            len(sample.get("questions", []))
            for sample in form.get("samples", []) if isinstance(sample, Mapping)
        ) if isinstance(form, Mapping) else 0
    except Exception:
        result["question_count"] = 0
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="prepare private external review packet")
    prep.add_argument("--export-root", type=Path, required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    chk = sub.add_parser("check", help="check a completed evidence review form")
    chk.add_argument("--export-root", type=Path, required=True)
    chk.add_argument("--form", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(args.export_root, args.output_dir) if args.command == "prepare" else check_review(args.export_root, args.form)
    except Exception as exc:
        result = {"approved": False, "errors": [str(exc)], "warnings": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.command == "prepare" and "errors" not in result else (0 if result.get("approved") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
