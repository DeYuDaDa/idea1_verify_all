#!/usr/bin/env bash
# H01-1 is human-accepted and frozen. Generate only missing family members.
set -Eeuo pipefail
if (($#)); then printf 'No arguments: generates H01-2/3/4 only.\n' >&2; exit 2; fi
operation_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export LSO_STAGE=59_generate_h01_remaining
exec bash "$operation_dir/43_generate_hard_groups.sh" --cases H01-2,H01-3,H01-4 --scene-limit 1 --capture-mode debug
