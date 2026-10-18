#!/usr/bin/env python3
"""Stage selected existing data/cache onto the data disk and inspect Qwen metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BUILD = "thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917"
EXPECTED_BUILD_SIZE = 835983275
EXPECTED_BUILD_SHA256 = "1fd5f998644a6dd522a4cf6604c05360a75a5c27f450a7486c20e52dc2b67bb9"
MODEL_FIELDS = (
    "model_type", "vocab_size", "hidden_size", "intermediate_size", "num_hidden_layers",
    "num_attention_heads", "num_key_value_heads", "max_position_embeddings", "image_size",
    "patch_size", "vision_start_token_id", "vision_end_token_id", "image_token_id",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, base: Path) -> dict:
    st = path.stat()
    return {"path": str(path.relative_to(base)), "size_bytes": st.st_size,
            "mtime_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
            "sha256": sha256(path)}


def cache_check(old_root: Path) -> tuple[Path, Path, dict]:
    cache = old_root / "unity_cache" / "releases" / BUILD
    receipt_path = old_root / "thor_build_receipts" / f"{BUILD}.json"
    exe = cache / BUILD
    data_dir = cache / f"{BUILD}_Data"
    if not cache.is_dir() or exe.is_symlink() or not exe.is_file() or exe.stat().st_size <= 0 or not os.access(exe, os.X_OK):
        raise ValueError(f"Old CloudRendering cache lacks a non-empty executable: {exe}")
    if data_dir.is_symlink() or not data_dir.is_dir() or not any(data_dir.iterdir()):
        raise ValueError(f"Old CloudRendering cache lacks non-empty Unity Data: {data_dir}")
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError(f"Verified build receipt is missing: {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("commit") != BUILD.rsplit("-", 1)[1]
            or receipt.get("platform") != "CloudRendering"
            or receipt.get("archive_size_bytes") != EXPECTED_BUILD_SIZE
            or receipt.get("sha256") != EXPECTED_BUILD_SHA256
            or "official-sidecar SHA-256" not in str(receipt.get("verification", ""))):
        raise ValueError(f"Build receipt does not match the expected verified CloudRendering build: {receipt_path}")
    recorded_cache_value = receipt.get("installed_cache")
    recorded_cache = Path(str(recorded_cache_value)) if recorded_cache_value else None
    if recorded_cache is not None and recorded_cache.resolve() != cache.resolve():
        raise ValueError(f"Build receipt names a different cache path: {recorded_cache}")
    return cache, receipt_path, receipt


def select_export_files(exports: Path) -> tuple[list[tuple[Path, Path, str]], list[str]]:
    receipt_dir = exports / "pair_receipts"
    receipts = sorted(p for p in receipt_dir.glob("*.json") if p.is_file() and not p.is_symlink()) if receipt_dir.is_dir() else []
    if not receipts:
        raise ValueError(f"No existing successful pair receipts found: {receipt_dir}")
    files: list[tuple[Path, Path, str]] = []
    pair_ids: list[str] = []

    def add(source: Path, relative: Path, reason: str, required: bool = True) -> None:
        if source.is_symlink() or not source.is_file():
            if required:
                raise FileNotFoundError(f"Required candidate file missing: {source}")
            return
        files.append((source, relative, reason))

    add(exports / "generation_summary.json", Path("exports/generation_summary.json"), "pilot generation summary")
    add(exports / "specs.json", Path("exports/specs.json"), "design specs snapshot")
    for receipt in receipts:
        record = json.loads(receipt.read_text(encoding="utf-8"))
        pair_id = record.get("pair_id") or receipt.stem
        if not isinstance(pair_id, str) or not re.fullmatch(r"[A-Z][0-9]{2}", pair_id):
            raise ValueError(f"Invalid pair receipt id in {receipt}")
        if record.get("status") not in (None, "simulator_checks_passed_pending_review"):
            raise ValueError(f"Refusing to copy non-candidate receipt: {receipt}")
        pair_ids.append(pair_id)
        add(receipt, Path("exports/pair_receipts") / receipt.name, "successful candidate receipt")
        for variant in ("A", "B"):
            filename = f"{pair_id}_{variant}.json"
            add(exports / "data" / "input" / filename, Path("exports/data/input") / filename,
                f"successful sample {pair_id}/{variant}: public input")
            add(exports / "hidden_gold" / filename, Path("exports/hidden_gold") / filename,
                f"successful sample {pair_id}/{variant}: hidden audit metadata")
        setup = sorted((exports / "private_logs").glob(f"{pair_id}_*_setup.json"))
        if not setup:
            raise FileNotFoundError(f"No setup action logs for successful pair {pair_id}")
        for path in setup:
            add(path, Path("exports/private_logs") / path.name, f"successful pair {pair_id}: setup actions")
        media = sorted((exports / "data" / "media").glob(f"{pair_id}_*_rgb.png"))
        if not media:
            raise FileNotFoundError(f"No RGB media for successful pair {pair_id}")
        for path in media:
            add(path, Path("exports/data/media") / path.name, f"successful pair {pair_id}: RGB only")
    return files, sorted(set(pair_ids))


def collect_reviews(old_root: Path) -> list[tuple[Path, Path, str]]:
    found: list[tuple[Path, Path, str]] = []
    for relative_dir in (Path("."), Path("review")):
        folder = old_root / relative_dir
        if folder.is_dir():
            for path in sorted(p for p in folder.glob("review_form*.json") if p.is_file() and not p.is_symlink()):
                bucket = "root" if relative_dir == Path(".") else "review"
                found.append((path, Path("review_forms") / bucket / path.name,
                              f"preserved review form from {bucket}; checks not changed"))
    return found


def disk_record(path: Path) -> dict:
    usage = shutil.disk_usage(path)
    return {"path": str(path), "total_bytes": usage.total, "used_bytes": usage.used,
            "free_bytes": usage.free, "free_gib": round(usage.free / (1024 ** 3), 2)}


def model_metadata(model_dir: Path) -> dict:
    result: dict = {"model_dir": str(model_dir), "directory_exists": model_dir.is_dir(),
                    "weights_read": False}
    config_path = model_dir / "config.json"
    result["config_exists"] = config_path.is_file()
    result["config_is_symlink"] = config_path.is_symlink()
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            def selected(obj: dict) -> dict:
                return {key: obj[key] for key in MODEL_FIELDS if key in obj and not isinstance(obj[key], (dict, list))}
            result["config"] = {
                "model_type": config.get("model_type"),
                "architectures": config.get("architectures"),
                "vision_config": selected(config.get("vision_config", {})) if isinstance(config.get("vision_config"), dict) else None,
                "text_config": selected(config.get("text_config", {})) if isinstance(config.get("text_config"), dict) else None,
            }
        except Exception as exc:
            result["config_error"] = f"{type(exc).__name__}: {exc}"
    safetensors = sorted(p for p in model_dir.rglob("*.safetensors") if p.is_file()) if model_dir.is_dir() else []
    indexes = sorted(p for p in model_dir.rglob("*.safetensors.index.json") if p.is_file()) if model_dir.is_dir() else []
    result["safetensors"] = {"present": bool(safetensors), "count": len(safetensors),
                             "files": [{"name": str(p.relative_to(model_dir)), "size_bytes": p.stat().st_size,
                                        "is_symlink": p.is_symlink()} for p in safetensors]}
    result["safetensors_indexes"] = {"present": bool(indexes), "files": [
        {"name": str(p.relative_to(model_dir)), "is_symlink": p.is_symlink()} for p in indexes]}
    return result


RUNTIME_PROBE = r'''import importlib.metadata as md, json
r={"python_version":__import__("sys").version.split()[0]}
try:
 import torch
 r["pytorch_version"]=torch.__version__
 try:
  r["cuda_available"]=bool(torch.cuda.is_available())
  r["cuda_device_count"]=int(torch.cuda.device_count())
  r["cuda_device_names"]=[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
 except Exception as e: r["gpu_probe_error"]=type(e).__name__+": "+str(e)
except Exception as e: r["pytorch_error"]=type(e).__name__+": "+str(e)
try:
 r["transformers_version"]=md.version("transformers")
 from transformers import AutoModelForImageTextToText
 r["AutoModelForImageTextToText_supported"]=True
except Exception as e:
 r["AutoModelForImageTextToText_supported"]=False
 r["transformers_error"]=type(e).__name__+": "+str(e)
print(json.dumps(r,ensure_ascii=False))
'''


def runtime_probe(conda_exe: str, env_name: str) -> dict:
    result: dict = {"environment": env_name, "packages_installed": False, "probe_only": True}
    try:
        proc = subprocess.run([conda_exe, "run", "--no-capture-output", "-n", env_name,
                               "python", "-c", RUNTIME_PROBE], capture_output=True, text=True, timeout=120)
        result["returncode"] = proc.returncode
        if proc.returncode == 0:
            lines = [line for line in proc.stdout.splitlines() if line.strip()]
            parsed = json.loads(lines[-1]) if lines else {}
            result.update(parsed)
        else:
            result["environment_error"] = (proc.stderr or proc.stdout)[-4000:]
    except Exception as exc:
        result["environment_error"] = f"{type(exc).__name__}: {exc}"
    return result


def copy_file(source: Path, dest: Path, progress: dict) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Staging {source} ({source.stat().st_size} bytes)", flush=True)
    digest = hashlib.sha256()
    copied = 0
    last = time.monotonic()
    with source.open("rb") as src, dest.open("xb") as out:
        while True:
            block = src.read(8 * 1024 * 1024)
            if not block:
                break
            out.write(block)
            digest.update(block)
            copied += len(block)
            progress["bytes"] += len(block)
            if time.monotonic() - progress["last_report"] >= 10:
                print(f"Copy progress: {progress['bytes']}/{progress['total']} bytes", flush=True)
                progress["last_report"] = time.monotonic()
    shutil.copystat(source, dest, follow_symlinks=False)
    if copied != source.stat().st_size:
        raise IOError(f"Copy size mismatch for {source}: {copied} bytes")
    return {"size_bytes": copied, "sha256": digest.hexdigest()}


def install_stage(stage: Path, target: Path, manifest: list[dict]) -> None:
    # Preflight all collisions before installing anything. Existing identical files
    # are idempotent; differing files are never overwritten.
    for record in manifest:
        relative = Path(record["relative_path"])
        staged = stage / relative
        dest = target / relative
        parent = dest.parent
        while parent != target and target in parent.parents:
            if parent.exists() and (not parent.is_dir() or parent.is_symlink()):
                raise FileExistsError(f"Target parent path conflict; preserved: {parent}")
            parent = parent.parent
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() or not dest.is_file() or sha256(dest) != record["sha256"]:
                raise FileExistsError(f"Content conflict; preserved existing target: {dest}")
    target.mkdir(parents=True, exist_ok=True)
    for record in manifest:
        relative = Path(record["relative_path"])
        staged = stage / relative
        dest = target / relative
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(staged, dest)
        except FileExistsError:
            if dest.is_file() and not dest.is_symlink() and sha256(dest) == record["sha256"]:
                continue
            raise FileExistsError(f"Concurrent target conflict; preserved: {dest}")
        except OSError as exc:
            raise OSError(f"Atomic hard-link install failed for {dest}: {exc}") from exc


def write_env_file(stage: Path, target_root: Path) -> None:
    paths = {
        "HF_HOME": target_root / "hf_home",
        "HF_HUB_CACHE": target_root / "hf_home" / "hub",
        "TRANSFORMERS_CACHE": target_root / "hf_home" / "transformers",
        "PIP_CACHE_DIR": target_root / "pip_cache",
        "TMPDIR": target_root / "tmp",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    lines = ["# Source before future model/cache commands; no global or HOME change."]
    for key, value in paths.items():
        lines.append(f"export {key}={shlex.quote(str(value))}")
    (stage / "model_env.sh").write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare(args: argparse.Namespace) -> dict:
    old_root = args.old_data_root.resolve(strict=True)
    target = args.target_root.resolve()
    if old_root == target or old_root in target.parents or target in old_root.parents:
        raise ValueError("OLD_DATA_ROOT and new DATA_ROOT must be distinct, non-nested directories")
    if not target.parent.is_dir():
        raise FileNotFoundError(f"New data-disk parent directory does not exist: {target.parent}")
    if not old_root.is_dir():
        raise FileNotFoundError(f"OLD_DATA_ROOT is not a directory: {old_root}")

    exports = old_root / "exports"
    candidate_files, pair_ids = select_export_files(exports)
    review_files = collect_reviews(old_root)
    cache, cache_receipt, receipt_data = cache_check(old_root)
    files = candidate_files + review_files
    files.append((cache_receipt, Path("thor_build_receipts") / cache_receipt.name, "verified CloudRendering cache receipt"))
    for source in sorted(p for p in cache.rglob("*") if p.is_file() and not p.is_symlink()):
        files.append((source, Path("unity_cache") / source.relative_to(old_root / "unity_cache"), "validated CloudRendering build file"))
    unique: dict[str, tuple[Path, Path, str]] = {}
    for entry in files:
        rel = entry[1].as_posix()
        if rel in unique and unique[rel][0] != entry[0]:
            raise ValueError(f"Duplicate planned destination: {rel}")
        unique[rel] = entry
    files = list(unique.values())
    estimate = sum(src.stat().st_size for src, _, _ in files)

    model_dir = args.model_dir.resolve()
    model_info = model_metadata(model_dir)
    model_runtime = runtime_probe(args.conda_exe, args.model_env)
    disk_before = {"old_root": disk_record(old_root), "target_parent": disk_record(target.parent)}
    target.mkdir(parents=True, exist_ok=True)
    report_dir = target / "transfer_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{args.timestamp}_{os.getpid()}_data_disk_model.json"
    report: dict = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "old_data_root": str(old_root), "new_data_root": str(target),
        "source_export_root": str(exports), "candidate_pairs": pair_ids,
        "selected_export_files": len(candidate_files),
        "cache": {"source": str(cache), "receipt": str(cache_receipt), "receipt_record": receipt_data},
        "cache_path_mapping": {"receipt_installed_cache_original": str(cache),
                               "new_data_disk_cache": str(target / "unity_cache" / "releases" / BUILD),
                               "receipt_copied_verbatim": True},
        "estimated_copy_bytes": estimate, "model": model_info,
        "inference_environment_probe": model_runtime,
        "disk_before": disk_before,
        "cache_paths_on_data_disk": {
            "HF_HOME": str(target / "hf_home"), "HF_HUB_CACHE": str(target / "hf_home" / "hub"),
            "TRANSFORMERS_CACHE": str(target / "hf_home" / "transformers"),
            "PIP_CACHE_DIR": str(target / "pip_cache"), "TMPDIR": str(target / "tmp"),
            "environment_file": str(target / "model_env.sh"),
        },
        "weights_read": False, "model_loaded": False, "packages_installed": False,
    }

    free = shutil.disk_usage(target.parent).free
    reserve = max(512 * 1024**2, estimate // 10)
    report["disk_space_check"] = {"required_estimate_bytes": estimate, "safety_reserve_bytes": reserve,
                                  "available_bytes": free, "sufficient": free >= estimate + reserve}
    if free < estimate + reserve:
        report["transfer_status"] = "insufficient_space"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"Not enough free space for staging. Report: {report_path}")

    target.mkdir(parents=True, exist_ok=True)
    # Existing target files must either be identical or absent; no overwrite.
    target_manifest = []
    for source, rel, reason in files:
        target_path = target / rel
        if target_path.exists() or target_path.is_symlink():
            if target_path.is_symlink() or not target_path.is_file():
                report["transfer_status"] = "target_conflict"
                report["conflict"] = str(target_path)
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                raise FileExistsError(f"Target path conflict, preserved: {target_path}; report: {report_path}")
            actual = sha256(target_path)
            expected = sha256(source)
            if actual != expected:
                report["transfer_status"] = "target_conflict"
                report["conflict"] = {"path": str(target_path), "expected_sha256": expected, "actual_sha256": actual}
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                raise FileExistsError(f"Target content differs; preserved: {target_path}; report: {report_path}")
        target_manifest.append({"source": str(source), "relative_path": rel.as_posix(), "reason": reason,
                                "size_bytes": source.stat().st_size, "sha256": sha256(source)})
    report["planned_files"] = target_manifest
    already_complete = all((target / row["relative_path"]).is_file()
                           and sha256(target / row["relative_path"]) == row["sha256"] for row in target_manifest)
    if already_complete:
        report["transfer_status"] = "already_identical"
    else:
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=target.parent))
        report["staging_path"] = str(stage)
        progress = {"bytes": 0, "total": estimate, "last_report": time.monotonic()}
        try:
            staged_manifest: list[dict] = []
            for source, relative, reason in files:
                meta = copy_file(source, stage / relative, progress)
                staged_manifest.append({"relative_path": relative.as_posix(), "reason": reason, **meta})
            write_env_file(stage, target)
            env_file = stage / "model_env.sh"
            staged_manifest.append({"relative_path": "model_env.sh", "reason": "data-disk cache environment helper",
                                    "size_bytes": env_file.stat().st_size, "sha256": sha256(env_file)})
            install_stage(stage, target, staged_manifest)
            report["transfer_status"] = "installed_or_identical_files"
            # Remove only this invocation's temporary staging tree after successful install.
            shutil.rmtree(stage)
        except Exception:
            report["transfer_status"] = "staging_or_install_failed"
            report["staging_preserved"] = str(stage)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise

    for subdir in ("hf_home", "pip_cache", "tmp", "model_outputs"):
        path = target / subdir
        if path.exists() and not path.is_dir():
            raise FileExistsError(f"Data-disk workspace path is not a directory; preserved: {path}")
        path.mkdir(parents=True, exist_ok=True)
    env_path = target / "model_env.sh"
    # Rewrite only when absent or identical; an existing differing helper is protected.
    env_content = "# Source before future model/cache commands; no global or HOME change.\n"
    env_values = {"HF_HOME": target / "hf_home", "HF_HUB_CACHE": target / "hf_home" / "hub",
                  "TRANSFORMERS_CACHE": target / "hf_home" / "transformers", "PIP_CACHE_DIR": target / "pip_cache",
                  "TMPDIR": target / "tmp"}
    env_content += "".join(f"export {key}={shlex.quote(str(value))}\n" for key, value in env_values.items())
    if env_path.exists():
        if env_path.read_text(encoding="utf-8") != env_content:
            raise FileExistsError(f"Existing model_env.sh differs; preserved: {env_path}")
    else:
        env_stage = target / f".model_env.sh.{args.timestamp}.{os.getpid()}.tmp"
        with env_stage.open("x", encoding="utf-8") as stream:
            stream.write(env_content)
        os.link(env_stage, env_path)
        env_stage.unlink()

    report["disk_after"] = {"old_root": disk_record(old_root), "target_parent": disk_record(target.parent),
                            "new_data_root": disk_record(target)}
    report["target_env_file"] = str(env_path)
    report["transfer_status"] = report.get("transfer_status", "installed_or_identical_files")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Transfer report: {report_path}", flush=True)
    print(f"New data root: {target}", flush=True)
    print(f"Model cache environment: source {env_path}", flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-data-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--conda-exe", required=True)
    parser.add_argument("--model-env", required=True)
    parser.add_argument("--timestamp", required=True)
    args = parser.parse_args()
    try:
        report = prepare(args)
        print(json.dumps({"transfer_status": report["transfer_status"],
                          "candidate_pairs": report["candidate_pairs"],
                          "estimated_copy_bytes": report["estimated_copy_bytes"],
                          "model_probe": report["inference_environment_probe"]}, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
