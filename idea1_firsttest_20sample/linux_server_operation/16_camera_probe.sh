#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "This camera probe is Linux-only."
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. Run 01_setup_env.sh first."

task_root="$(realpath -m -- "$DATA_ROOT")"
task_out="${task_root%/}/camera_probe/${_lso_timestamp}"
task_zip="${task_root%/}/logs/${_lso_timestamp}_camera_probe_bundle.zip"
task_started="$(date +%s)"
task_helper="${PROJECT_DIR%/}/camera_probe.py"
task_cache_checker="${PROJECT_DIR%/}/linux_server_operation/13_thor_build.py"
require_file "$task_helper"
require_file "$task_cache_checker"
mkdir -p -- "$task_out"
export PROJECT_DIR DATA_ROOT THOR_PLATFORM

task_cache_dir="${task_root%/}/unity_cache"
task_status=0
printf 'Validating the existing data-disk THOR build; downloads are not allowed in this step.\n'
if run_python "$task_cache_checker" --check-cache --data-root "$task_root"; then
  :
else
  task_status=$?
fi

task_args=("$task_helper" --out "$task_out" --platform "$THOR_PLATFORM"
  --build-cache-dir "$task_cache_dir")
if [[ -n "${THOR_LOCAL_EXECUTABLE_PATH:-}" ]]; then
  task_args+=(--local-executable-path "$THOR_LOCAL_EXECUTABLE_PATH")
fi
if (( task_status == 0 )); then
  if run_python "${task_args[@]}"; then
    :
  else
    task_status=$?
  fi
else
  printf 'Cache validation failed; writing failure metadata without launching the camera probe or Unity.\n'
  task_elapsed="$(( $(date +%s) - task_started ))"
  if run_python - "$task_out" "$task_elapsed" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
elapsed = float(sys.argv[2])
cases = [
    ("FloorPlan5", "CoffeeMachine"),
    ("FloorPlan201", "Laptop"),
    ("FloorPlan9", "Microwave"),
]
rows = []
for scene, object_type in cases:
    item = {"scene": scene, "objectType": object_type, "status": "failed",
            "stage": "cache_preflight", "elapsed_seconds": elapsed,
            "error": "13_thor_build.py --check-cache failed; probe and Unity launch skipped."}
    case_dir = out / f"{scene}_{object_type}"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "metadata.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    rows.append(item)
(out / "manifest.json").write_text(json.dumps({"status": "failed", "elapsed_seconds": elapsed,
                                                "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
PY
  then
    :
  else
    write_status=$?
    (( task_status != 0 )) || task_status=$write_status
  fi
fi

# Package on both success and failure. Python's standard library avoids a
# system-zip dependency and includes this stage's operation log for diagnosis.
if run_python - "$task_zip" "$PROJECT_DIR" "$task_out" "$_lso_log" <<'PY'
import sys
import zipfile
from pathlib import Path

archive_path, project_root, output_root, log_path = map(Path, sys.argv[1:])
project_files = (
    "camera_probe.py", "runtime.py", "interactions.py", "tests/test_camera.py",
    "linux_server_operation/16_camera_probe.sh",
    "linux_server_operation/16_camera_probe.md",
)
with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for relative in project_files:
        path = project_root / relative
        if path.is_file():
            archive.write(path, relative)
    if output_root.exists():
        for path in sorted(output_root.rglob("*")):
            if path.is_file():
                archive.write(path, str(path.relative_to(output_root.parent)))
    if log_path.is_file():
        archive.write(log_path, f"logs/{log_path.name}")
PY
then
  :
else
  printf 'ERROR: Could not create the probe bundle: %s\n' "$task_zip" >&2
  (( task_status != 0 )) || task_status=1
fi
printf 'Probe output: %s\nBundle: %s\n' "$task_out" "$task_zip"
if (( task_status != 0 )); then
  printf 'ERROR: Camera probe stage failed with status %s; preserve the bundle and operation log.\n' "$task_status" >&2
  exit "$task_status"
fi
