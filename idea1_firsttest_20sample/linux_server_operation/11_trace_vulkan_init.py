#!/usr/bin/env python3
"""Summarize targeted Vulkan init traces and read-only driver/device metadata."""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from typing import Any


LIB_DIRS = ("/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu", "/usr/lib64", "/lib64", "/usr/lib", "/lib")
TRACE_PATTERN = re.compile(
    r"ENOENT|EACCES|EPERM|permission denied|no such file|cannot open|failed to load|undefined symbol|"
    r"libGLX_nvidia|libnvidia-(?:eglcore|glvkspirv|gpucomp)|/dev/(?:nvidia|dri)|vk_icd|vkCreateInstance",
    re.IGNORECASE,
)


def capture(argv: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        cp = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
        return {"argv": argv, "returncode": cp.returncode, "stdout": cp.stdout[-20000:], "stderr": cp.stderr[-10000:]}
    except subprocess.TimeoutExpired:
        return {"argv": argv, "returncode": None, "timed_out": True}
    except OSError as exc:
        return {"argv": argv, "returncode": None, "error": str(exc)}


def host_version() -> str | None:
    path = Path("/proc/driver/nvidia/version")
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    match = re.search(r"\b(\d{3,4}\.\d+\.\d+)\b", text)
    return match.group(1) if match else None


def inspect_library(path: Path) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path), "exists": path.exists(), "is_symlink": path.is_symlink()}
    try:
        if path.is_symlink():
            item["link_target"] = os.readlink(path)
        resolved = path.resolve(strict=False)
        item["resolved_path"] = str(resolved)
        item["resolved_exists"] = resolved.exists()
        if not resolved.exists():
            return item
        info = resolved.stat()
        item["size_bytes"] = info.st_size
        with resolved.open("rb") as handle:
            item["elf"] = handle.read(4) == b"\x7fELF"
        item["readelf_dynamic"] = capture(["readelf", "-d", str(resolved)])
        item["ldd"] = capture(["ldd", str(resolved)])
    except OSError as exc:
        item["error"] = str(exc)
    return item


def driver_libraries(version: str | None) -> list[dict[str, Any]]:
    names = ["libGLX_nvidia.so.0"]
    if version:
        names.extend([
            f"libGLX_nvidia.so.{version}",
            f"libnvidia-eglcore.so.{version}",
            f"libnvidia-glvkspirv.so.{version}",
        ])
    found: dict[str, Path] = {}
    for directory in LIB_DIRS:
        for name in names:
            path = Path(directory) / name
            if path.exists() or path.is_symlink():
                found[str(path)] = path
    return [inspect_library(found[key]) for key in sorted(found)]


def device_nodes() -> dict[str, Any]:
    paths = sorted(glob.glob("/dev/nvidia*") + glob.glob("/dev/dri/*"))
    records = []
    for value in paths:
        path = Path(value)
        try:
            info = path.stat()
            records.append({
                "path": value,
                "type": "character" if stat.S_ISCHR(info.st_mode) else "block" if stat.S_ISBLK(info.st_mode) else "other",
                "mode_octal": oct(stat.S_IMODE(info.st_mode)),
                "uid": info.st_uid,
                "gid": info.st_gid,
                "major": os.major(info.st_rdev) if stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode) else None,
                "minor": os.minor(info.st_rdev) if stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode) else None,
                "readable": os.access(path, os.R_OK),
                "writable": os.access(path, os.W_OK),
            })
        except OSError as exc:
            records.append({"path": value, "error": str(exc)})
    return {"effective_uid": os.geteuid(), "nodes": records}


def filtered_trace_lines(evidence: Path) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {}
    for path in sorted(evidence.glob("*.loader_stderr.txt")) + sorted(evidence.glob("*.strace")):
        try:
            matches = [line for line in path.read_text(errors="replace").splitlines() if TRACE_PATTERN.search(line)]
        except OSError as exc:
            matches = [f"read error: {exc}"]
        report[path.name] = matches[:200]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    evidence = args.output_dir.resolve()
    version = host_version()
    report = {
        "collected_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host_driver_version": version,
        "selected_nvidia_environment": {
            key: os.environ[key]
            for key in ("NVIDIA_DRIVER_CAPABILITIES", "NVIDIA_VISIBLE_DEVICES")
            if key in os.environ
        },
        "driver_libraries": driver_libraries(version),
        "device_nodes": device_nodes(),
        "probe_exit_status": {
            name: (evidence / f"{name}.exit_status.txt").read_text(errors="replace").strip()
            if (evidence / f"{name}.exit_status.txt").exists() else "missing"
            for name in ("vulkaninfo", "nativeprobe")
        },
        "nativeprobe_json_stdout": (evidence / "nativeprobe.stdout.txt").read_text(errors="replace")[-12000:]
        if (evidence / "nativeprobe.stdout.txt").exists() else "missing",
        "relevant_loader_and_syscall_lines": filtered_trace_lines(evidence),
    }
    path = evidence / "init_trace_report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    empty = [item["path"] for item in report["driver_libraries"] if item.get("size_bytes") == 0]
    hits = [(name, line) for name, lines in report["relevant_loader_and_syscall_lines"].items() for line in lines]
    permissions = report["device_nodes"]
    summary = [
        "Vulkan initialization trace summary",
        f"Host NVIDIA version: {version or 'unknown'}",
        f"vulkaninfo exit: {report['probe_exit_status']['vulkaninfo']}; nativeprobe exit: {report['probe_exit_status']['nativeprobe']}",
        f"Inspected driver libraries: {len(report['driver_libraries'])}; zero-byte files: {', '.join(empty) if empty else 'none'}",
        f"NVIDIA/DRI device nodes: {len(permissions['nodes'])}; effective uid: {permissions['effective_uid']}",
        "Device nodes were stat/access checked only; this helper did not open them.",
        f"Relevant loader/syscall lines: {len(hits)} (showing up to 160)",
    ]
    for filename, line in hits[:160]:
        summary.append(f"[{filename}] {line[:600]}")
    summary.extend(["", f"Detailed report: {path}"])
    (evidence / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary[:7]))
    print(f"Summary: {evidence / 'summary.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
