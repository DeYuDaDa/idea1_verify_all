#!/usr/bin/env bash
# Only the four Step41 setup-unavailable arms; R2 and successful R1 pairs stay retired.
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if (($#)); then
  printf 'Usage: bash linux_server_operation/42_complete_r1_bundle_arms.sh\n' >&2
  exit 2
fi
printf 'Retry only R1 bowl-bundle removal and apple reparenting, each with no-pickup control.\n'
printf 'Bounded native Put destinations/seeds; held-bowl and settled-content checks remain strict.\n'
exec bash "$script_dir/31_probe_native_mechanisms.sh" \
  --suite rechecks --scenes FloorPlan1 --max-scenes 1 --view-mode passive \
  --cases R1_bowl_and_apple_out_pickup,R1_bowl_and_apple_out_control,R1_apple_reparented_pickup,R1_apple_reparented_control
