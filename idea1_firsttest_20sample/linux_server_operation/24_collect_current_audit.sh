#!/usr/bin/env bash
# Read-only collection of the current data-generation and model-audit artifacts.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "Linux server only."
resolve_conda

export_root=""
while (($#)); do
  case "$1" in
    --export-root)
      (($# >= 2)) || die "--export-root requires a path."
      export_root="$2"; shift 2 ;;
    --export-root=*) export_root="${1#*=}"; shift ;;
    *) die "Unknown argument: $1" ;;
  esac
done

args=("$PROJECT_DIR/linux_server_operation/24_collect_current_audit.py" --data-root "$DATA_ROOT" --log "$_lso_log")
[[ -z "$export_root" ]] || args+=(--export-root "$export_root")
run_python "${args[@]}"
