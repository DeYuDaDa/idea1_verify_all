#!/usr/bin/env bash
# Check calibration restoration, four-surface selection, and uncooked history in debug capture.
# H04-1 still has an unresolved native return-to-bowl placement; request it explicitly for diagnostics.
set -Eeuo pipefail
operation_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($# == 0)); then
  set -- --cases H01-1,H02-1,H05-3 --scene-limit 2 --capture-mode debug
fi
exec bash "$operation_dir/43_generate_hard_groups.sh" "$@"
