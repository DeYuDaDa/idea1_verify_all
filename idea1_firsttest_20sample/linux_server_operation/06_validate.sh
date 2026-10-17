#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. Run 01_setup_env.sh first."
require_file "${PROJECT_DIR%/}/validate.py"
export_root="${1:-${DATA_ROOT%/}/exports}"
[[ -d "$export_root" ]] || die "Export root does not exist: $export_root"
if [[ -n "${2:-}" ]]; then
  run_python "${PROJECT_DIR%/}/validate.py" "$export_root" --strict --pairs "$2"
else
  run_python "${PROJECT_DIR%/}/validate.py" "$export_root" --strict
fi
