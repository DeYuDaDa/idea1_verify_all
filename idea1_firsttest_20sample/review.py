"""Create and apply human review forms for simulator candidate records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sample_fingerprint(root: str | Path, sample_id: str) -> str:
    root_path = Path(root)
    public = _read(root_path / "data" / "input" / f"{sample_id}.json")
    hidden = _read(root_path / "hidden_gold" / f"{sample_id}.json")
    model_input = public.get("model_input", {}) if isinstance(public, Mapping) else {}
    frames = model_input.get("frames", []) if isinstance(model_input, Mapping) else []
    media_root = (root_path / "data" / "media").resolve()
    frame_hashes = {}
    for frame in frames or []:
        if not isinstance(frame, Mapping) or not frame.get("path"):
            raise ValueError(f"Invalid media frame reference for {sample_id}")
        relative = Path(str(frame["path"]))
        if relative.is_absolute():
            raise ValueError(f"Media path must be relative to the dataset root: {relative}")
        candidate = (root_path / relative).resolve()
        try:
            candidate.relative_to(media_root)
        except ValueError as exc:
            raise ValueError(f"Media path is outside data/media: {relative}") from exc
        if not candidate.is_file():
            raise ValueError(f"Media frame is missing: {relative}")
        frame_hashes[relative.as_posix()] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return _canonical_hash({"public": public, "hidden": hidden, "frame_sha256": frame_hashes})


def _sample_ids(root: Path) -> list[str]:
    public_dir, hidden_dir = root / "data" / "input", root / "hidden_gold"
    public = {path.stem for path in public_dir.glob("*.json")} if public_dir.exists() else set()
    hidden = {path.stem for path in hidden_dir.glob("*.json")} if hidden_dir.exists() else set()
    ids = sorted(public & hidden)
    if not ids:
        raise ValueError("No matching public and hidden sample records were found")
    pairs = sorted({sample_id.rsplit("_", 1)[0] for sample_id in ids})
    incomplete = [pair for pair in pairs if f"{pair}_A" not in ids or f"{pair}_B" not in ids]
    if incomplete:
        raise ValueError("Review requires both variants for each pair: " + ", ".join(incomplete))
    return ids


def _root_fingerprint(root: Path, sample_ids: list[str]) -> tuple[str, dict[str, str]]:
    fingerprints = {sample_id: sample_fingerprint(root, sample_id) for sample_id in sample_ids}
    return _canonical_hash(fingerprints), fingerprints


def create_template(root: str | Path, output: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    output_path = Path(output)
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing review form: {output_path}")
    try:
        output_path.resolve().relative_to(root_path.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("Review form output must be outside the dataset root")
    sample_ids = _sample_ids(root_path)
    root_hash, hashes = _root_fingerprint(root_path, sample_ids)
    entries = []
    for sample_id in sample_ids:
        public = _read(root_path / "data" / "input" / f"{sample_id}.json")
        model_input = public.get("model_input", {}) if isinstance(public, Mapping) else {}
        frames = model_input.get("frames", []) if isinstance(model_input, Mapping) else []
        entries.append({
            "sample_id": sample_id,
            "sample_fingerprint": hashes[sample_id],
            "frame_paths": [frame.get("path") for frame in frames if isinstance(frame, Mapping) and frame.get("path")],
            "checks": {
                "visual_evidence_confirmed": False,
                "initial_controls_confirmed": False,
                "knowledge_protocol_confirmed": False,
            },
        })
    form = {
        "review_form_version": 1,
        "root_fingerprint": root_hash,
        "samples": entries,
        "reviewer": "",
        "instructions": "Inspect the referenced frames and public history/rules. Confirm all three checks for every sample; do not alter simulator metadata.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(form, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return form


def apply_review(root: str | Path, form_path: str | Path, reviewer: str) -> Path:
    root_path = Path(root)
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer must be a non-empty name")
    form = _read(Path(form_path))
    if not isinstance(form, Mapping) or form.get("review_form_version") != 1:
        raise ValueError("Unsupported review form")
    sample_ids = _sample_ids(root_path)
    root_hash, hashes = _root_fingerprint(root_path, sample_ids)
    if form.get("root_fingerprint") != root_hash:
        raise ValueError("Review form does not match the current public/hidden records")
    form_items = form.get("samples", [])
    if not isinstance(form_items, list):
        raise ValueError("Review form samples must be a list")
    decisions = {str(item.get("sample_id")): item for item in form_items if isinstance(item, Mapping)}
    if len(decisions) != len(form_items) or set(decisions) != set(sample_ids):
        raise ValueError("Review form must contain every current sample exactly once")
    samples = {}
    required = ("visual_evidence_confirmed", "initial_controls_confirmed", "knowledge_protocol_confirmed")
    for sample_id in sample_ids:
        item = decisions[sample_id]
        if item.get("sample_fingerprint") != hashes[sample_id]:
            raise ValueError(f"Stale fingerprint for {sample_id}")
        checks = item.get("checks", {})
        approved = isinstance(checks, Mapping) and all(checks.get(key) is True for key in required)
        if not approved:
            raise ValueError(f"All review checks are required for {sample_id}")
        samples[sample_id] = {
            "sample_fingerprint": hashes[sample_id],
            "visual_evidence_confirmed": True,
            "initial_controls_confirmed": True,
            "knowledge_protocol_confirmed": True,
            "approved": True,
        }
    record = {
        "review_record_version": 1,
        "reviewer": reviewer,
        "root_fingerprint": root_hash,
        "samples": samples,
    }
    output = root_path / "review_records.json"
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Dataset candidate root")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--template", type=Path, help="Write an external review form to this path")
    action.add_argument("--apply", type=Path, help="Apply a completed review form")
    parser.add_argument("--reviewer", help="Reviewer name (required with --apply)")
    args = parser.parse_args()
    if args.template:
        create_template(args.root, args.template)
    else:
        if not args.reviewer:
            parser.error("--reviewer is required with --apply")
        print(apply_review(args.root, args.apply, args.reviewer))


if __name__ == "__main__":
    main()
