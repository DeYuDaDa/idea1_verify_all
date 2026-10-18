#!/usr/bin/env bash
# Install the missing EGL loader if needed, then verify NVIDIA Vulkan enumeration.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "This repair is Linux-only."
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing; this stage will not recreate it."

check_only=false
run_smoke=false
for arg in "$@"; do
  case "$arg" in
    --check-only) check_only=true ;;
    --smoke) run_smoke=true ;;
    *) die "Usage: bash linux_server_operation/12_fix_egl.sh [--check-only] [--smoke]" ;;
  esac
done
if [[ "$check_only" == true && "$run_smoke" == true ]]; then die "--check-only and --smoke cannot be combined."; fi

task_evidence="${DATA_ROOT%/}/egl_repair/${_lso_timestamp}"
mkdir -p -- "$task_evidence"
task_evidence="$(cd -- "$task_evidence" && pwd -P)"
task_started_epoch="$(date +%s)"
task_helper="${PROJECT_DIR%/}/linux_server_operation/12_egl_check.py"
require_file "$task_helper"
export PROJECT_DIR DATA_ROOT CONDA_EXE CONDA_ENV THOR_PLATFORM
cd -- "$task_evidence"
ulimit -c 0 || true
task_final_status=0
task_egl_status=0
task_nvidia_ready=false
set +e
run_python "$task_helper" --check-egl > egl_before.json 2>&1
task_egl_status=$?
set -e
cat egl_before.json

