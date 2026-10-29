#!/usr/bin/env bash
# H01-1 only; no model, no other cases, no dependency installation.
set -Eeuo pipefail
if (($#)); then
  printf 'This entry runs H01-1 only and takes no arguments.\n' >&2
  exit 2
fi
operation_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export LSO_STAGE=56_generate_h01_1
exec bash "$operation_dir/43_generate_hard_groups.sh" \
  --cases H01-1 --scene-limit 1 --capture-mode debug
