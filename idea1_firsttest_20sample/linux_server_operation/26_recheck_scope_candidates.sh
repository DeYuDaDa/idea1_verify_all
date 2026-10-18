#!/usr/bin/env bash
# Prepare a public-only one-question diagnostic, test its selector, then run it
# through the existing step-20 inference wrapper unless --prepare-only is set.
# A focused ZIP is attempted on both success and inference failure; it names
# this run directory explicitly so no previous model run can be collected.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
DATA_ROOT="$(realpath -- "$DATA_ROOT")"
LOG_DIR="${DATA_ROOT%/}/logs"
_lso_log="$(realpath -- "$_lso_log")"
export DATA_ROOT
print_settings
[[ "$(uname -s)" == Linux ]] || die "Linux server only."

ENV_PREFIX="${QWEN_ENV_PREFIX:-${DATA_ROOT%/}/model_env}"
ENV_PYTHON="$ENV_PREFIX/bin/python"
[[ -x "$ENV_PYTHON" ]] || die "Step-17 model environment is unavailable: $ENV_PYTHON"

prepare_only=no
source_export=""
while (($#)); do
  case "$1" in
    --prepare-only) prepare_only=yes; shift ;;
    --source-export)
      (($# >= 2)) || die "--source-export requires a directory."
      source_export="$2"; shift 2 ;;
    --source-export=*) source_export="${1#*=}"; shift ;;
    *) die "Unknown argument: $1" ;;
  esac
done

if [[ -z "$source_export" ]]; then
  source_export="$(find "$DATA_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'exports_scope_v2_*' -print | sort | tail -n 1)"
fi
[[ -n "$source_export" && -d "$source_export/data/input" ]] || die "No source export with data/input found; pass --source-export."
source_export="$(realpath -- "$source_export")"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
recheck_dir="${DATA_ROOT%/}/scope_recheck_${timestamp}"
run_dir="$recheck_dir/model_outputs/run_scope_recheck_${timestamp}"
archive="${LOG_DIR%/}/${timestamp}_$$_26_scope_recheck.zip"
archive_log="${LOG_DIR%/}/${timestamp}_$$_26_scope_recheck_operation.log"
helper="$PROJECT_DIR/prepare_scope_recheck.py"
require_file "$helper"

note() { printf '[26_scope_recheck] %s\n' "$*"; }
note "Source export: $source_export"
note "Diagnostic export: $recheck_dir"
note "Purpose: exploratory single-question recheck; not an approved benchmark."

cd -- "$PROJECT_DIR"
"$ENV_PYTHON" -m prepare_scope_recheck prepare \
  --data-root "$DATA_ROOT" --export-root "$source_export" --output-dir "$recheck_dir"

note "Running the focused selector and public-boundary unittest before any model inference."
if ! "$ENV_PYTHON" -m unittest discover -s tests -p test_scope_recheck.py -v; then
  note "Focused tests failed; no model inference will be started. The diagnostic export remains available for inspection."
  cp -- "$_lso_log" "$archive_log"
  "$ENV_PYTHON" -m prepare_scope_recheck package \
    --data-root "$DATA_ROOT" --export-dir "$recheck_dir" --run-dir "$run_dir" \
    --output-zip "$archive" --operation-log "$archive_log" || true
  exit 1
fi

if [[ "$prepare_only" == yes ]]; then
  note "Preparation-only requested; model inference was not started."
  cp -- "$_lso_log" "$archive_log"
  "$ENV_PYTHON" -m prepare_scope_recheck package \
    --data-root "$DATA_ROOT" --export-dir "$recheck_dir" --run-dir "$run_dir" \
    --output-zip "$archive" --operation-log "$archive_log"
  note "Focused archive: $archive"
  exit 0
fi

if bash "$PROJECT_DIR/linux_server_operation/20_run_model.sh" \
  --export-root "$recheck_dir" --outputs-root "$recheck_dir/model_outputs" \
  --run-dir "$run_dir" --all --debug-unreviewed; then
  model_rc=0
else
  model_rc=$?
fi

note "Collecting only this diagnostic export and designated run: $run_dir"
cp -- "$_lso_log" "$archive_log"
"$ENV_PYTHON" -m prepare_scope_recheck package \
  --data-root "$DATA_ROOT" --export-dir "$recheck_dir" --run-dir "$run_dir" \
  --output-zip "$archive" --operation-log "$archive_log"
note "Focused archive: $archive"
if (( model_rc != 0 )); then
  die "Step-20 inference failed (status recorded as nonzero); diagnostic export and any partial run were archived."
fi
note "Completed focused run. Inspect raw predictions and manifest; original strict format labels are unchanged."
