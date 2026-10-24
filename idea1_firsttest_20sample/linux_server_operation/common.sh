# Shared settings and logging for the Linux server operation scripts.
# This file is sourced by the numbered scripts; it is not an executable stage.

set -Eeuo pipefail

_lso_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-$(cd -- "${_lso_script_dir}/.." && pwd -P)}"
source "${_lso_script_dir}/server_paths.sh"
if [[ -n "$THOR_ENV_PREFIX" ]]; then
  _lso_conda_selector=(--prefix "$THOR_ENV_PREFIX")
else
  _lso_conda_selector=(-n "$CONDA_ENV")
fi
LOG_DIR="${DATA_ROOT%/}/logs"

# Refuse accidentally placing non-Git outputs anywhere inside this repository.
_lso_repo_root="$(cd -- "${PROJECT_DIR}/.." && pwd -P)"
_lso_data_absolute="$(realpath -m -- "$DATA_ROOT")"
case "${_lso_data_absolute%/}/" in
  "${_lso_repo_root%/}/"*)
    printf 'ERROR: DATA_ROOT must be outside idea1_verify_all: %s\n' "$DATA_ROOT" >&2
    exit 1
    ;;
esac

mkdir -p -- "$LOG_DIR"
_lso_stage="${LSO_STAGE:-$(basename -- "$0" .sh)}"
_lso_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
_lso_log="${LOG_DIR}/${_lso_timestamp}_${_lso_stage}.log"
exec > >(tee -a "$_lso_log") 2>&1

trap 'rc=$?; if (( rc != 0 )); then printf "ERROR: %s failed (exit %s). Log: %s\n" "$_lso_stage" "$rc" "$_lso_log" >&2; fi' EXIT

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_file() {
  [[ -f "$1" ]] || die "Required file not found: $1"
}

resolve_conda() {
  if [[ -n "$CONDA_EXE" ]]; then
    [[ -x "$CONDA_EXE" ]] || die "CONDA_EXE is set but is not executable: $CONDA_EXE"
  else
    source "${_lso_script_dir}/server_paths.sh"
    [[ -n "$CONDA_EXE" ]] || die "Conda was not found. Install/configure Conda on the Linux server, then set CONDA_EXE=/absolute/path/to/conda. No installer or large package download was started."
  fi
}

env_exists() {
  if [[ -n "$THOR_ENV_PREFIX" ]]; then
    [[ -x "${THOR_ENV_PREFIX%/}/bin/python" ]]
    return
  fi
  local base_python
  base_python="$("$CONDA_EXE" info --base)/bin/python"
  [[ -x "$base_python" ]] || base_python="$("$CONDA_EXE" info --base)/bin/python3"
  [[ -x "$base_python" ]] || die "Could not find Python in Conda base; set CONDA_EXE to a valid Conda installation."
  "$CONDA_EXE" env list --json | "$base_python" -c 'import json,os,sys; name=sys.argv[1]; paths=json.load(sys.stdin).get("envs", []); sys.exit(0 if any(os.path.basename(os.path.normpath(p)) == name for p in paths) else 1)' "$CONDA_ENV"
}

_thor_conda_run() {
  "$CONDA_EXE" run --no-capture-output "${_lso_conda_selector[@]}" "$@"
}

run_python() {
  local graphics_env="${DATA_ROOT%/}/thor_graphics.env" user_library_dir=""
  if [[ "${THOR_DISABLE_GRAPHICS_ENV:-0}" != 1 && -f "$graphics_env" ]]; then
    # Stage 33 writes a single shell-safe THOR_USER_LIBRARY_DIR assignment.
    unset THOR_USER_LIBRARY_DIR
    source "$graphics_env"
    user_library_dir="${THOR_USER_LIBRARY_DIR:-}"
  fi
  if [[ -n "$user_library_dir" ]]; then
    _thor_conda_run env "LD_LIBRARY_PATH=${user_library_dir}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" python "$@"
  else
    _thor_conda_run python "$@"
  fi
}

print_settings() {
  printf 'Stage: %s\nProject: %s\nData root: %s\nConda env: %s\nTHOR platform: %s\nLog: %s\n' \
    "$_lso_stage" "$PROJECT_DIR" "$DATA_ROOT" "${THOR_ENV_PREFIX:-$CONDA_ENV}" "$THOR_PLATFORM" "$_lso_log"
}
