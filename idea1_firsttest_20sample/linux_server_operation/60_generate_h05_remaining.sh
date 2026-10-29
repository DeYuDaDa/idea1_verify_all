#!/usr/bin/env bash
# Reuse accepted H05-3; remaining cases still require program and visual review.
set -Eeuo pipefail
if (($#)); then printf 'No arguments: generates H05-1/2/4 only.\n' >&2; exit 2; fi
operation_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export LSO_STAGE=60_generate_h05_remaining
exec bash "$operation_dir/43_generate_hard_groups.sh" --cases H05-1,H05-2,H05-4 --scene-limit 1 --capture-mode debug
