#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. Run 01_setup_env.sh first."
require_file "${PROJECT_DIR%/}/generator.py"
mkdir -p -- "${DATA_ROOT%/}/exports"
run_python "${PROJECT_DIR%/}/generator.py" \
  --pairs C13,T16,M01,S05,B19,P20 \
  --output-root "${DATA_ROOT%/}/exports" \
  --platform "$THOR_PLATFORM"
