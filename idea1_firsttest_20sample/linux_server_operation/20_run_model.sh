#!/usr/bin/env bash
# Run the offline Qwen inference script inside the isolated step-17 environment.
set -Eeuo pipefail

DATA_ROOT="${DATA_ROOT:-/root/autodl-tmp/idea1_firsttest_20sample}"
MODEL_DIR="${QWEN_MODEL_DIR:-/root/autodl-tmp/model/qwen3.5-4b}"
ENV_PREFIX="${QWEN_ENV_PREFIX:-${DATA_ROOT%/}/model_env}"
THOR20_ENV="${THOR20_ENV:-thor20}"
CONDA_EXE="${CONDA_EXE:-}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$PROJECT_DIR/.." && pwd -P)"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '[20_run_model] %s\n' "$*"; }

[[ "$(uname -s)" == Linux ]] || die "Linux server only; do not run this script on Windows."
data_root_absolute="$(realpath -m -- "$DATA_ROOT")"
case "${data_root_absolute%/}/" in
  "${REPO_ROOT%/}/"*) die "DATA_ROOT must be outside the repository: $DATA_ROOT" ;;
esac
[[ -d "$ENV_PREFIX" && -x "$ENV_PREFIX/bin/python" ]] || die "Step-17 environment is unavailable/incomplete: $ENV_PREFIX. Finish and review step 17 first."
[[ -d "$MODEL_DIR" && -f "$MODEL_DIR/config.json" ]] || die "Local Qwen3.5 model/config is missing: $MODEL_DIR"

if [[ -z "$CONDA_EXE" ]]; then
  CONDA_EXE="$(command -v conda || true)"
  if [[ -z "$CONDA_EXE" ]]; then
    for candidate in /root/miniconda3/bin/conda /root/anaconda3/bin/conda /opt/conda/bin/conda; do
      if [[ -x "$candidate" ]]; then CONDA_EXE="$candidate"; break; fi
    done
  fi
fi
[[ -n "$CONDA_EXE" && -x "$CONDA_EXE" ]] || die "Conda was not found; set CONDA_EXE=/absolute/path/to/conda."

export_root=""
review_mode=""
args=("$@")
index=0
while (( index < ${#args[@]} )); do
  arg="${args[$index]}"
  case "$arg" in
    --export-root)
      (( index + 1 < ${#args[@]} )) || die "--export-root requires a path."
      export_root="${args[$((index + 1))]}"
      ((index += 2))
      ;;
    --export-root=*)
      export_root="${arg#*=}"
      ((index += 1))
      ;;
    --review-approved)
      [[ -z "$review_mode" ]] || die "Choose only one of --review-approved or --debug-unreviewed."
      review_mode="approved"
      ((index += 1))
      ;;
    --debug-unreviewed)
      [[ -z "$review_mode" ]] || die "Choose only one of --review-approved or --debug-unreviewed."
      review_mode="debug"
      ((index += 1))
      ;;
    *) ((index += 1)) ;;
  esac
done
[[ -n "$export_root" && -d "$export_root" ]] || die "Pass --export-root pointing to an export containing data/input and hidden_gold."
[[ -n "$review_mode" ]] || die "Pass --review-approved or the explicit --debug-unreviewed bypass."

PKG_CACHE="${DATA_ROOT%/}/conda_pkgs"
PIP_CACHE="${DATA_ROOT%/}/pip_cache"
HF_HOME="${DATA_ROOT%/}/hf_home"
TMPDIR="${DATA_ROOT%/}/tmp"
LOG_DIR="${DATA_ROOT%/}/logs"
mkdir -p -- "$PKG_CACHE" "$PIP_CACHE" "$HF_HOME" "$TMPDIR" "$LOG_DIR"
export CONDA_PKGS_DIRS="$PKG_CACHE" PIP_CACHE_DIR="$PIP_CACHE" HF_HOME
export HF_HUB_CACHE="$HF_HOME/hub" TMPDIR TMP="$TMPDIR" TEMP="$TMPDIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/${timestamp}_20_run_model.log"
exec > >(tee -a "$LOG_FILE") 2>&1
trap 'rc=$?; if (( rc != 0 )); then printf "ERROR: step 20 exited with status %s. Preserve log: %s\n" "$rc" "$LOG_FILE" >&2; fi' EXIT

note "Project directory: $PROJECT_DIR"
note "Isolated environment: $ENV_PREFIX"
note "Model directory: $MODEL_DIR (local_files_only; no model download)"
note "Logs and runtime caches: $DATA_ROOT"
note "Forwarding inference arguments exactly as provided. Choose --limit 1 for the smoke run; --all is explicit."

unset QWEN_EXTERNAL_STRICT_VALIDATION
if [[ "$review_mode" == "approved" ]]; then
  note "Running strict export/review validation in the separate $THOR20_ENV Conda environment before model inference."
  "$CONDA_EXE" run --no-capture-output --name "$THOR20_ENV" \
    python "$PROJECT_DIR/validate.py" "$export_root" --strict
  export QWEN_EXTERNAL_STRICT_VALIDATION=pass
else
  note "Explicit unreviewed debug mode; strict review validation is not asserted."
fi

"$CONDA_EXE" run --no-capture-output --prefix "$ENV_PREFIX" \
  python "$PROJECT_DIR/offline_run_qwen.py" \
  --model-dir "$MODEL_DIR" --outputs-root "${DATA_ROOT%/}/model_outputs" "$@"
