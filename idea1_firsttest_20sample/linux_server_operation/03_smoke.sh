#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. Run 01_setup_env.sh first."
require_file "${PROJECT_DIR%/}/probe.py"
scene="${1:-FloorPlan1}"
case "$scene" in -* ) die "Scene must be a scene name, not an option: $scene" ;; esac
if [[ "$THOR_PLATFORM" == CloudRendering ]]; then
  task_build_checker="${PROJECT_DIR%/}/linux_server_operation/13_thor_build.py"
  require_file "$task_build_checker"
  printf 'Checking the pinned local CloudRendering cache; no build download is started here.\n'
  if ! run_python "$task_build_checker" --check-cache --data-root "$DATA_ROOT"; then
    die "CloudRendering cache is not ready. Run linux_server_operation/13_prepare_thor_build.sh or import the official ZIP as documented in 13_thor_build.md, then rerun this stage."
  fi
fi
run_python "${PROJECT_DIR%/}/probe.py" --output-root "$DATA_ROOT" --platform "$THOR_PLATFORM" --scene "$scene"
