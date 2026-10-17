#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing. Run 01_setup_env.sh first."
require_file "${PROJECT_DIR%/}/package_offline.py"
export_root="${1:-${DATA_ROOT%/}/exports}"
package_path="${2:-${DATA_ROOT%/}/offline_public_input.zip}"
[[ -d "$export_root" ]] || die "Export root does not exist: $export_root"
if [[ -n "${3:-}" ]]; then
  run_python "${PROJECT_DIR%/}/package_offline.py" --root "$export_root" --output "$package_path" --pairs "$3"
else
  run_python "${PROJECT_DIR%/}/package_offline.py" --root "$export_root" --output "$package_path"
fi
