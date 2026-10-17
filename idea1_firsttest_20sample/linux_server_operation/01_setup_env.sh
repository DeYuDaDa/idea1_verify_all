#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
require_file "${PROJECT_DIR%/}/requirements.txt"
resolve_conda

if env_exists; then
  printf 'Conda environment "%s" already exists; leaving it untouched.\n' "$CONDA_ENV"
  printf 'Checking Python version and reconciling pinned requirements in this environment.\n'
  run_python -c 'import sys; print(sys.version); assert sys.version_info[:2] == (3, 10), "Expected Python 3.10 in existing environment"'
  run_python -m pip install -r "${PROJECT_DIR%/}/requirements.txt"
  run_python -c 'import ai2thor, numpy, cv2; from importlib.metadata import version; expected={"ai2thor":"5.0.0","numpy":"1.23.5","opencv-python":"4.8.1.78"}; actual={name:version(name) for name in expected}; print(actual); assert actual == expected, f"Environment versions differ from requirements: {actual}"'
  exit 0
fi

printf 'Creating dedicated environment "%s" with Python 3.10.\n' "$CONDA_ENV"
printf 'This stage installs only requirements.txt; AI2-THOR runtime assets may be downloaded by a later simulator launch.\n'
"$CONDA_EXE" create -y -n "$CONDA_ENV" python=3.10
"$CONDA_EXE" run --no-capture-output -n "$CONDA_ENV" python -m pip install -r "${PROJECT_DIR%/}/requirements.txt"
run_python -c 'import sys,ai2thor,numpy,cv2; from importlib.metadata import version; expected={"ai2thor":"5.0.0","numpy":"1.23.5","opencv-python":"4.8.1.78"}; actual={name:version(name) for name in expected}; print(sys.version); print(actual); assert actual == expected, f"Installed versions differ from requirements: {actual}"'
