#!/usr/bin/env bash
# Carry-aware detour diagnosis on one question, never all H02 variants yet.
set -Eeuo pipefail
if (($#)); then printf 'No arguments: rechecks H02-1 only.\n' >&2; exit 2; fi
operation_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export LSO_STAGE=61_recheck_h02_1
exec bash "$operation_dir/43_generate_hard_groups.sh" --cases H02-1 --scene-limit 1 --capture-mode debug
