#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Run 01_setup_env.sh first."
run_python "${PROJECT_DIR%/}/validate.py" "${DATA_ROOT%/}/exports" \
  --pairs C13,T16,M01,S05,B19,P20
printf '\nThis is a diagnostic report, not approval. Read fail/inconclusive/pending_review before continuing.\n'
