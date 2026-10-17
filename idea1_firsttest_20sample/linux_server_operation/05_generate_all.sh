#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. Run 01_setup_env.sh first."
require_file "${PROJECT_DIR%/}/generator.py"
mkdir -p -- "${DATA_ROOT%/}/exports"
printf 'Starting the full generation run with resume enabled. This is the only full-run stage.\n'
run_python "${PROJECT_DIR%/}/generator.py" \
  --resume \
  --output-root "${DATA_ROOT%/}/exports" \
  --platform "$THOR_PLATFORM"
