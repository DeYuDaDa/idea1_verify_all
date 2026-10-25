#!/usr/bin/env bash
# Diagnostics only; no relaxation of state-change checks, no full-batch rerun.
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($#)); then
  printf 'Usage: bash linux_server_operation/39_diagnose_capture_state.sh\n' >&2
  exit 2
fi
printf 'One-case camera/state diagnostic: first offending action and old/new fields.\n'
printf 'The guard is unchanged. A nonzero result may preserve the evidence we need.\n'
exec bash "$script_dir/31_probe_native_mechanisms.sh" \
  --cases f1_coffee_activate_then_enter --scenes FloorPlan2 --max-scenes 1 \
  --sample-steps 0 --view-mode planned
