#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Run 01_setup_env.sh first."
form="${1:-${DATA_ROOT%/}/review_form_${_lso_timestamp}.json}"
[[ ! -e "$form" ]] || die "Review form already exists; choose a new file path to preserve your annotations."
run_python "${PROJECT_DIR%/}/review.py" --root "${DATA_ROOT%/}/exports" --template "$form"
printf '\nReview form: %s\nInspect its frame paths, history/rules and paired controls. Fill checks only after checking the actual evidence.\n' "$form"
