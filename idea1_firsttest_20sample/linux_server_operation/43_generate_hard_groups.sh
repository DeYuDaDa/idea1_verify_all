#!/usr/bin/env bash
# Generate native data only. Default selection remains H05-1; --all excludes frozen accepted H04-2/3.
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
    --cases|--seed|--scene-limit|--capture-mode|--debug-stride) (($# >= 2)) || die "$1 needs a value"; shift 2 ;;
    --debug-views) shift ;;
    *) die "Supported options: --all (excludes frozen H04-2/3), --cases H03-1,H04-1,H04-4,H05-1, --seed INTEGER, --scene-limit 1..30, --capture-mode debug|full, --debug-stride INTEGER, --debug-views. Default: H05-1 only; debug capture." ;;
  esac
done
printf '\n[43] Checking source and mock contracts before starting Unity. No model environment is used.\n'
printf '[43] Capture defaults to debug (key frames + ordinary stride 3). Use --capture-mode full for the final dense visual dataset.\n'
run_python -m compileall -q runtime.py full_step_trace.py hard_context.py hard_navigation.py hard_inventory.py hard_inventory_prepare.py hard_scene_survey.py hard_contracts.py hard_scenarios.py hard_h01.py hard_camera.py hard_export.py hard_generate.py
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
source_names = ["runtime.py", "full_step_trace.py", "hard_context.py", "hard_navigation.py", "hard_inventory.py", "hard_inventory_prepare.py", "hard_scene_survey.py", "hard_contracts.py", "hard_scenarios.py", "hard_h01.py", "hard_camera.py",
                "hard_export.py", "hard_generate.py", "interactions.py", "view_planning.py", "observation_views.py",
                "review_web/review.css", "review_web/index.html", "tests/test_hard_h01.py",
                "linux_server_operation/56_generate_h01_1.sh", "linux_server_operation/56_H01-1单题生成与检查.md",
                "nested_setup.py", "New-WebReview.ps1", "review_web/review.js", "config.json",
                "docs/ai2thor_object_reference.md", "linux_server_operation/43_generate_hard_groups.sh",
                "困难组逐题流程与全程采集核对_20261027.md", "linux_server_operation/44_困难组生成与网页审核.md",
                "linux_server_operation/45_repair_hard_capture.sh", "linux_server_operation/46_审核意见修复与重跑.md",
                "hard_accepted_cases.json", "linux_server_operation/49_已通过题封存与剩余组重跑.md",
                "linux_server_operation/52_杯盘与微波炉审核修复及调试采帧_20261028.md"]
entries += [(project / name, "source/" + name) for name in source_names if (project / name).is_file()]
manifest = [{"path": name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p, name in entries]
image_count = sum(1 for _, name in entries if name.startswith("dataset/") and name.lower().endswith(".png"))
summary_path = root / "generation_summary.json"
summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
published = summary.get("published_case_count", 0)
capture_status = ("candidates_pending_review"
                  if published and published == len(summary.get("requested_cases", []))
                  else "source_incomplete")
with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as bundle:
    for path, name in entries:
        bundle.write(path, name)
    bundle.writestr("bundle_manifest.json", json.dumps({"model_called": False, "files": manifest,
                                                     "image_file_count": image_count,
                                                     "published_case_count": published,
                                                     "source_status": capture_status},
                                                     ensure_ascii=False, indent=2))
print(json.dumps({"archive": str(archive_path), "data_root": str(root), "files": len(entries),
                  "image_file_count": image_count, "published_case_count": published,
                  "source_status": capture_status, "model_called": False}, ensure_ascii=False, indent=2))
if image_count == 0:
    print("[43] NO IMAGES PRODUCED: diagnostic ZIP only. Read generation_summary.json; do not treat this as a generated dataset.", file=sys.stderr)
PY
printf '\n[43] Data: %s\nZIP: %s\nLog: %s\n' "$out" "$archive" "$_lso_log"
if [[ "$run_status" -eq 0 ]]; then
  printf '[43] Candidates still need human visual/answerability review; no model was run.\n'
else
  printf '[43] Generation incomplete. ZIP preserves diagnostics and any partial candidates; it is not a completed dataset. No model was run.\n'
fi
exit "$run_status"
