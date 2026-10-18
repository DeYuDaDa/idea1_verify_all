#!/usr/bin/env bash
# Create an isolated, data-disk Qwen3.5 inference environment and inspect local metadata only.
set -Eeuo pipefail

DATA_ROOT="${DATA_ROOT:-/root/autodl-tmp/idea1_firsttest_20sample}"
MODEL_DIR="${QWEN_MODEL_DIR:-/root/autodl-tmp/model/qwen3.5-4b}"
CONDA_EXE="${CONDA_EXE:-}"
ENV_PREFIX="${QWEN_ENV_PREFIX:-${DATA_ROOT%/}/model_env}"
MIN_FREE_KIB=$((20 * 1024 * 1024))
MIN_INSTALL_HEADROOM_KIB=$((8 * 1024 * 1024))

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '[17_setup_model_env] %s\n' "$*"; }

[[ "$(uname -s)" == Linux ]] || die "Linux server only; this script does not run on Windows."
[[ -d "$MODEL_DIR" ]] || die "Local model directory is missing: $MODEL_DIR. This stage does not download model weights."
[[ -f "$MODEL_DIR/config.json" ]] || die "Missing local config.json: $MODEL_DIR/config.json"

if [[ -z "$CONDA_EXE" ]]; then
  CONDA_EXE="$(command -v conda || true)"
  if [[ -z "$CONDA_EXE" ]]; then
    for candidate in /root/miniconda3/bin/conda /root/anaconda3/bin/conda /opt/conda/bin/conda; do
      if [[ -x "$candidate" ]]; then CONDA_EXE="$candidate"; break; fi
    done
  fi
fi
[[ -n "$CONDA_EXE" && -x "$CONDA_EXE" ]] || die "Conda was not found; set CONDA_EXE=/absolute/path/to/conda. Nothing has been installed."

disk_free_kib() {
  df -Pk -- "$1" | awk 'NR == 2 { print $4 }'
}
disk_probe="$DATA_ROOT"
while [[ ! -d "$disk_probe" ]]; do
  parent="$(dirname -- "$disk_probe")"
  [[ "$parent" != "$disk_probe" ]] || die "Could not find an existing parent filesystem for DATA_ROOT=$DATA_ROOT"
  disk_probe="$parent"
done
free_kib="$(disk_free_kib "$disk_probe")"
[[ "$free_kib" =~ ^[0-9]+$ ]] || die "Could not read free space for $DATA_ROOT."
(( free_kib >= MIN_FREE_KIB )) || die "Only $((free_kib / 1024)) MiB free on the DATA_ROOT filesystem; require at least 20480 MiB before creating/downloading the isolated environment."

PKG_CACHE="${DATA_ROOT%/}/conda_pkgs"
PIP_CACHE="${DATA_ROOT%/}/pip_cache"
HF_HOME="${DATA_ROOT%/}/hf_home"
TMPDIR="${DATA_ROOT%/}/tmp"
mkdir -p -- "$DATA_ROOT" "$PKG_CACHE" "$PIP_CACHE" "$HF_HOME" "$TMPDIR" "${DATA_ROOT%/}/logs" "${DATA_ROOT%/}/transfer_reports"
export CONDA_PKGS_DIRS="$PKG_CACHE" PIP_CACHE_DIR="$PIP_CACHE" HF_HOME TMPDIR TMP="$TMPDIR" TEMP="$TMPDIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="${DATA_ROOT%/}/logs/${timestamp}_17_setup_model_env.log"
exec > >(tee -a "$LOG_FILE") 2>&1
trap 'rc=$?; if (( rc != 0 )); then printf "ERROR: step 17 failed (exit %s). Preserve log: %s\n" "$rc" "$LOG_FILE" >&2; fi' EXIT

note "DATA_ROOT=$DATA_ROOT"
note "Model directory=$MODEL_DIR (local files only; weights will not be loaded or downloaded)"
note "New Conda prefix=$ENV_PREFIX"
note "Filesystem probe=$disk_probe; initial free space=$((free_kib / 1024)) MiB; conservative gate=20480 MiB (planning allowance, not a measured package-size sum)."
note "Conda packages, pip cache, Hugging Face cache, and temporary files are redirected to DATA_ROOT."

if [[ -e "$ENV_PREFIX" ]]; then
  [[ -x "$ENV_PREFIX/bin/python" ]] || die "Environment prefix exists but is incomplete; refusing to delete or recreate it: $ENV_PREFIX"
  note "Reusing existing prefix; no Conda environment will be removed or recreated."
else
  "$CONDA_EXE" create --yes --prefix "$ENV_PREFIX" python=3.11 pip
fi

ENV_PYTHON="$ENV_PREFIX/bin/python"
[[ -x "$ENV_PYTHON" ]] || die "Python was not created at $ENV_PYTHON"

# Fixed, stable package set. If any requested package is installed at a different
# version, stop instead of silently upgrading/replacing it.
EXPECTED='{"torch":"2.10.0+cu128","transformers":"5.15.0","accelerate":"1.11.0","Pillow":"11.3.0"}'
set +e
"$ENV_PYTHON" - "$EXPECTED" <<'PY'
import importlib.metadata as md, json, sys
expected=json.loads(sys.argv[1])
bad=[]
for name, want in expected.items():
    try: got=md.version(name)
    except md.PackageNotFoundError: continue
    if got != want: bad.append(f"{name} installed={got}, requested={want}")
if bad:
    print("Version mismatch; refusing implicit upgrade/reinstall:", *bad, sep="\n  ", file=sys.stderr)
    sys.exit(3)
