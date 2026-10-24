# Portable per-user defaults shared by server operation scripts.
# Source-only: does not change HOME, install software, or configure global libraries.

_lso_paths_home="${SERVER_HOME:-${HOME:?HOME must be set or SERVER_HOME supplied}}"
_lso_paths_profile="${THOR_SERVER_PROFILE:-auto}"
case "$_lso_paths_profile" in
  auto)
    if [[ -d "${_lso_paths_home%/}/autodl-tmp" && -w "${_lso_paths_home%/}/autodl-tmp" ]]; then
      _lso_paths_profile="autodl"
    else
      _lso_paths_profile="home"
    fi
    ;;
  home|autodl) ;;
  *) printf 'ERROR: THOR_SERVER_PROFILE must be auto, home, or autodl (got %s)\n' "$_lso_paths_profile" >&2; return 2 ;;
esac

SERVER_HOME="$_lso_paths_home"
THOR_SERVER_PROFILE="$_lso_paths_profile"
if [[ "$THOR_SERVER_PROFILE" == autodl ]]; then
  _lso_paths_data="${SERVER_HOME%/}/autodl-tmp/idea1_firsttest_20sample"
  _lso_paths_model="${SERVER_HOME%/}/autodl-tmp/model/qwen3.5-4b"
else
  _lso_paths_data="${SERVER_HOME%/}/experiment_data/idea1_firsttest_20sample"
  _lso_paths_model="${SERVER_HOME%/}/model/qwen3.5-4b"
fi

DATA_ROOT="${DATA_ROOT:-$_lso_paths_data}"
QWEN_MODEL_DIR="${QWEN_MODEL_DIR:-$_lso_paths_model}"
OLD_DATA_ROOT="${OLD_DATA_ROOT:-${SERVER_HOME%/}/will_not_be_push_to_git/idea1_firsttest_20sample}"
CONDA_ENV="${CONDA_ENV:-thor20}"
THOR_PLATFORM="${THOR_PLATFORM:-CloudRendering}"
QWEN_ENV_PREFIX="${QWEN_ENV_PREFIX:-${DATA_ROOT%/}/model_env}"
THOR_ENV_PREFIX="${THOR_ENV_PREFIX:-}"
PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${DATA_ROOT%/}/pycache}"

if [[ -z "${CONDA_EXE:-}" ]]; then
  CONDA_EXE="$(command -v conda || true)"
  if [[ -z "$CONDA_EXE" ]]; then
    for _lso_conda_candidate in \
      "${SERVER_HOME%/}/miniforge3/bin/conda" \
      "${SERVER_HOME%/}/miniconda3/bin/conda" \
      "${SERVER_HOME%/}/anaconda3/bin/conda" \
      /opt/conda/bin/conda; do
      if [[ -x "$_lso_conda_candidate" ]]; then CONDA_EXE="$_lso_conda_candidate"; break; fi
    done
  fi
fi
export SERVER_HOME THOR_SERVER_PROFILE DATA_ROOT QWEN_MODEL_DIR OLD_DATA_ROOT
export CONDA_ENV THOR_PLATFORM QWEN_ENV_PREFIX THOR_ENV_PREFIX CONDA_EXE
export PYTHONPYCACHEPREFIX
unset _lso_paths_home _lso_paths_profile _lso_paths_data _lso_paths_model _lso_conda_candidate
