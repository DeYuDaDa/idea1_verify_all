#!/usr/bin/env bash
# Two minimal native rechecks; no environment installation or model run.
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($# > 1)) || { (($# == 1)) && [[ "$1" != R1 && "$1" != R2 ]]; }; then
  printf 'Usage: bash linux_server_operation/41_recheck_r1_r2.sh [R1|R2]\n' >&2
  exit 2
fi
selection=()
if (($#)); then
  case "$1" in
    R1) selection=(--cases R1_intact_pickup,R1_intact_control,R1_apple_out_pickup,R1_apple_out_control,R1_bowl_and_apple_out_pickup,R1_bowl_and_apple_out_control,R1_apple_reparented_pickup,R1_apple_reparented_control) ;;
    R2) selection=(--cases R2_uncooked_inside,R2_uncooked_outside,R2_cooked_cooled_inside,R2_cooked_cooled_outside) ;;
  esac
fi
printf 'R1: four relation configurations x pickup/no-pickup. R2: cooked history x location.\n'
printf 'One room (FloorPlan1), actual pre-cooking and natural cooling, no CookObject shortcut.\n'
printf 'Existing-frame previews are best effort; picture failure does not stop native checks.\n'
exec bash "$script_dir/31_probe_native_mechanisms.sh" \
  --suite rechecks --scenes FloorPlan1 --max-scenes 1 --view-mode passive "${selection[@]}"
