#!/usr/bin/env bash
# New bounded generation cohort, gated on current tests and rendered camera checks.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "Linux server only."
resolve_conda
env_exists || die "Missing '$CONDA_ENV' environment."
command -v flock >/dev/null 2>&1 || die "flock is required to prevent overlapping generation."
exec 9>"${DATA_ROOT%/}/generation.lock"
flock -n 9 || die "Another candidate generation is running; no second Controller started."

task_pairs="M01,M02,M03,M04,S05,S06,S07,W08,W09,W10,W11,W12,C13,C14,C15,T16,T17,T18,B19,P20"
task_max_scenes=2
task_seeds="17,43"
while (($#)); do
  case "$1" in
    --pairs) (($# >= 2)) || die "--pairs requires IDs"; task_pairs="$2"; shift 2 ;;
    --max-scenes) (($# >= 2)) || die "--max-scenes requires an integer"; task_max_scenes="$2"; shift 2 ;;
    --seeds) (($# >= 2)) || die "--seeds requires comma-separated integers"; task_seeds="$2"; shift 2 ;;
    *) die "Usage: 21_generate_candidates.sh [--pairs C13,B19,...] [--max-scenes 2] [--seeds 17,43]" ;;
  esac
done
[[ "$task_max_scenes" =~ ^[1-9][0-9]*$ ]] || die "--max-scenes must be positive."
[[ "$task_seeds" =~ ^[0-9]+(,[0-9]+)*$ ]] || die "Invalid seeds."

export PROJECT_DIR DATA_ROOT CONDA_EXE CONDA_ENV THOR_PLATFORM
bash "${PROJECT_DIR%/}/linux_server_operation/02_unit_checks.sh"
bash "${PROJECT_DIR%/}/linux_server_operation/16_camera_probe.sh"
task_helper="${PROJECT_DIR%/}/linux_server_operation/21_candidate_batch.py"
require_file "$task_helper"
run_python "$task_helper" check --project "$PROJECT_DIR" --data-root "$DATA_ROOT"

task_output="$(mktemp -d -- "${DATA_ROOT%/}/exports_scope_v2_${_lso_timestamp}_XXXXXX")"
run_python "$task_helper" prepare --project "$PROJECT_DIR" --output "$task_output" \
  --pairs "$task_pairs" --max-scenes "$task_max_scenes" --seeds "$task_seeds"
printf 'New export root: %s\n' "$task_output"
set +e
run_python "${PROJECT_DIR%/}/generator.py" --pairs "$task_pairs" \
  --output-root "$task_output" --platform "$THOR_PLATFORM" \
  --config "$task_output/_run/config.json" --max-scenes "$task_max_scenes" --seeds "$task_seeds"
task_generation_status=$?
set -e
run_python "$task_helper" collect --project "$PROJECT_DIR" --data-root "$DATA_ROOT" \
  --output "$task_output" --log "$_lso_log" --generation-status "$task_generation_status"
printf 'Generation status: %s\nExport root: %s\n' "$task_generation_status" "$task_output"
printf 'Use this explicit export root for model smoke testing; candidates remain unreviewed.\n'
if (( task_generation_status != 0 )); then
  die "Some constructions failed or generation stopped (status $task_generation_status). Evidence was collected; do not fabricate missing samples."
fi
