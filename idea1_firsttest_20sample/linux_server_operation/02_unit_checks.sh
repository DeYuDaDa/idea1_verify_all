#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
require_file "${PROJECT_DIR%/}/requirements.txt"
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. Run 01_setup_env.sh first."

cd -- "$PROJECT_DIR"
printf 'Compiling project Python files (compile only; no simulator launch).\n'
run_python -m compileall -q .
printf 'Running unittest discovery. Tests are maintained separately under tests/.\n'
run_python -m unittest discover -s tests -v