PY
version_status=$?
set -e
(( version_status == 0 )) || die "The environment already contains a conflicting package version. Use a fresh, explicitly reviewed prefix; this script will not upgrade or delete it."

note "Installing only the pinned packages that are not already present."
"$ENV_PYTHON" -m pip install --cache-dir "$PIP_CACHE" --index-url https://download.pytorch.org/whl/cu128 'torch==2.10.0'
"$ENV_PYTHON" -m pip install --cache-dir "$PIP_CACHE" \
  'transformers==5.15.0' 'accelerate==1.11.0' 'Pillow==11.3.0'

free_kib="$(disk_free_kib "$DATA_ROOT")"
(( free_kib >= MIN_INSTALL_HEADROOM_KIB )) || die "After installation only $((free_kib / 1024)) MiB remain; require 8192 MiB headroom before proceeding to any model inference/output stage."

ACTIVATE_FILE="${DATA_ROOT%/}/qwen_model_env.sh"
cat > "$ACTIVATE_FILE" <<EOF
# Source in each server shell before running the separate Qwen inference stage.
export HF_HOME='$HF_HOME'
export HF_HUB_CACHE='$HF_HOME/hub'
export PIP_CACHE_DIR='$PIP_CACHE'
export TMPDIR='$TMPDIR'
export TMP='$TMPDIR'
export TEMP='$TMPDIR'
export CONDA_PKGS_DIRS='$PKG_CACHE'
EOF

REPORT_FILE="${DATA_ROOT%/}/transfer_reports/${timestamp}_17_model_env_report.json"
export REPORT_FILE MODEL_DIR
"$ENV_PYTHON" - <<'PY'
import json, os, platform, importlib.metadata as md
from pathlib import Path
import torch
import transformers
from transformers import AutoConfig, AutoProcessor

model_dir = Path(os.environ["MODEL_DIR"])
report_path = Path(os.environ["REPORT_FILE"])
report = {
    "stage": "17_setup_model_env",
    "python": platform.python_version(),
    "packages": {},
    "model_dir": str(model_dir),
    "model_config": None,
    "processor": None,
    "cuda": {"available": bool(torch.cuda.is_available()), "torch_cuda_build": torch.version.cuda},
}
import subprocess
try:
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.free", "--format=csv,noheader,nounits"],
        check=True, capture_output=True, text=True, timeout=15,
    )
    report["nvidia_smi"] = {"query_ok": True, "rows": [line.strip() for line in smi.stdout.splitlines() if line.strip()]}
except Exception as exc:
    report["nvidia_smi"] = {"query_ok": False, "error": f"{type(exc).__name__}: {exc}"}
for package in ("torch", "transformers", "accelerate", "Pillow"):
    try: report["packages"][package] = md.version(package)
    except md.PackageNotFoundError: report["packages"][package] = None

for name in ("AutoModelForMultimodalLM", "AutoModelForImageTextToText", "Qwen3_5ForConditionalGeneration"):
    try:
        getattr(transformers, name)
        report.setdefault("available_model_classes", []).append(name)
    except Exception as exc:
        report.setdefault("unavailable_model_classes", {})[name] = f"{type(exc).__name__}: {exc}"

try:
    config = AutoConfig.from_pretrained(model_dir, local_files_only=True)
    config_dict = config.to_dict()
    report["model_config"] = {
        "model_type": config_dict.get("model_type"),
        "architectures": config_dict.get("architectures"),
        "has_vision_config": isinstance(config_dict.get("vision_config"), dict),
        "vision_model_type": (config_dict.get("vision_config") or {}).get("model_type") if isinstance(config_dict.get("vision_config"), dict) else None,
        "transformers_version_in_config": config_dict.get("transformers_version"),
    }
except Exception as exc:
    report["model_config"] = {"loaded_local_only": False, "error": f"{type(exc).__name__}: {exc}"}
try:
    processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
    report["processor"] = {"class": type(processor).__name__, "loaded_local_only": True}
except Exception as exc:
    report["processor"] = {"loaded_local_only": False, "error": f"{type(exc).__name__}: {exc}"}
if report["cuda"]["available"]:
    report["cuda"]["device_count"] = torch.cuda.device_count()
    report["cuda"]["devices"] = []
    for index in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(index)
        free_bytes, total_bytes = torch.cuda.mem_get_info(index)
        report["cuda"]["devices"].append({
            "index": index,
            "name": props.name,
            "total_vram_bytes": int(total_bytes),
            "free_vram_bytes": int(free_bytes),
        })
else:
    report["cuda"]["device_count"] = 0

report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
print(f"REPORT_FILE={report_path}")
problems = []
if report["model_config"].get("model_type") != "qwen3_5" or not report["model_config"].get("has_vision_config"):
    problems.append(f"local model config is not expected Qwen3.5 multimodal: {report['model_config']}")
if not report.get("processor", {}).get("loaded_local_only"):
    problems.append("AutoProcessor could not load from local files")
if "Qwen3_5ForConditionalGeneration" not in report.get("available_model_classes", []):
    problems.append("Qwen3_5ForConditionalGeneration is unavailable in this Transformers installation")
if not report["cuda"]["available"]:
    problems.append("PyTorch cannot access a CUDA GPU")
if problems:
    raise RuntimeError("Environment verification failed: " + "; ".join(problems))
PY

note "Wrote reusable data-disk cache environment: $ACTIVATE_FILE"
note "Wrote local configuration/processor/GPU report: $REPORT_FILE"
note "No model weights were loaded, no inference was run, and no NVIDIA driver was changed."
