#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Run 01_setup_env.sh first."
[[ $# -eq 2 ]] || die "Usage: bash linux_server_operation/06b_apply_review.sh /absolute/path/review_form.json reviewer_name"
run_python "${PROJECT_DIR%/}/review.py" --root "${DATA_ROOT%/}/exports" --apply "$1" --reviewer "$2"
printf '\nReview evidence recorded. Run 06_validate.sh for the intended pair subset before packaging.\n'
