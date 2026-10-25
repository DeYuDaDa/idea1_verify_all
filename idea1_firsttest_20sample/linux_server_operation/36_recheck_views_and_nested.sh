#!/usr/bin/env bash
# Run from the migrated server after syncing code:
# source "$HOME/.config/thor20/server.env" &&
# cd "$HOME/idea1_verify_all/idea1_firsttest_20sample" &&
# bash linux_server_operation/36_recheck_views_and_nested.sh
#
# F1 device views, water/contact view, single-layer carry and F10 setup repairs.
# 8 templates x 2 scenes, not the entire 45-template batch. All outputs go to a
# fresh DATA_ROOT/mechanism_probe_* directory; original evidence is preserved.
# Expected evidence: role-based external RGBs and per-camera mask diagnostics,
# same-time view_frames groups, camera intervention state checks, and bounded
# F10 candidate failures or native observations. A zero exit code is not a claim
# that every setup/visual cue is valid. No model or Markdown review is generated.
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($#)); then
  printf 'Usage: bash linux_server_operation/36_recheck_views_and_nested.sh\n' >&2
  exit 2
fi
printf 'Checking planned evidence views and outer-to-inner F10 setup in FloorPlan1/FloorPlan2.\n'
bash "$script_dir/31_probe_native_mechanisms.sh" \
  --cases f1_coffee_activate_then_enter,f1_toaster_enter_then_activate,f1_microwave_enter_then_activate,f5_dirty_empty_water_on,F7_retained,F10_nested_carry,F10_nested_heat,F10_nested_wash \
  --scenes FloorPlan1,FloorPlan2 --max-scenes 2 --view-mode planned
