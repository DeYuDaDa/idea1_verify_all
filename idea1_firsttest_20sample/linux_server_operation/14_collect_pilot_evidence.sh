#!/usr/bin/env bash
# Collect existing pilot artifacts only; does not run validation or AI2-THOR.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "This collection stage is Linux-only."
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing; run 01_setup_env.sh first."

task_export_root="${DATA_ROOT%/}/exports"
while (($#)); do
  case "$1" in
    --export-root) (($# >= 2)) || die "--export-root requires a path"; task_export_root="$2"; shift 2 ;;
    *) die "Usage: bash linux_server_operation/14_collect_pilot_evidence.sh [--export-root PATH]" ;;
  esac
done
task_export_root="$(realpath -e -- "$task_export_root")"
task_helper="${PROJECT_DIR%/}/linux_server_operation/14_collect_pilot_evidence.py"
require_file "$task_helper"
task_output_parent="${DATA_ROOT%/}/pilot_evidence"
mkdir -p -- "$task_output_parent"
task_output="$(mktemp -d -- "$task_output_parent/${_lso_timestamp}_XXXXXX")"
printf 'Export root: %s\nEvidence staging: %s\n' "$task_export_root" "$task_output"
export PROJECT_DIR DATA_ROOT CONDA_EXE CONDA_ENV THOR_PLATFORM
run_python "$task_helper" --export-root "$task_export_root" --data-root "$DATA_ROOT" --output-dir "$task_output"
