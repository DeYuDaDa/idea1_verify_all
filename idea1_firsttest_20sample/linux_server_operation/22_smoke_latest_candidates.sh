#!/usr/bin/env bash
# Select the latest completed v2 construction batch, then test one public input.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "The thor20 bookkeeping environment is missing."
task_export_root="$(run_python - "$DATA_ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
batches = sorted(p for p in root.glob('exports_scope_v2_*') if p.is_dir())
if not batches:
    raise SystemExit('No new v2 batch exists. Run step 21 first.')
batch = batches[-1]
record_path = batch / '_run' / 'execution_result.json'
if not record_path.is_file():
    raise SystemExit('Latest batch has not finished collection; do not fall back to old samples.')
record = json.loads(record_path.read_text(encoding='utf-8'))
if not record.get('candidate_pairs'):
    raise SystemExit('Latest batch has no successful candidates; review its failure evidence first.')
if not (batch / 'data' / 'input').is_dir():
    raise SystemExit('Latest candidate public inputs are absent.')
print(batch)
PY
)"
printf 'Single-sample debug input batch: %s\n' "$task_export_root"
export DATA_ROOT CONDA_EXE
bash "${PROJECT_DIR%/}/linux_server_operation/20_run_model.sh" \
  --export-root "$task_export_root" --limit 1 --debug-unreviewed
