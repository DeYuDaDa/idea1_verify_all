#!/usr/bin/env python3
"""Small stdlib-only EGL/Vulkan checks and focused NVIDIA EGL evidence collector."""

from __future__ import annotations

import argparse
import ctypes
from ctypes.util import find_library
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

LIB_DIRS = ("/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu", "/usr/lib64", "/lib64", "/usr/lib", "/lib")


def inspect(path: Path) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path), "exists": path.exists(), "symlink": path.is_symlink()}
    try:
        if path.is_symlink():
            item["link_target"] = os.readlink(path)
        real = path.resolve(strict=False)
        item["resolved"] = str(real)
        item["resolved_exists"] = real.exists()
        if not real.exists():
            return item
        info = real.stat()
        item["size_bytes"] = info.st_size
        with real.open("rb") as stream:
            item["elf"] = stream.read(4) == b"\x7fELF"
        for name, command in (
            ("readelf_dynamic", ["readelf", "-d", str(real)]),
            ("ldd", ["ldd", str(real)]),
        ):
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
                item[name] = {"returncode": result.returncode, "stdout": result.stdout[-20000:], "stderr": result.stderr[-10000:]}
            except (OSError, subprocess.TimeoutExpired) as exc:
                item[name] = {"error": str(exc)}
    except OSError as exc:
        item["error"] = str(exc)
    return item


def check_egl() -> int:
    name = find_library("EGL")
    result: dict[str, Any] = {"find_library_EGL": name, "loaded": False}
    try:
        library = ctypes.CDLL("libEGL.so.1")
        result["loaded"] = True
        result["eglGetDisplay_symbol"] = bool(getattr(library, "eglGetDisplay", None))
    except OSError as exc:
        result["load_error"] = str(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["loaded"] else 1


def classify_vulkan(exit_code: int, output_file: Path) -> int:
    text = output_file.read_text(errors="replace") if output_file.exists() else ""
    lowered = text.lower()
    name_ok = bool(re.search(r"devicename\s*=\s*[^\n]*nvidia", lowered))
    vendor_ok = bool(re.search(r"vendorid\s*=\s*0x10de", lowered))
    result = {
        "exit_code": exit_code,
        "vendor_0x10de": vendor_ok,
        "device_name_nvidia": name_ok,
        "nvidia_vulkan_enumerated": exit_code == 0 and vendor_ok and name_ok,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["nvidia_vulkan_enumerated"] else 1


def collect(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    driver_file = Path("/proc/driver/nvidia/version")
    try:
        driver_text = driver_file.read_text(errors="replace")
    except OSError as exc:
        driver_text = f"unavailable: {exc}"
    match = re.search(r"\b(\d{3,4}\.\d+\.\d+)\b", driver_text)
    version = match.group(1) if match else None
    names = ["libEGL_nvidia.so.0"]
    if version:
        names.append(f"libEGL_nvidia.so.{version}")
    libraries: dict[str, Path] = {}
    for directory in LIB_DIRS:
        for name in names:
            path = Path(directory) / name
            if path.exists() or path.is_symlink():
                libraries[str(path)] = path
    vendor_files = []
    for directory in (Path("/usr/share/glvnd/egl_vendor.d"), Path("/etc/glvnd/egl_vendor.d")):
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                try:
                    vendor_files.append({"path": str(path), "json": json.loads(path.read_text(encoding="utf-8"))})
                except (OSError, ValueError) as exc:
                    vendor_files.append({"path": str(path), "error": str(exc)})
    report = {
        "collected_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host_driver_version": version,
        "host_driver_version_source": driver_text,
        "egl_vendor_json": vendor_files,
        "nvidia_egl_libraries": [inspect(libraries[key]) for key in sorted(libraries)],
    }
    report_path = output_dir / "egl_vendor_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"EGL vendor/library evidence: {report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-egl", action="store_true")
    mode.add_argument("--classify-vulkan", action="store_true")
    mode.add_argument("--collect", action="store_true")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.check_egl:
        return check_egl()
    if args.classify_vulkan:
        if args.exit_code is None or args.output_file is None:
            parser.error("--classify-vulkan requires --exit-code and --output-file")
        return classify_vulkan(args.exit_code, args.output_file)
    if args.output_dir is None:
        parser.error("--collect requires --output-dir")
    return collect(args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
