#!/usr/bin/env python3
"""Selectively collect existing pilot evidence; never starts AI2-THOR."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MAX_SELECTED_PER_PAIR = 5
SUCCESS_VARIANTS = ("A", "B")


class Collector:
    def __init__(self, exports: Path, data_root: Path, output_dir: Path):
        self.exports = exports.resolve()
        self.data_root = data_root.resolve()
        self.output_dir = output_dir.resolve()
        self.files: list[dict] = []
        self.missing: list[dict] = []
        self.selected_attempts: list[dict] = []

    def add(self, source: Path, rel: str, reason: str, required: bool = False) -> None:
        source = source
        if not source.exists() or not source.is_file() or source.is_symlink():
            self.missing.append({"source": str(source), "package_path": rel,
                                 "reason": reason, "required": required})
            return
        target = self.output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"Collecting {source} ({source.stat().st_size} bytes): {reason}", flush=True)
        shutil.copy2(source, target)
        stat = source.stat()
        self.files.append({
            "source": str(source), "package_path": rel, "reason": reason,
            "size_bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })

    def add_matches(self, source_dir: Path, pattern: str, package_dir: str, reason: str) -> list[Path]:
        if not source_dir.is_dir():
            return []
        matches = sorted(p for p in source_dir.glob(pattern) if p.is_file() and not p.is_symlink())
        for path in matches:
            self.add(path, f"{package_dir}/{path.name}", reason)
        return matches


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def error_text(attempt: Path) -> str:
    pieces: list[str] = []
    failure = read_json(attempt / "failure.json")
    for key in ("error", "message", "traceback"):
        value = failure.get(key)
        if isinstance(value, str):
            pieces.append(value)
    check = read_json(attempt / "pair_construction_check.json")
    if check:
        pieces.append(json.dumps(check, ensure_ascii=False))
    return "\n".join(pieces)


def error_signature(text: str) -> str:
    low = text.casefold()
    if "no valid receptacle" in low or "no valid" in low and "view" in low:
        return "no_valid_receptacle_or_view"
    if "spawn area not clear" in low or "can't place object" in low:
        return "spawn_area_collision"
    if "couldn't come to rest" in low or "could not come to rest" in low:
        return "object_not_settling"
    if "parent_plate" in low or "actual_parents" in low:
        return "apple_parent_relation"
    if "temperature_preserved" in low or "roomtemp" in low or "temperature" in low:
        return "temperature_or_preservation"
    if "boundary" in low or "carrying" in low:
        return "carrying_boundary"
    first = next((line.strip() for line in text.splitlines() if line.strip()), "unknown_error")
    return re.sub(r"\s+", " ", first)[:180]


def critical_rank(pair_id: str, text: str) -> int | None:
    low = text.casefold()
    if pair_id == "S05":
        if "temperature_preserved" in low or ("roomtemp" in low and "hot" in low):
            return 0
        if "temperature" in low and ("preserv" in low or "hot" in low):
            return 1
    if pair_id == "P20":
        if "apple_carrying_boundary" in low:
            return 0
        if "parent_plate" in low or "actual_parents" in low:
            return 1
        if "apple" in low and ("parent" in low or "carrying" in low):
            return 2
    return None


def attempt_time(path: Path) -> tuple[int, str]:
    return (int(path.stat().st_mtime_ns), path.name)


def select_attempts(pair_id: str, attempts: list[Path]) -> list[tuple[Path, str]]:
    ordered = sorted(attempts, key=attempt_time)
    selected: dict[Path, str] = {}

    def choose(path: Path, reason: str) -> None:
        if path not in selected and len(selected) < MAX_SELECTED_PER_PAIR:
            selected[path] = reason

    # Keep broad temporal coverage and a mechanically informative attempt.
    if ordered:
        choose(ordered[0], "first chronological attempt: preserves initial failure evidence")
    critical = []
    for path in ordered:
        rank = critical_rank(pair_id, error_text(path))
        if rank is not None:
            critical.append((rank, path))
    if critical:
        rank, path = min(critical, key=lambda item: (item[0], attempt_time(item[1])))
        focus = "temperature_preserved / RoomTemp-to-Hot evidence" if pair_id == "S05" else "Apple carrying / _parent_Plate evidence"
        choose(path, f"mechanism-focused attempt prioritized ({focus})")
    if ordered:
        choose(ordered[-1], "last chronological attempt: captures final observed state")
    signatures: set[str] = set()
    for path in ordered:
        signature = error_signature(error_text(path))
        if signature not in signatures:
            signatures.add(signature)
            choose(path, f"representative failure type: {signature}")
    return list(selected.items())


def collect_successes(collector: Collector) -> None:
    receipts_dir = collector.exports / "pair_receipts"
    receipts: list[Path] = []
    if receipts_dir.is_dir():
        receipts = sorted(p for p in receipts_dir.glob("*.json") if p.is_file() and not p.is_symlink())
    for receipt in receipts:
        collector.add(receipt, f"exports/pair_receipts/{receipt.name}", "generator candidate receipt")
    pair_ids: list[str] = []
    for receipt in receipts:
        item = read_json(receipt)
        pair_id = item.get("pair_id") or receipt.stem
        if isinstance(pair_id, str) and re.fullmatch(r"[A-Z][0-9]{2}", pair_id):
            pair_ids.append(pair_id)
    for pair_id in sorted(set(pair_ids)):
        for variant in SUCCESS_VARIANTS:
            name = f"{pair_id}_{variant}.json"
            collector.add(collector.exports / "data" / "input" / name,
                          f"exports/data/input/{name}", "published successful sample: public model input", required=True)
            collector.add(collector.exports / "hidden_gold" / name,
                          f"exports/hidden_gold/{name}", "published successful sample: private hidden gold for audit only", required=True)
        for path in sorted((collector.exports / "data" / "media").glob(f"{pair_id}_*_rgb.png")):
            collector.add(path, f"exports/data/media/{path.name}", "published sample RGB frame; instance/depth images excluded")
        for path in sorted((collector.exports / "private_logs").glob(f"{pair_id}_*_setup.json")):
            collector.add(path, f"exports/private_logs/{path.name}", "successful candidate setup actions; placement audit")


def collect_attempts(collector: Collector) -> None:
    attempts_root = collector.exports / "_attempts"
    if not attempts_root.is_dir():
        return
    summary = read_json(collector.exports / "generation_summary.json")
    statuses = {entry.get("pair_id"): entry.get("status")
                for entry in summary.get("pairs", []) if isinstance(entry, dict)}
    receipt_ids = {p.stem for p in (collector.exports / "pair_receipts").glob("*.json")}
    for pair_dir in sorted(p for p in attempts_root.iterdir() if p.is_dir() and not p.is_symlink()):
        pair_id = pair_dir.name
        attempts = sorted(p for p in pair_dir.iterdir() if p.is_dir() and not p.is_symlink())
        for attempt in attempts:
            failure = attempt / "failure.json"
            if failure.is_file() and not failure.is_symlink():
                collector.add(failure, f"exports/_attempts/{pair_id}/{attempt.name}/failure.json",
                              "all-attempt failure summary; included without full action log")
        is_failed_pair = statuses.get(pair_id) == "construction_failed" or (
            pair_id not in statuses and pair_id not in receipt_ids
        )
        if not is_failed_pair:
            continue
        chosen = select_attempts(pair_id, attempts)
        for attempt, reason in chosen:
            collector.selected_attempts.append({"pair_id": pair_id, "attempt_id": attempt.name, "reason": reason,
                                                "failure": read_json(attempt / "failure.json").get("error", "")})
            base = f"exports/_attempts/{pair_id}/{attempt.name}"
            for path in sorted(attempt.glob("*_action_log.json")):
                collector.add(path, f"{base}/{path.name}", f"selected attempt action log: {reason}")
            for path in sorted(attempt.glob("*_failure_context.json")):
                collector.add(path, f"{base}/{path.name}", f"selected attempt raw failure snapshots, if available: {reason}")
            check = attempt / "pair_construction_check.json"
            if check.is_file():
                collector.add(check, f"{base}/pair_construction_check.json", f"selected attempt pair check: {reason}")
            for subdir, package_subdir, pattern, desc in (
                ("data/input", "data/input", f"{pair_id}_*.json", "selected attempt public input (A/B when generated)"),
                ("hidden_gold", "hidden_gold", f"{pair_id}_*.json", "selected attempt hidden metadata (A/B when generated)"),
                ("data/media", "data/media", f"{pair_id}_*_rgb.png", "selected attempt before/after RGB frames only"),
            ):
                source_dir = attempt / subdir
                if source_dir.is_dir():
                    for path in sorted(source_dir.glob(pattern)):
                        collector.add(path, f"{base}/{package_subdir}/{path.name}", f"{desc}: {reason}")


def add_general_evidence(collector: Collector) -> None:
    collector.add(collector.exports / "generation_summary.json", "exports/generation_summary.json",
                  "complete generation result summary", required=True)
    collector.add(collector.exports / "specs.json", "exports/specs.json", "spec snapshot used for generation")
    if not (collector.exports / "specs.json").is_file():
        collector.add(collector.exports.parent / "specs.json", "source_specs.json", "source design spec fallback")

    logs_dir = collector.data_root / "logs"
    for suffix, label in (("_04_generate_pilot.log", "full raw 04 generation log"),
                          ("_04b_inspect_pilot.log", "full raw 04b validation log")):
        matches = sorted(p for p in logs_dir.glob(f"*{suffix}") if p.is_file() and not p.is_symlink())
        if matches:
            collector.add(matches[-1], f"logs/{matches[-1].name}", f"latest stage-matched {label}", required=True)
        else:
            collector.missing.append({"source": str(logs_dir / f"*{suffix}"), "reason": f"required {label} not found"})

    review_forms = sorted(p for p in collector.data_root.glob("review_form*.json") if p.is_file() and not p.is_symlink())
    if review_forms:
        collector.add(review_forms[-1], f"review/{review_forms[-1].name}", "latest human review form; checks preserved unchanged")
    else:
        collector.missing.append({"source": str(collector.data_root / "review_form*.json"), "reason": "review form not found"})

    smoke = collector.data_root / "smoke"
    for name, reason in (("report.json", "smoke report"), ("scene_rgb.png", "smoke RGB frame"),
                         ("failure.json", "smoke failure details when present")):
        collector.add(smoke / name, f"smoke/{name}", reason)


def write_manifest(collector: Collector) -> Path:
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "export_root": str(collector.exports), "data_root": str(collector.data_root),
        "selection_policy": {
            "successful_pairs": "all pair_receipts; copy A/B public input, hidden_gold, RGB, and private setup logs",
            "failed_attempts": f"all failure.json summaries; at most {MAX_SELECTED_PER_PAIR} full evidence attempts per pair",
            "attempt_priority": "first, mechanism-focused (S05 temperature / P20 Apple parent), last, then distinct failure signatures",
            "excluded": "unity_cache, build ZIPs, instance/depth imagery, and unselected full action logs",
            "privacy": "hidden_gold is included for this debugging review; do not supply this bundle to the evaluated model as task input",
        },
        "selected_attempts": collector.selected_attempts,
        "missing_or_unavailable": collector.missing,
        "files": collector.files,
        "manifest_note": "This manifest lists all copied source files; it does not list itself or the resulting archive.",
    }
    path = collector.output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def archive_directory(root: Path, destination: Path) -> None:
    files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    total = sum(p.stat().st_size for p in files)
    started = time.monotonic()
    temp = destination.with_suffix(destination.suffix + ".partial")
    done = 0
    last_report = started
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zf:
        for path in files:
            rel = path.relative_to(root)
            # Passing the name lets ZipFile apply its configured compression
            # level; explicit ZipInfo would otherwise use the zlib default.
            with path.open("rb") as src, zf.open(rel.as_posix(), "w", force_zip64=True) as dst:
                while True:
                    chunk = src.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    done += len(chunk)
                    if time.monotonic() - last_report >= 10:
                        pct = 100 if total == 0 else done * 100 // total
                        print(f"Archive progress: {done}/{total} source bytes ({pct}%)", flush=True)
                        last_report = time.monotonic()
    os.replace(temp, destination)
    print(f"Archive completed in {time.monotonic() - started:.1f}s; {len(files)} files, {total} source bytes.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    exports = args.export_root.expanduser().resolve(strict=True)
    data_root = args.data_root.expanduser().resolve(strict=True)
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(f"Output directory must be new or empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    collector = Collector(exports, data_root, output_dir)
    add_general_evidence(collector)
    collect_successes(collector)
    collect_attempts(collector)
    write_manifest(collector)
    destination = output_dir.parent / f"{output_dir.name}.zip"
    archive_directory(output_dir, destination)
    print(f"Evidence directory: {output_dir}", flush=True)
    print(f"Upload package: {destination}", flush=True)
    if collector.missing:
        print(f"Some requested evidence was unavailable; see manifest.json ({len(collector.missing)} entries).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
