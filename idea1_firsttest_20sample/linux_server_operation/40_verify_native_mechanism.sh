#!/usr/bin/env bash
# One clean native mechanism check; not a dataset or a full 45-case run.
# source "$HOME/.config/thor20/server.env" &&
# cd "$HOME/idea1_verify_all/idea1_firsttest_20sample" &&
# bash linux_server_operation/40_verify_native_mechanism.sh
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($#)); then
  printf 'Usage: bash linux_server_operation/40_verify_native_mechanism.sh\n' >&2
  exit 2
fi
printf 'Purpose: verify two-level nested carry in FloorPlan1 from native relations and motion.\n'
printf 'Only one unresolved/previously observer-invalidated condition is rerun.\n'
printf 'Native-only mode: zero PNGs and no rgb directory are intentional.\n'
printf 'Read CHECK results and native displacement values; a small ZIP is expected.\n'
exec bash "$script_dir/31_probe_native_mechanisms.sh" \
  --cases F10_nested_carry --scenes FloorPlan1 --max-scenes 1 \
  --sample-steps 0,1,4,12,36 --view-mode none
