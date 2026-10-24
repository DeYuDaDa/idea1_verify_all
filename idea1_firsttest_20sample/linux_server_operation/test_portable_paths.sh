#!/usr/bin/env bash
# Server-only contract check for portable path selection and Conda dispatch.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
task_tmp="$(mktemp -d)"
trap 'rm -rf -- "$task_tmp"' EXIT

task_home="$task_tmp/home"
mkdir -p -- "$task_home"
task_data="$task_tmp/data"
task_fake_conda="$task_tmp/fake-conda"
task_capture="$task_tmp/conda-args.txt"
cat > "$task_fake_conda" <<'SH'
#!/usr/bin/env bash
printf '<%s>\n' "$@" >> "$CAPTURE_ARGS"
SH
chmod +x "$task_fake_conda"
export CAPTURE_ARGS="$task_capture"

(
  export HOME="$task_home" SERVER_HOME="$task_home" THOR_SERVER_PROFILE=auto
  unset DATA_ROOT QWEN_MODEL_DIR THOR_ENV_PREFIX CONDA_EXE
  source "$SCRIPT_DIR/server_paths.sh"
  [[ "$DATA_ROOT" == "$task_home/experiment_data/idea1_firsttest_20sample" ]]
  [[ "$QWEN_MODEL_DIR" == "$task_home/model/qwen3.5-4b" ]]
  [[ -z "$THOR_ENV_PREFIX" ]]
)

mkdir -p -- "$task_home/autodl-tmp"
(
  export HOME="$task_home" SERVER_HOME="$task_home" THOR_SERVER_PROFILE=auto
  unset DATA_ROOT QWEN_MODEL_DIR THOR_ENV_PREFIX CONDA_EXE
  source "$SCRIPT_DIR/server_paths.sh"
  [[ "$DATA_ROOT" == "$task_home/autodl-tmp/idea1_firsttest_20sample" ]]
  [[ "$QWEN_MODEL_DIR" == "$task_home/autodl-tmp/model/qwen3.5-4b" ]]
  [[ -z "$THOR_ENV_PREFIX" ]]
)

mkdir -p -- "$task_tmp/prefix/bin"
printf '#!/usr/bin/env bash\nexit 0\n' > "$task_tmp/prefix/bin/python"
chmod +x "$task_tmp/prefix/bin/python"
(
  export SERVER_HOME="$task_home" THOR_SERVER_PROFILE=home DATA_ROOT="$task_data"
  export QWEN_MODEL_DIR="$task_home/model/qwen3.5-4b" THOR_ENV_PREFIX="$task_tmp/prefix"
  export CONDA_EXE="$task_fake_conda" PROJECT_DIR
  unset LD_LIBRARY_PATH
  source "$SCRIPT_DIR/common.sh"
  env_exists
  mkdir -p -- "$task_data"
  printf 'THOR_USER_LIBRARY_DIR=%q\n' "$task_tmp/prefix/lib" > "$task_data/thor_graphics.env"
  run_python -c 'pass'
  THOR_DISABLE_GRAPHICS_ENV=1 run_python -c 'pass'
)
grep -F -- "<--prefix>" "$task_capture" >/dev/null
grep -F -- "<$task_tmp/prefix>" "$task_capture" >/dev/null
grep -F -- "<env>" "$task_capture" >/dev/null
grep -F -- "<LD_LIBRARY_PATH=$task_tmp/prefix/lib>" "$task_capture" >/dev/null
[[ "$(grep -Fc -- '<env>' "$task_capture")" -eq 1 ]]

: > "$task_capture"
(
  export SERVER_HOME="$task_home" THOR_SERVER_PROFILE=autodl DATA_ROOT="$task_data"
  export CONDA_EXE="$task_fake_conda" CONDA_ENV=thor20 PROJECT_DIR
  unset THOR_ENV_PREFIX
  source "$SCRIPT_DIR/common.sh"
  run_python -c 'pass'
)
grep -F -- "<-n>" "$task_capture" >/dev/null
grep -F -- "<thor20>" "$task_capture" >/dev/null

printf 'Portable path profile and Conda dispatch checks passed.\n'
