#!/usr/bin/env bash
# Trace Vulkan loader initialization only; no Unity/AI2-THOR launch.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "This diagnostic is Linux-only."
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing; this stage does not install or recreate it."

install_strace=false
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --install-strace ) ]]; then
  die "Usage: bash linux_server_operation/11_trace_vulkan_init.sh [--install-strace]"
elif [[ $# -eq 1 ]]; then
  install_strace=true
fi

task_evidence="${DATA_ROOT%/}/vulkan_init_trace/${_lso_timestamp}"
mkdir -p -- "$task_evidence"
task_evidence="$(cd -- "$task_evidence" && pwd -P)"
task_helper="${PROJECT_DIR%/}/linux_server_operation/11_trace_vulkan_init.py"
task_nativeprobe="${PROJECT_DIR%/}/linux_server_operation/10_nvidia_icd_diagnose.py"
require_file "$task_helper"
require_file "$task_nativeprobe"
export PROJECT_DIR DATA_ROOT CONDA_EXE CONDA_ENV THOR_PLATFORM

if ! command -v strace >/dev/null 2>&1 && [[ "$install_strace" == true ]]; then
  printf 'Optional strace requested. Attempting to install only the strace package.\n'
  task_privilege=()
  if (( EUID != 0 )); then
    if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
      task_privilege=(sudo -n)
    else
      printf 'strace install skipped: root or passwordless sudo is unavailable. LD_DEBUG probes will still run.\n'
    fi
  fi
  if (( EUID == 0 )) || (( ${#task_privilege[@]} > 0 )); then
    set +e
    "${task_privilege[@]}" apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 install -y --no-install-recommends strace
    task_install_status=$?
    set -e
    if (( task_install_status != 0 )); then printf 'strace installation failed (status %s); continuing with LD_DEBUG only.\n' "$task_install_status"; fi
  fi
fi

task_strace_available=false
if command -v strace >/dev/null 2>&1; then task_strace_available=true; fi
printf 'Evidence directory: %s\nstrace available: %s\n' "$task_evidence" "$task_strace_available"
cd -- "$task_evidence"
# Native probes may crash; retain text evidence without producing large core files.
ulimit -c 0 || true

task_run_probe() {
  local label="$1"; shift
  local status=0
  local trace_args=()
  if [[ "$task_strace_available" == true ]]; then
    trace_args=("$(command -v strace)" -f -tt -s 256 -e trace=openat,open,access,stat,newfstatat,statx,readlink,readlinkat,ioctl -o "${task_evidence}/${label}.strace" --)
  fi
  set +e
  timeout 35s "$CONDA_EXE" run --no-capture-output "${_lso_conda_selector[@]}" "${trace_args[@]}" env LD_DEBUG=libs,files "$@" >"${label}.stdout.txt" 2>"${label}.loader_stderr.txt"
  status=$?
  set -e
  if [[ "$task_strace_available" == true ]] && grep -Eiq 'ptrace|operation not permitted|could not attach' "${label}.loader_stderr.txt"; then
    printf '%s\n' 'strace could not trace this container; retrying once with LD_DEBUG only.' >> "${label}.loader_stderr.txt"
    set +e
    timeout 35s "$CONDA_EXE" run --no-capture-output "${_lso_conda_selector[@]}" env LD_DEBUG=libs,files "$@" >"${label}.fallback.stdout.txt" 2>"${label}.fallback.loader_stderr.txt"
    status=$?
    set -e
  fi
  printf '%s\n' "$status" > "${label}.exit_status.txt"
}

task_vulkaninfo="$(command -v vulkaninfo || true)"
if [[ -n "$task_vulkaninfo" ]]; then
  task_run_probe vulkaninfo "$task_vulkaninfo" --summary
else
  printf 'vulkaninfo was not found on PATH.\n' > "${task_evidence}/vulkaninfo.stdout.txt"
  printf '127\n' > "${task_evidence}/vulkaninfo.exit_status.txt"
fi

task_run_probe nativeprobe python "$task_nativeprobe" --ctypes-child libGLX_nvidia.so.0 stage11_nativeprobe

set +e
run_python "$task_helper" --output-dir "$task_evidence"
task_summary_status=$?
set -e

task_archive="${DATA_ROOT%/}/vulkan_init_trace/${_lso_timestamp}_vulkan_init_trace.tar.gz"
task_archive_status=1
if command -v tar >/dev/null 2>&1; then
  set +e
  tar -czf "$task_archive" -C "$DATA_ROOT" "vulkan_init_trace/${_lso_timestamp}" -C "$LOG_DIR" "$(basename -- "$_lso_log")"
  task_archive_status=$?
  set -e
fi
if (( task_archive_status == 0 )); then printf 'Selective evidence archive: %s\n' "$task_archive"; else printf 'Archive unavailable; return evidence directory and stage log separately.\n'; fi
printf 'Summary: %s/summary.txt\n' "$task_evidence"
if (( task_summary_status != 0 )); then die "Summary generation failed (status $task_summary_status); return $task_evidence and $_lso_log."; fi
printf 'Trace collection finished. No Unity or AI2-THOR process was started.\n'
