#!/usr/bin/env bash
# Optionally seed the THOR Python prefix with user-space graphics libraries,
# then validate the host NVIDIA/Vulkan path without changing the system driver.
set -Eeuo pipefail

task_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "${task_script_dir}/server_paths.sh" ]]; then
  # shellcheck source=/dev/null
  source "${task_script_dir}/server_paths.sh"
fi
task_data_root="${DATA_ROOT:-${HOME}/experiment_data/idea1_firsttest_20sample}"
task_conda="${CONDA_EXE:-${HOME}/miniforge3/bin/conda}"
task_thor_prefix="${THOR_ENV_PREFIX:-${DATA_ROOT:-$task_data_root}/thor_env}"
task_install=false
while (($#)); do
  case "$1" in
    --install-user-libs) task_install=true; shift ;;
    *) printf 'Usage: bash %s [--install-user-libs]\n' "$0" >&2; exit 2 ;;
  esac
done
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Linux ]] || die 'Run this check on Linux.'
[[ -x "$task_conda" ]] || die "Conda executable not found: $task_conda. Run 32_install_user_conda.sh and configure CONDA_EXE."
[[ "$(uname -m)" == x86_64 ]] || die 'Pinned CloudRendering build requires Linux x86_64.'
task_repo_root="$(realpath -m -- "${task_script_dir}/../..")"
task_data_absolute="$(realpath -m -- "$task_data_root")"
case "${task_data_absolute%/}/" in "${task_repo_root%/}/"*) die "DATA_ROOT must be outside idea1_verify_all: $task_data_root" ;; esac
task_prefix_absolute="$(realpath -m -- "$task_thor_prefix")"
case "${task_prefix_absolute%/}/" in "${task_repo_root%/}/"*) die "THOR_ENV_PREFIX must be outside idea1_verify_all: $task_thor_prefix" ;; esac
mkdir -p -- "$task_data_root/logs"
task_log="${task_data_root%/}/logs/$(date -u +%Y%m%dT%H%M%SZ)_33_user_graphics.log"
exec > >(tee -a "$task_log") 2>&1
printf 'THOR prefix: %s\nData root: %s\nLog: %s\n' "$task_thor_prefix" "$task_data_root" "$task_log"

if [[ ! -x "${task_thor_prefix}/bin/python" ]]; then
  [[ "$task_install" == true ]] || die "THOR Python prefix is missing. Run this stage with --install-user-libs first: $task_thor_prefix"
  if [[ -e "$task_thor_prefix" ]]; then die "THOR prefix exists but has no executable Python; preserving it: $task_thor_prefix"; fi
  printf 'Creating dedicated THOR Python 3.10 prefix.\n'
  "$task_conda" create -y -p "$task_thor_prefix" python=3.10
fi
[[ -x "${task_thor_prefix}/bin/python" ]] || die 'THOR environment Python is missing.'
"${task_thor_prefix}/bin/python" -c 'import sys; assert sys.version_info[:2] == (3,10), sys.version; print(sys.version)'

if [[ "$task_install" == true ]]; then
  printf 'Installing user-space graphics runtime packages into the THOR prefix only.\n'
  "$task_conda" install -y -p "$task_thor_prefix" --override-channels -c conda-forge vulkan-tools libvulkan-loader libegl libgl libglvnd
  printf 'Conda packages installed. NVIDIA kernel driver and host ICD files were not changed.\n'
fi

[[ -d "${task_thor_prefix}/lib" ]] || die "Expected library directory is missing: ${task_thor_prefix}/lib"
task_graphics_env="${task_data_root%/}/thor_graphics.env"
task_tmp="${task_graphics_env}.tmp.$$"
printf 'THOR_USER_LIBRARY_DIR=%q\n' "${task_thor_prefix}/lib" > "$task_tmp"
mv -- "$task_tmp" "$task_graphics_env"
printf 'Wrote scoped library-path hint: %s\n' "$task_graphics_env"

command -v nvidia-smi >/dev/null 2>&1 || die 'nvidia-smi is unavailable. The host NVIDIA driver is not visible; ask the server administrator to install/configure the driver. No Unity process was started.'
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || die 'nvidia-smi could not query a usable NVIDIA GPU; ask the server administrator to inspect the driver/GPU assignment.'
command -v timeout >/dev/null 2>&1 || die 'GNU timeout is required.'
[[ -x "${task_thor_prefix}/bin/vulkaninfo" ]] || die 'vulkaninfo is missing. Run this stage with --install-user-libs first.'
task_vulkan_output="${task_data_root%/}/logs/$(date -u +%Y%m%dT%H%M%SZ)_vulkaninfo.txt"
if ! timeout --foreground 30s "$task_conda" run --no-capture-output --prefix "$task_thor_prefix" \
  env "LD_LIBRARY_PATH=${task_thor_prefix}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
  "${task_thor_prefix}/bin/vulkaninfo" --summary > "$task_vulkan_output" 2>&1; then
  cat "$task_vulkan_output"
  die 'Vulkan enumeration failed or exceeded 30 seconds. Inspect host NVIDIA driver/ICD with the administrator; do not rewrite global ICD files or start Unity.'
fi
cat "$task_vulkan_output"
if ! "${task_thor_prefix}/bin/python" - "$task_vulkan_output" <<'PY'
import re
import sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
blocks = re.split(r"(?m)^GPU\d+:\s*$", text)
found = False
for block in blocks[1:]:
    vendor = re.search(r"(?im)^\s*vendorID\s*=\s*0x10de\s*$", block)
    name = re.search(r"(?im)^\s*deviceName\s*=\s*([^\r\n]+)", block)
    # The vendor ID identifies NVIDIA, including cards whose name starts with
    # Tesla/Quadro rather than the literal word NVIDIA.
    if vendor and name and not re.search(r"llvmpipe|swiftshader", name.group(1), re.I):
        found = True
        break
sys.exit(0 if found else 1)
PY
then
  die 'Vulkan did not enumerate an NVIDIA GPU. CPU/llvmpipe alone is insufficient; ask the server administrator to expose a working NVIDIA driver and ICD. Unity was not started.'
fi

task_scoped_library_path="${task_thor_prefix}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
if [[ -f "${task_thor_prefix}/bin/python" ]]; then
  if ! "$task_conda" run --no-capture-output --prefix "$task_thor_prefix" \
    env "LD_LIBRARY_PATH=$task_scoped_library_path" python - "$task_install" <<'PY'
import ctypes
import sys
from ctypes.util import find_library
ctypes.CDLL("libEGL.so.1")
vulkan_name = find_library("vulkan")
assert vulkan_name, "ctypes.util.find_library('vulkan') returned nothing"
ctypes.CDLL(vulkan_name)
print("libEGL.so.1 loaded; Vulkan loader resolved by ctypes.util.find_library:", vulkan_name)
try:
    import cv2
    print("cv2 import passed", cv2.__version__)
except ModuleNotFoundError as exc:
    if sys.argv[1] == "true" and exc.name == "cv2":
        print("cv2 check deferred until 01_setup_env.sh installs the pinned project requirements")
    else:
        raise
PY
  then die 'User-space EGL/Vulkan loader validation failed.'; fi
fi

printf '\nPASS: NVIDIA is visible through nvidia-smi and Vulkan. Scoped graphics libraries are recorded for later THOR calls.\n'
printf 'Run 01_setup_env.sh, then rerun this script without --install-user-libs to check cv2 import as well.\n'
