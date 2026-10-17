#!/usr/bin/env python3
"""Read-only NVIDIA Vulkan ICD diagnostics; only writes reports under output-dir."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any


TIMEOUT_SECONDS = 25
MANIFEST_DIRS = (
    Path("/etc/vulkan/icd.d"),
    Path("/usr/share/vulkan/icd.d"),
    Path("/usr/local/share/vulkan/icd.d"),
    Path("/root/.local/share/vulkan/icd.d"),
)
SELECTED_ENV_KEYS = (
    "VK_ICD_FILENAMES", "VK_DRIVER_FILES", "VK_ADD_DRIVER_FILES",
    "VK_LAYER_PATH", "VK_INSTANCE_LAYERS", "VK_LOADER_DEBUG",
    "LD_LIBRARY_PATH", "LD_PRELOAD", "LD_DEBUG",
)
LIBRARY_DIRS = (
    Path("/usr/lib/x86_64-linux-gnu"), Path("/lib/x86_64-linux-gnu"),
    Path("/usr/lib64"), Path("/lib64"), Path("/usr/lib"), Path("/lib"),
    Path("/usr/local/lib"),
)


def run_capture(argv: list[str], timeout: int = TIMEOUT_SECONDS, env: dict[str, str] | None = None, max_chars: int = 30000, cwd: Path | None = None) -> dict[str, Any]:
    try:
        cp = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, env=env, check=False, cwd=cwd)
        return {"argv": argv, "returncode": cp.returncode, "stdout": cp.stdout[-max_chars:], "stderr": cp.stderr[-max_chars:], "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv, "returncode": None, "stdout": _text(exc.stdout)[-max_chars:],
            "stderr": _text(exc.stderr)[-max_chars:], "timed_out": True, "timeout_seconds": timeout,
        }
    except (OSError, ValueError) as exc:
        return {"argv": argv, "returncode": None, "stdout": "", "stderr": str(exc), "timed_out": False}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def host_driver() -> dict[str, Any]:
    result: dict[str, Any] = {}
    driver_version = Path("/proc/driver/nvidia/version")
    try:
        result["proc_driver_version"] = driver_version.read_text(errors="replace").strip() if driver_version.is_file() else None
    except OSError as exc:
        result["proc_driver_version_error"] = str(exc)
        result["proc_driver_version"] = None
    gpu_info = sorted(Path("/proc/driver/nvidia/gpus").glob("*/information"))
    result["proc_gpu_information"] = {}
    for path in gpu_info:
        try:
            result["proc_gpu_information"][str(path)] = path.read_text(errors="replace").strip()
        except OSError as exc:
            result["proc_gpu_information"][str(path)] = f"read error: {exc}"
    nvidia_smi = shutil.which("nvidia-smi")
    result["nvidia_smi"] = run_capture([nvidia_smi, "--query-gpu=name,driver_version,pci.bus_id", "--format=csv,noheader"]) if nvidia_smi else {"unavailable": True}
    text = result.get("proc_driver_version") or ""
    match = re.search(r"(?:Kernel Module\s+)?([0-9]{3,4}\.[0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        smi_text = result.get("nvidia_smi", {}).get("stdout", "")
        match = re.search(r"(?:,\s*|\s)([0-9]{3,4}\.[0-9]+(?:\.[0-9]+)?)", smi_text)
    result["host_driver_version"] = match.group(1) if match else None
    return result


def selected_environment() -> dict[str, str]:
    # Never serialize the full environment. These keys are limited to loader selection.
    return {key: os.environ[key] for key in SELECTED_ENV_KEYS if key in os.environ}


def clean_loader_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in SELECTED_ENV_KEYS:
        env.pop(key, None)
    return env


def ldconfig_index() -> dict[str, str]:
    ldconfig = shutil.which("ldconfig")
    if not ldconfig:
        return {}
    output = run_capture([ldconfig, "-p"], timeout=10, max_chars=5000000).get("stdout", "")
    index: dict[str, str] = {}
    for line in output.splitlines():
        match = re.match(r"\s*(\S+)\s+\([^)]*\)\s+=>\s+(\S+)\s*$", line)
        if match:
            index.setdefault(match.group(1), match.group(2))
    return index


def resolve_library(value: str, manifest: Path | None, index: dict[str, str]) -> str | None:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    if "/" in value and manifest is not None:
        return str((manifest.parent / path).resolve(strict=False))
    return index.get(value)


def inspect_file(path_text: str | None) -> dict[str, Any]:
    if not path_text:
        return {"requested_path": path_text, "exists": False}
    path = Path(path_text)
    data: dict[str, Any] = {"requested_path": path_text, "exists": path.exists(), "is_symlink": path.is_symlink()}
    try:
        data["link_target"] = os.readlink(path) if path.is_symlink() else None
        real = path.resolve(strict=False)
        data["resolved_path"] = str(real)
        data["resolved_exists"] = real.exists()
        if real.exists():
            stat = real.stat()
            data["size_bytes"] = stat.st_size
            with real.open("rb") as file_handle:
                data["elf_magic"] = file_handle.read(4) == b"\x7fELF"
            data["file"] = run_capture(["file", "-L", str(path)], timeout=5) if shutil.which("file") else {"unavailable": True}
            data["readelf_header"] = run_capture(["readelf", "-h", str(real)], timeout=5) if shutil.which("readelf") else {"unavailable": True}
            data["readelf_dynamic"] = run_capture(["readelf", "-d", str(real)], timeout=5) if shutil.which("readelf") else {"unavailable": True}
            data["ldd"] = run_capture(["ldd", str(real)], timeout=10) if shutil.which("ldd") else {"unavailable": True}
        else:
            data["size_bytes"] = None
            data["elf_magic"] = False
    except OSError as exc:
        data["inspect_error"] = str(exc)
    return data


def read_manifests(index: dict[str, str]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    for directory in MANIFEST_DIRS:
        if directory.is_dir():
            paths.extend(sorted(directory.glob("*.json")))
    # Respect the actual loader override as an additional manifest source, but only report
    # explicitly named paths; do not read arbitrary files from other environment variables.
    for key in ("VK_ICD_FILENAMES", "VK_DRIVER_FILES", "VK_ADD_DRIVER_FILES"):
        for item in os.environ.get(key, "").split(os.pathsep):
            if item:
                candidate = Path(item)
                if candidate.is_file() and candidate not in paths:
                    paths.append(candidate)
    records: list[dict[str, Any]] = []
    for manifest in paths:
        record: dict[str, Any] = {"path": str(manifest), "readable": False}
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            record["readable"] = True
            record["manifest"] = raw
            lib = raw.get("ICD", {}).get("library_path") if isinstance(raw, dict) else None
            record["library_path"] = lib
            record["resolved_library"] = resolve_library(lib, manifest, index) if isinstance(lib, str) else None
            if isinstance(lib, str):
                record["library_inspection"] = inspect_file(record["resolved_library"])
        except (OSError, ValueError, TypeError) as exc:
            record["error"] = str(exc)
        records.append(record)
    return records


def mapped_driver_lines() -> list[str]:
    try:
        lines = Path("/proc/self/maps").read_text(errors="replace").splitlines()
    except OSError as exc:
        return [f"maps unavailable: {exc}"]
    terms = ("libvulkan", "libGLX_nvidia", "libnvidia", "nvidia_icd")
    return [line for line in lines if any(term in line for term in terms)]


def ctypes_child(library: str, label: str) -> int:
    record: dict[str, Any] = {"label": label, "library": library, "loaded": False}
    try:
        handle = ctypes.CDLL(library)
        record["loaded"] = True
        try:
            negotiate = getattr(handle, "vk_icdNegotiateLoaderICDInterfaceVersion")
            negotiate.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
            negotiate.restype = ctypes.c_int32
            interface_version = ctypes.c_uint32(5)
            negotiate_status = negotiate(ctypes.byref(interface_version))
            record["negotiate_loader_icd_interface"] = {
                "exported": True, "input_version": 5,
                "status": negotiate_status, "negotiated_version": interface_version.value,
            }
        except AttributeError:
            record["negotiate_loader_icd_interface"] = {"exported": False}
        raw_symbol = getattr(handle, "vk_icdGetInstanceProcAddr")
        # VkInstance is a pointer; pName is const char*; return is PFN_vkVoidFunction.
        function_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
        get_proc = function_type(("vk_icdGetInstanceProcAddr", handle))
        result = get_proc(ctypes.c_void_p(), b"vkCreateInstance")
        record["symbol_address"] = hex(ctypes.cast(raw_symbol, ctypes.c_void_p).value or 0)
        record["vkCreateInstance_address"] = hex(result) if result else None
        record["vkCreateInstance_available"] = bool(result)
    except Exception as exc:  # diagnostic child must always emit maps and a result
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["mapped_libraries"] = mapped_driver_lines()
    print(json.dumps(record, ensure_ascii=False))
    return 0 if record.get("vkCreateInstance_available") else 2


def ctypes_probe(helper: Path, library: str, label: str, env: dict[str, str], output_dir: Path) -> dict[str, Any]:
    command = [sys.executable, str(helper), "--ctypes-child", library, label]
    result = run_capture(command, timeout=TIMEOUT_SECONDS, env=env, cwd=output_dir)
    parsed = None
    try:
        parsed = json.loads(result.get("stdout", "").strip().splitlines()[-1])
    except (ValueError, IndexError, TypeError):
        pass
    result["child_result"] = parsed
    return result


def has_nvidia_enumeration(output: str, returncode: int | None) -> bool:
    lowered = output.lower()
    has_name = bool(re.search(r"devicename\s*=\s*[^\n]*nvidia", lowered))
    return returncode == 0 and bool(re.search(r"vendorid\s*=\s*0x10de", lowered)) and has_name


def vulkaninfo_probe(env: dict[str, str], label: str, output_dir: Path) -> dict[str, Any]:
    path = shutil.which("vulkaninfo")
    if not path:
        return {"label": label, "available": False, "nvidia_enumerated": False, "error": "vulkaninfo not found"}
    result = run_capture([path, "--summary"], timeout=TIMEOUT_SECONDS, env=env, cwd=output_dir)
    text = result.get("stdout", "") + "\n" + result.get("stderr", "")
    result.update({"label": label, "available": True, "nvidia_enumerated": has_nvidia_enumeration(text, result.get("returncode"))})
    return result


def host_version_from_name(path_text: str | None) -> str | None:
    if not path_text:
        return None
    matches = re.findall(r"\.so\.(\d{3,4}\.\d+\.\d+)(?:$|[^0-9])", Path(path_text).name)
    return matches[-1] if matches else None


def find_library_candidates(index: dict[str, str], kind: str) -> list[dict[str, Any]]:
    found: dict[str, str] = {}
    prefix = "libGLX_nvidia.so" if kind == "glx" else "libnvidia-gpucomp.so"
    for name, path in index.items():
        if name.startswith(prefix):
            found[path] = path
    for directory in LIBRARY_DIRS:
        if directory.is_dir():
            for path in directory.glob(prefix + "*"):
                found[str(path)] = str(path)
    return [inspect_file(path) for path in sorted(found)]


def private_manifest_candidate(manifests: list[dict[str, Any]], glx_candidates: list[dict[str, Any]], host_version: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if not host_version:
        return None, None, "Host NVIDIA driver version could not be determined."
    templates = [item for item in manifests if isinstance(item.get("manifest"), dict)
                 and "nvidia" in str(item.get("library_path", "")).lower()
                 and "glx" in str(item.get("library_path", "")).lower()]
    if not templates:
        return None, None, "No actual NVIDIA GLX ICD manifest is available as a private template."
    for info in glx_candidates:
        real = info.get("resolved_path")
        if (info.get("size_bytes") or 0) <= 0 or not info.get("elf_magic") or host_version_from_name(real) != host_version:
            continue
        ldd_output = info.get("ldd", {}).get("stdout", "")
        gpucomp_refs = re.findall(r"(\S*libnvidia-gpucomp\.so\.[0-9.]+)", ldd_output)
        if any(host_version not in Path(ref).name for ref in gpucomp_refs):
            continue
        return templates[0], info, None
    return None, None, "No nonzero host-version-matched NVIDIA GLX ELF was found in the manifest target or common library directories."


def main_diagnose(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    helper = Path(__file__).resolve()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    index = ldconfig_index()
    host = host_driver()
    manifests = read_manifests(index)
    env_report = selected_environment()
    glx_candidates = find_library_candidates(index, "glx")
    gpucomp_candidates = find_library_candidates(index, "gpucomp")

    default_glx = "libGLX_nvidia.so.0"
    baseline_env = dict(os.environ)
    clean_env = clean_loader_environment()
    report: dict[str, Any] = {
        "started_utc": started,
        "host_driver": host,
        "selected_loader_environment": env_report,
        "ldconfig_index": {k: v for k, v in index.items() if "vulkan" in k.lower() or "nvidia" in k.lower() or "glx" in k.lower()},
        "icd_manifests": manifests,
        "libGLX_nvidia_candidates": glx_candidates,
        "libnvidia_gpucomp_candidates": gpucomp_candidates,
        "baseline_ctypes_probe": ctypes_probe(helper, default_glx, "baseline", baseline_env, output_dir),
        "clean_ctypes_probe": ctypes_probe(helper, default_glx, "cleared_vk_ld_overrides", clean_env, output_dir),
        "vulkaninfo_baseline": vulkaninfo_probe(baseline_env, "baseline", output_dir),
        "vulkaninfo_clean": vulkaninfo_probe(clean_env, "cleared_vk_ld_overrides", output_dir),
    }
    interim_report = output_dir / "diagnosis_report.json"
    interim_report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    candidate, candidate_library, candidate_reason = private_manifest_candidate(manifests, glx_candidates, host.get("host_driver_version"))
    report["private_icd_candidate_reason"] = candidate_reason
    if candidate:
        source_manifest = Path(candidate["path"])
        private_path = output_dir / "private_nvidia_icd.json"
        private_json = json.loads(json.dumps(candidate["manifest"]))
        # Preserve every manifest field except library_path; point only to the resolved real library.
        private_json["ICD"]["library_path"] = candidate_library["resolved_path"]
        private_path.write_text(json.dumps(private_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        private_env = clean_loader_environment()
        private_env["VK_ICD_FILENAMES"] = str(private_path.resolve())
        report["private_icd"] = {
            "source_manifest": str(source_manifest), "path": str(private_path.resolve()),
            "library_path": private_json["ICD"]["library_path"],
            "only_manifest_field_changed": "ICD.library_path",
            "ctypes_probe": ctypes_probe(helper, private_json["ICD"]["library_path"], "private_real_glx", private_env, output_dir),
            "vulkaninfo": vulkaninfo_probe(private_env, "private_real_glx", output_dir),
        }
    else:
        report["private_icd"] = {"created": False, "reason": candidate_reason}
    interim_report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    private_vulkan = report.get("private_icd", {}).get("vulkaninfo", {})
    real_enumeration = any((
        report["vulkaninfo_baseline"].get("nvidia_enumerated"),
        report["vulkaninfo_clean"].get("nvidia_enumerated"),
        private_vulkan.get("nvidia_enumerated"),
    ))
    report["summary"] = {
        "real_nvidia_vulkan_enumeration_confirmed": bool(real_enumeration),
        "success_criterion": "vulkaninfo --summary returned a real NVIDIA device (vendorID 0x10de and NVIDIA device name)",
        "zero_sized_595_libraries_are_only_a_clue": True,
        "unity_or_ai2thor_started": False,
        "interpretation": (
            "A real NVIDIA Vulkan device was enumerated by at least one variant. This confirms loader/ICD/device enumeration only; it does not confirm Unity or AI2-THOR startup."
            if real_enumeration else
            "No variant enumerated a real NVIDIA Vulkan device. Zero-sized 595 libraries are evidence to investigate, not proof of cause. Review manifests, ELF/linker evidence, host version, and each probe result."
        ),
    }
    import shlex
    retry_variant = None
    if report["vulkaninfo_baseline"].get("nvidia_enumerated"):
        retry_variant = "baseline"
    elif report["vulkaninfo_clean"].get("nvidia_enumerated"):
        retry_variant = "cleared_vk_ld_overrides"
    elif private_vulkan.get("nvidia_enumerated"):
        retry_variant = "private_real_glx"
    retry_script = None
    if retry_variant:
        project_dir = Path(__file__).resolve().parent.parent
        retry_script = output_dir / "retry_smoke.sh"
        lines = ["#!/usr/bin/env bash", "set -Eeuo pipefail"]
        lines.append(f"export PROJECT_DIR={shlex.quote(str(project_dir))}")
        for setting in ("DATA_ROOT", "CONDA_EXE", "CONDA_ENV", "THOR_PLATFORM"):
            if setting in os.environ:
                lines.append(f"export {setting}={shlex.quote(os.environ[setting])}")
        lines.extend([
            f"source {shlex.quote(str(project_dir / 'linux_server_operation' / 'common.sh'))}",
            "print_settings",
            "unset " + " ".join(SELECTED_ENV_KEYS),
        ])
        if retry_variant == "baseline":
            for key, value in env_report.items():
                lines.append(f"export {key}={shlex.quote(value)}")
        if retry_variant == "private_real_glx":
            lines.append(f"export VK_ICD_FILENAMES={shlex.quote(str((output_dir / 'private_nvidia_icd.json').resolve()))}")
        # Use the already selected thor20 interpreter directly. Activating Conda
        # again could reintroduce an LD/VK override removed by a successful probe.
        lines.append(
            f"{shlex.quote(sys.executable)} {shlex.quote(str(project_dir / 'probe.py'))} "
            '--output-root "$DATA_ROOT" --platform "$THOR_PLATFORM" --scene FloorPlan1'
        )
        retry_script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report["summary"]["manual_smoke_retry_variant"] = retry_variant
        report["summary"]["manual_smoke_retry_script"] = str(retry_script.resolve())
    report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report_path = output_dir / "diagnosis_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary_path = output_dir / "summary.txt"
    summary_path.write_text(
        "NVIDIA Vulkan ICD diagnostic summary\n"
        f"Host driver: {host.get('host_driver_version') or 'unknown'}\n"
        f"Real NVIDIA Vulkan enumeration: {'YES' if real_enumeration else 'NO'}\n"
        f"Private ICD test: {'created' if candidate else 'not created'}\n"
        f"Private ICD note: {candidate_reason or 'manifest-backed host-version-matched GLX library selected'}\n"
        "Interpretation: zero-sized 595.71.05 libraries are a clue only; they do not alone establish the cause.\n"
        "Unity/AI2-THOR was not launched.\n"
        f"Detailed report: {report_path}\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Detailed report: {report_path}")
    print(f"Summary: {summary_path}")
    if retry_script:
        print(f"Manual-only smoke retry (not executed): {retry_script.resolve()}")
    return 0 if real_enumeration else 3


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--ctypes-child":
        if len(sys.argv) != 4:
            print("usage: helper --ctypes-child LIBRARY LABEL", file=sys.stderr)
            return 64
        return ctypes_child(sys.argv[2], sys.argv[3])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        return main_diagnose(args.output_dir)
    except Exception as exc:
        # Best-effort fatal report. Normal probe failures are captured independently above.
        args.output_dir.mkdir(parents=True, exist_ok=True)
        fatal = args.output_dir / "fatal_error.txt"
        fatal.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"Diagnostic helper error: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"Failure detail: {fatal}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