if (( task_egl_status != 0 )) && [[ "$check_only" == false ]]; then
  if ! command -v apt-get >/dev/null 2>&1; then
    printf 'apt-get is unavailable; cannot install libegl1.\n' > apt_simulation.txt
    task_final_status=1
  else
    set +e
    LC_ALL=C apt-get -s -o Acquire::Retries=0 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 install --no-remove --no-install-recommends libegl1 > apt_simulation.txt 2>&1
    task_sim_status=$?
    set -e
    cat apt_simulation.txt
    if (( task_sim_status != 0 )); then
      printf 'Package simulation failed; no system package was changed.\n'
      task_final_status=1
    elif grep -Eiq '^(Remv[[:space:]]|The following packages will be REMOVED:)|^(Inst|Conf)[[:space:]]+(lib)?nvidia([[:space:]:-]|$)' apt_simulation.txt; then
      printf 'Unsafe apt plan detected (removal or NVIDIA driver-related package); refusing installation.\n'
      task_final_status=1
    else
      task_privilege=()
      if (( EUID != 0 )); then
        if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then task_privilege=(sudo -n); else
          printf 'Install requires root or passwordless sudo; no system package changed.\n'
          task_final_status=1
        fi
      fi
      if (( EUID == 0 )) || (( ${#task_privilege[@]} > 0 )); then
        set +e
        "${task_privilege[@]}" env LC_ALL=C apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 install -y --no-remove --no-install-recommends libegl1 > apt_install.txt 2>&1
        task_install_status=$?
        set -e
        cat apt_install.txt
        if (( task_install_status != 0 )); then task_final_status=1; fi
      fi
    fi
  fi
fi

if (( task_final_status == 0 )); then
  set +e
  run_python "$task_helper" --check-egl > egl_after.json 2>&1
  task_egl_status=$?
  set -e
  cat egl_after.json
  if (( task_egl_status != 0 )); then
    printf 'libEGL.so.1 is still not loadable in the thor20 environment.\n'
    task_final_status=1
  fi
fi

if (( task_final_status == 0 && task_egl_status == 0 )); then
  task_vulkaninfo="$(command -v vulkaninfo || true)"
  if [[ -z "$task_vulkaninfo" ]]; then
    printf 'vulkaninfo is unavailable; install/restore vulkan-tools separately.\n' > vulkaninfo.stdout.txt
    task_vulkan_status=127
  else
    set +e
    timeout 45s "$CONDA_EXE" run --no-capture-output -n "$CONDA_ENV" "$task_vulkaninfo" --summary > vulkaninfo.stdout.txt 2>&1
    task_vulkan_status=$?
    set -e
  fi
  printf '%s\n' "$task_vulkan_status" > vulkaninfo.exit_status.txt
  cat vulkaninfo.stdout.txt
  set +e
  run_python "$task_helper" --classify-vulkan --exit-code "$task_vulkan_status" --output-file vulkaninfo.stdout.txt > vulkaninfo.classification.json 2>&1
  task_vulkan_class_status=$?
  set -e
  cat vulkaninfo.classification.json
  if (( task_vulkan_class_status != 0 )); then
    # LD_DEBUG is forensic only: it changes the process environment and
    # cannot override a failed baseline verification.
    task_final_status=1
    set +e
    if [[ -n "$task_vulkaninfo" ]]; then
      timeout 45s "$CONDA_EXE" run --no-capture-output -n "$CONDA_ENV" env LD_DEBUG=libs,files "$task_vulkaninfo" --summary > vulkaninfo_ld_debug.stdout.txt 2> vulkaninfo_ld_debug.stderr.txt
    else
      printf 'vulkaninfo is unavailable; no loader trace was attempted.\n' > vulkaninfo_ld_debug.stdout.txt
      : > vulkaninfo_ld_debug.stderr.txt
      false
    fi
    task_vulkan_debug_status=$?
    set -e
    printf '%s\n' "$task_vulkan_debug_status" > vulkaninfo_ld_debug.exit_status.txt
    cat vulkaninfo_ld_debug.stdout.txt
    cat vulkaninfo_ld_debug.stderr.txt
    set +e
    run_python "$task_helper" --classify-vulkan --exit-code "$task_vulkan_debug_status" --output-file vulkaninfo_ld_debug.stdout.txt > vulkaninfo_ld_debug.classification.json 2>&1
    task_vulkan_debug_class_status=$?
    set -e
    cat vulkaninfo_ld_debug.classification.json
  else
    task_nvidia_ready=true
  fi
fi

if (( task_final_status != 0 )) || [[ "$run_smoke" == true ]]; then
  set +e
  run_python "$task_helper" --collect --output-dir "$task_evidence"
  task_collect_status=$?
  set -e
  if (( task_collect_status != 0 )); then task_final_status=1; fi
fi

if [[ "$run_smoke" == true ]]; then
  if [[ "$task_nvidia_ready" == true ]]; then
    set +e
    bash "${PROJECT_DIR%/}/linux_server_operation/03_smoke.sh" FloorPlan1 > smoke.stdout.txt 2>&1
    task_smoke_status=$?
    set -e
    printf '%s\n' "$task_smoke_status" > smoke.exit_status.txt
    cat smoke.stdout.txt
    task_smoke_result="$task_evidence/smoke_result"
    mkdir -p -- "$task_smoke_result"
    for task_smoke_file in failure.json report.json actions.json scene_rgb.png; do
      task_smoke_source="${DATA_ROOT%/}/smoke/$task_smoke_file"
      if [[ -f "$task_smoke_source" ]]; then
        task_smoke_mtime="$(stat -c %Y -- "$task_smoke_source" 2>/dev/null || printf '0')"
        if [[ "$task_smoke_mtime" =~ ^[0-9]+$ ]] && (( task_smoke_mtime >= task_started_epoch )); then
          cp -p -- "$task_smoke_source" "$task_smoke_result/$task_smoke_file"
        fi
      fi
    done
    if (( task_smoke_status != 0 )); then task_final_status=1; fi
  else
    printf 'Smoke skipped: baseline vulkaninfo did not confirm NVIDIA enumeration.\n'
    task_final_status=1
  fi
fi

task_archive="${DATA_ROOT%/}/egl_repair/${_lso_timestamp}_egl_repair.tar.gz"
task_archive_status=1
if command -v tar >/dev/null 2>&1; then
  set +e
  tar -czf "$task_archive" -C "$DATA_ROOT" "egl_repair/${_lso_timestamp}" -C "$LOG_DIR" "$(basename -- "$_lso_log")"
  task_archive_status=$?
  set -e
fi
if (( task_archive_status == 0 )); then printf 'Selective evidence archive: %s\n' "$task_archive"; else printf 'Archive failed; return %s and %s separately.\n' "$task_evidence" "$_lso_log"; fi
if (( task_final_status != 0 )); then die "EGL repair/verification did not complete successfully. Preserve and return the evidence above. This script does not request NVIDIA driver packages or manually rewrite driver links."; fi
printf 'EGL and NVIDIA Vulkan verification completed. Evidence: %s\n' "$task_evidence"
