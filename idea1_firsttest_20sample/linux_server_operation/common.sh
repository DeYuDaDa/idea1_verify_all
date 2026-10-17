# Shared settings and logging for the Linux server operation scripts.
# This file is sourced by the numbered scripts; it is not an executable stage.

set -Eeuo pipefail

_lso_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="${PROJECT_DIR:-$(cd -- "${_lso_script_dir}/.." && pwd -P)}"
DATA_ROOT="${DATA_ROOT:-/root/will_not_be_push_to_git/idea1_firsttest_20sample}"
CONDA_EXE="${CONDA_EXE:-}"
CONDA_ENV="${CONDA_ENV:-thor20}"
THOR_PLATFORM="${THOR_PLATFORM:-CloudRendering}"
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
    CONDA_EXE="$(command -v conda || true)"
    if [[ -z "$CONDA_EXE" ]]; then
      for candidate in /root/miniconda3/bin/conda /root/anaconda3/bin/conda /opt/conda/bin/conda; do
        if [[ -x "$candidate" ]]; then CONDA_EXE="$candidate"; break; fi
      done
    fi
    [[ -n "$CONDA_EXE" ]] || die "Conda was not found. Install/configure Conda on the Linux server, then set CONDA_EXE=/absolute/path/to/conda. No installer or large package download was started."
  fi
}

env_exists() {
  local base_python
  base_python="$("$CONDA_EXE" info --base)/bin/python"
  [[ -x "$base_python" ]] || base_python="$("$CONDA_EXE" info --base)/bin/python3"
  [[ -x "$base_python" ]] || die "Could not find Python in Conda base; set CONDA_EXE to a valid Conda installation."
  "$CONDA_EXE" env list --json | "$base_python" -c 'import json,os,sys; name=sys.argv[1]; paths=json.load(sys.stdin).get("envs", []); sys.exit(0 if any(os.path.basename(os.path.normpath(p)) == name for p in paths) else 1)' "$CONDA_ENV"
}

run_python() {
  "$CONDA_EXE" run --no-capture-output -n "$CONDA_ENV" python "$@"
}

print_settings() {
  printf 'Stage: %s\nProject: %s\nData root: %s\nConda env: %s\nTHOR platform: %s\nLog: %s\n' \
    "$_lso_stage" "$PROJECT_DIR" "$DATA_ROOT" "$CONDA_ENV" "$THOR_PLATFORM" "$_lso_log"
}
