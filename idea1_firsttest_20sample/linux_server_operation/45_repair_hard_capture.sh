#!/usr/bin/env bash
# Native inventory addition + changed layouts only; accepted H04-2/3 stay frozen.
# H04-1 still has an unresolved native return-to-bowl placement; request it explicitly for diagnostics.
set -Eeuo pipefail
operation_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($# == 0)); then
  set -- --cases H01-1,H02-1,H03-1,H04-4,H05-1 --scene-limit 3
fi
exec bash "$operation_dir/43_generate_hard_groups.sh" "$@"
