#!/usr/bin/env bash
# Generate native data only. Default is one H05-1 capture smoke; --all is explicit.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "Run generation on Linux, not the Windows authoring checkout."
resolve_conda
env_exists || die "Existing THOR environment is unavailable. Load the migrated server.env; no install was attempted."
command -v flock >/dev/null 2>&1 || die "flock is required to prevent overlapping Unity generation."
mkdir -p -- "$DATA_ROOT"
exec 9>"${DATA_ROOT%/}/generation.lock"
flock -n 9 || die "Another simulator generation/probe is running."
cd -- "$PROJECT_DIR"
export DATA_ROOT
args=("$@")
while (($#)); do
  case "$1" in
    --all) shift ;;
    --cases|--seed) (($# >= 2)) || die "$1 needs a value"; shift 2 ;;
    *) die "Supported options: --all, --cases H05-1,H04-2, --seed INTEGER. Default: H05-1 only." ;;
  esac
done
printf '\n[43] Checking source and mock contracts before starting Unity. No model environment is used.\n'
run_python -m compileall -q runtime.py full_step_trace.py hard_context.py hard_contracts.py hard_scenarios.py hard_camera.py hard_export.py hard_generate.py
for pattern in 'test_hard_*.py' 'test_full_step_trace.py' 'test_interactions.py' 'test_camera.py' 'test_nested_setup.py' 'test_offline_runner.py'; do
  run_python -m unittest discover -s tests -p "$pattern" -v || die "Preflight tests failed; Unity has not started. Return this log."
done
run_python hard_generate.py --all --plan-only
if [[ -n "${THOR_LOCAL_EXECUTABLE_PATH:-}" ]]; then
  [[ -x "$THOR_LOCAL_EXECUTABLE_PATH" ]] || die "Configured Unity executable is not executable."
else
  run_python linux_server_operation/13_thor_build.py --check-cache --data-root "$DATA_ROOT"
fi
out="$(mktemp -d -- "${DATA_ROOT%/}/hard_groups_${_lso_timestamp}_XXXXXX")"
runtime_args=(--out "$out" --build-cache-dir "${DATA_ROOT%/}/unity_cache" --platform "$THOR_PLATFORM")
if [[ -n "${THOR_LOCAL_EXECUTABLE_PATH:-}" ]]; then
  runtime_args+=(--local-executable-path "$THOR_LOCAL_EXECUTABLE_PATH")
fi
run_status=0
if run_python hard_generate.py "${runtime_args[@]}" "${args[@]}"; then :; else run_status=$?; fi
printf '\n[43] Generation returned %s. Preserving successful and failed attempts.\n' "$run_status"
archive="${LOG_DIR%/}/${_lso_timestamp}_$(basename -- "$out")_43_hard_groups.zip"
run_python - "$out" "$archive" "$_lso_log" "$PROJECT_DIR" <<'PY'
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

root, archive_path, stage_log, project = map(Path, sys.argv[1:])
(root / "_run").mkdir(exist_ok=True)
shutil.copyfile(stage_log, root / "_run" / "stage_log_snapshot.txt")
entries = [(p, "dataset/" + p.relative_to(root).as_posix()) for p in root.rglob("*") if p.is_file()]
source_names = ["runtime.py", "full_step_trace.py", "hard_context.py", "hard_contracts.py", "hard_scenarios.py", "hard_camera.py",
                "hard_export.py", "hard_generate.py", "interactions.py", "view_planning.py", "observation_views.py",
                "nested_setup.py", "New-WebReview.ps1", "review_web/review.js", "config.json",
                "docs/ai2thor_object_reference.md", "linux_server_operation/43_generate_hard_groups.sh",
                "困难组逐题流程与全程采集核对_20261027.md", "linux_server_operation/44_困难组生成与网页审核.md"]
entries += [(project / name, "source/" + name) for name in source_names if (project / name).is_file()]
manifest = [{"path": name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p, name in entries]
with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as bundle:
    for path, name in entries:
        bundle.write(path, name)
    bundle.writestr("bundle_manifest.json", json.dumps({"model_called": False, "files": manifest},
                                                     ensure_ascii=False, indent=2))
print(json.dumps({"archive": str(archive_path), "data_root": str(root), "files": len(entries),
                  "model_called": False}, ensure_ascii=False, indent=2))
PY
printf '\n[43] Data: %s\nZIP: %s\nLog: %s\n' "$out" "$archive" "$_lso_log"
printf '[43] Candidates still need human visual/answerability review; no model was run.\n'
exit "$run_status"
