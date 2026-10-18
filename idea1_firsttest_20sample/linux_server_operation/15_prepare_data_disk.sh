#!/usr/bin/env bash
# Copy only reviewed-scope candidate inputs and the verified THOR build to the data disk.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "This data-disk preparation stage is Linux-only."
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing; run 01_setup_env.sh first."

task_old_root="${OLD_DATA_ROOT:-/root/will_not_be_push_to_git/idea1_firsttest_20sample}"
task_model_env="$CONDA_ENV"
task_model_dir="/root/autodl-tmp/model/qwen3.5-4b"
while (($#)); do
  case "$1" in
    --old-data-root) (($# >= 2)) || die "--old-data-root requires a path"; task_old_root="$2"; shift 2 ;;
    --model-env) (($# >= 2)) || die "--model-env requires an existing conda environment name"; task_model_env="$2"; shift 2 ;;
    --model-dir) (($# >= 2)) || die "--model-dir requires a path"; task_model_dir="$2"; shift 2 ;;
    *) die "Usage: bash linux_server_operation/15_prepare_data_disk.sh [--old-data-root PATH] [--model-env ENV] [--model-dir PATH]" ;;
  esac
done

task_helper="${PROJECT_DIR%/}/linux_server_operation/15_prepare_data_disk.py"
require_file "$task_helper"
task_old_root="$(realpath -e -- "$task_old_root")"
task_target_root="$(realpath -m -- "$DATA_ROOT")"
task_model_dir="$(realpath -m -- "$task_model_dir")"
OLD_DATA_ROOT="$task_old_root"
export PROJECT_DIR DATA_ROOT CONDA_EXE CONDA_ENV THOR_PLATFORM OLD_DATA_ROOT
set +e
run_python "$task_helper" --old-data-root "$task_old_root" --target-root "$task_target_root" \
  --model-dir "$task_model_dir" --conda-exe "$CONDA_EXE" --model-env "$task_model_env" \
  --timestamp "$_lso_timestamp"
task_status=$?
set -e
(( task_status == 0 )) || die "Data-disk preparation/diagnostics did not complete successfully. Preserve the printed report and log; old data was left untouched."
