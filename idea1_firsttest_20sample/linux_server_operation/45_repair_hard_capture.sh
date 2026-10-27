#!/usr/bin/env bash
# One representative per group, plus all four nested variants; no model run.
set -Eeuo pipefail
operation_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($# == 0)); then
  set -- --cases H01-1,H02-1,H03-1,H04-1,H04-2,H04-3,H04-4,H05-1
fi
exec bash "$operation_dir/43_generate_hard_groups.sh" "$@"
