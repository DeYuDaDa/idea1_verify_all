#!/usr/bin/env bash
# Read-only Vulkan/NVIDIA ICD diagnosis. Does not launch AI2-THOR or Unity.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "This diagnostic is Linux-only."

resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. This read-only diagnostic does not install or recreate it."
task_report_dir="${DATA_ROOT%/}/vulkan_diagnosis/${_lso_timestamp}"
mkdir -p -- "$task_report_dir"
task_helper="${PROJECT_DIR%/}/linux_server_operation/10_nvidia_icd_diagnose.py"
require_file "$task_helper"

printf 'Running read-only ICD diagnosis. No Unity or AI2-THOR process will be started.\n'
printf 'Detailed evidence: %s\n' "$task_report_dir"
export PROJECT_DIR DATA_ROOT CONDA_EXE CONDA_ENV THOR_PLATFORM
set +e
run_python "$task_helper" --output-dir "$task_report_dir"
task_result=$?
set -e
task_archive="${DATA_ROOT%/}/vulkan_diagnosis/${_lso_timestamp}_nvidia_icd_diagnostic.tar.gz"
task_archive_status=1
if command -v tar >/dev/null 2>&1; then
  set +e
  tar -czf "$task_archive" -C "$DATA_ROOT" "vulkan_diagnosis/${_lso_timestamp}" -C "$LOG_DIR" "$(basename -- "$_lso_log")"
  task_archive_status=$?
  set -e
fi
if (( task_archive_status == 0 )); then
  printf 'Selective evidence archive: %s\n' "$task_archive"
else
  printf 'Could not create a tar.gz archive; upload the diagnostic directory and stage log separately.\n'
fi
if (( task_result != 0 )); then
  die "No real NVIDIA Vulkan enumeration was confirmed (diagnostic status $task_result). Upload the diagnostic directory $task_report_dir and stage log $_lso_log. Do not infer root cause from zero-sized 595 libraries alone."
fi
printf '\nREAL_NVIDIA_VULKAN_ENUMERATION_CONFIRMED\n'
printf 'Upload the archive above, or the diagnostic directory and stage log: %s\n' "$task_report_dir"
