#!/usr/bin/env python3
"""Collect existing current-run artifacts into one small audit ZIP; never runs workloads."""
import argparse
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--export-root", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    root = args.data_root.resolve()
    missing, selected = [], {}
    files = {}

    def add(path, label):
        path = Path(path)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            missing.append(label)
            return
        if not resolved.is_file():
            missing.append(label)
            return
        files[resolved] = resolved.relative_to(root).as_posix()

    if args.export_root:
        export = args.export_root.resolve()
        try:
            export.relative_to(root)
        except ValueError:
            parser.error("--export-root must be inside DATA_ROOT")
        if not export.is_dir():
            parser.error(f"export root does not exist: {export}")
    else:
        candidates = sorted((p for p in root.glob("exports_scope_v2_*") if p.is_dir()),
                            key=lambda p: p.name)
        export = candidates[-1] if candidates else None
    selected["export_root"] = str(export) if export else None
    if export:
        add(export / "generation_summary.json", "current export generation_summary.json")
        for path in sorted((export / "_run").glob("*.json")):
            add(path, "current export _run JSON: " + path.name)
        add(root / "pilot_evidence" / (export.name + ".zip"), "pilot_evidence/current-export.zip")
    else:
        missing.extend(["latest exports_scope_v2_* directory", "current export generation_summary.json",
                        "current export _run JSON", "pilot_evidence/current-export.zip"])

    report_dir = root / "transfer_reports"
    reports = sorted(report_dir.glob("*_19_model_env_report.json"), key=lambda p: p.name)
    report = reports[-1] if reports else None
    add(report, "latest *_19_model_env_report.json") if report else missing.append("latest *_19_model_env_report.json")
    selected["env_report"] = report.name if report else None
    env_status = None
    if report:
        try:
            env_status = json.loads(report.read_text(encoding="utf-8")).get("status")
        except Exception as exc:
            env_status = "unreadable: " + type(exc).__name__
    selected["envstatus"] = env_status

    evidence_dir = root / "model_setup_evidence"
    bundles = sorted(evidence_dir.glob("*19*.tar.gz"), key=lambda p: p.name)
    bundle = bundles[-1] if bundles else None
    add(bundle, "latest model_setup_evidence/*19*.tar.gz") if bundle else missing.append("latest model_setup_evidence/*19*.tar.gz")
    selected["model_setup_bundle"] = bundle.name if bundle else None

    logs = root / "logs"
    for step in (19, 20, 21, 22):
        candidates = sorted(logs.glob(f"*_{step}_*.log"), key=lambda p: (p.stat().st_mtime_ns, p.name))
        if candidates:
            add(candidates[-1], f"latest {step} log")
        else:
            missing.append(f"latest {step} log")
    camera = sorted(logs.glob("*_camera_probe_bundle.zip"), key=lambda p: (p.stat().st_mtime_ns, p.name))
    if camera:
        add(camera[-1], "latest camera_probe_bundle.zip")
    else:
        missing.append("latest camera_probe_bundle.zip")
    selected["camera_bundle"] = camera[-1].name if camera else None
    if args.log:
        add(args.log, "this collector operation log")

    outputs = root / "model_outputs"
    runs = sorted((p for p in outputs.glob("run_*") if p.is_dir()), key=lambda p: p.name)
    prediction_stats = []
    model_manifest_status = []
    if not runs:
        missing.append("model_outputs/run_* directories")
    for run in runs:
        manifest = run / "run_manifest.json"
        predictions = run / "predictions.jsonl"
        add(manifest, f"{run.name}/run_manifest.json")
        add(predictions, f"{run.name}/predictions.jsonl")
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                model_manifest_status.append({"run": run.name, "status": data.get("status"),
                                              "selected_sample_count": len(data.get("samples", [])),
                                              "completed_sample_count": len(data.get("completed_samples", []))})
            except Exception as exc:
                model_manifest_status.append({"run": run.name, "status": "unreadable: " + type(exc).__name__})
        if predictions.is_file():
            raw = predictions.read_bytes()
            prediction_stats.append({"run": run.name, "bytes": len(raw),
                                     "nonempty_lines": sum(bool(line.strip()) for line in raw.splitlines())})
        else:
            prediction_stats.append({"run": run.name, "bytes": None, "nonempty_lines": None})

    selected["modelmanifeststatus"] = model_manifest_status
    selected["prediction_stats"] = prediction_stats
    entries = [{"path": arc, "bytes": path.stat().st_size, "sha256": sha256(path)}
               for path, arc in sorted(files.items(), key=lambda item: item[1])]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = root / "logs" / f"{stamp}_{os.getpid()}_24_current_audit.zip"
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "selected": selected,
                "missing": sorted(set(missing)), "files": entries,
                "collector_scope": "existing files only; no model weights, caches, simulator, or installation"}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path, arc in sorted(files.items(), key=lambda item: item[1]):
            archive.write(path, arc)
        archive.writestr("audit_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"archive": str(output), "selected_export_root": selected["export_root"],
                      "envstatus": env_status, "modelmanifeststatus": model_manifest_status,
                      "prediction_stats": prediction_stats, "missing": manifest["missing"],
                      "file_count": len(entries)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
