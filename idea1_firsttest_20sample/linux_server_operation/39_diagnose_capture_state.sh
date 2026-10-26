#!/usr/bin/env bash
# Optional camera diagnostic. Physics-control motion flags are separately
# accounted for; other state changes still reject image evidence.
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($#)); then
  printf 'Usage: bash linux_server_operation/39_diagnose_capture_state.sh\n' >&2
  exit 2
fi
printf 'One-case camera/state diagnostic: first offending action and old/new fields.\n'
printf 'Physics-control motion flags are separately recorded; actual pose/attribute/relation changes still reject evidence.\n'
printf 'For native mechanism conclusions use stage 40; this camera check is optional.\n'
exec bash "$script_dir/31_probe_native_mechanisms.sh" \
  --cases f1_coffee_activate_then_enter --scenes FloorPlan2 --max-scenes 1 \
  --sample-steps 0 --view-mode planned
