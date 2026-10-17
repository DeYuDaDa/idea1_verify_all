#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. Run 01_setup_env.sh first."
require_file "${PROJECT_DIR%/}/probe.py"
scene="${1:-FloorPlan1}"
case "$scene" in -* ) die "Scene must be a scene name, not an option: $scene" ;; esac
run_python "${PROJECT_DIR%/}/probe.py" --output-root "$DATA_ROOT" --platform "$THOR_PLATFORM" --scene "$scene"
