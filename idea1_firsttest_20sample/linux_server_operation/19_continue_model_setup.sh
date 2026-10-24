#!/usr/bin/env bash
# Safely resume the pinned model environment after confirming no installer is active.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
resolve_conda
note() { printf '[19_continue_model_setup] %s\n' "$*"; }

MODEL_DIR="$QWEN_MODEL_DIR"
ENV_PREFIX="$QWEN_ENV_PREFIX"
PIP_CACHE="${PIP_CACHE_DIR:-${DATA_ROOT%/}/pip_cache}"
TMPDIR="${TMPDIR:-${DATA_ROOT%/}/tmp}"
CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-${DATA_ROOT%/}/conda_pkgs}"
HF_HOME="${HF_HOME:-${DATA_ROOT%/}/hf_home}"
REPORT_DIR="${DATA_ROOT%/}/transfer_reports"
EVIDENCE_DIR="${DATA_ROOT%/}/model_setup_evidence"
WHEELHOUSE="${DATA_ROOT%/}/recovered_wheels"
mkdir -p -- "$PIP_CACHE" "$TMPDIR" "$CONDA_PKGS_DIRS" "$HF_HOME" "$REPORT_DIR" "$EVIDENCE_DIR" "$WHEELHOUSE"
export PIP_CACHE_DIR="$PIP_CACHE" TMPDIR TMP="$TMPDIR" TEMP="$TMPDIR" \
  CONDA_PKGS_DIRS HF_HOME HF_HUB_CACHE="${HF_HOME%/}/hub" PIP_DISABLE_PIP_VERSION_CHECK=1
command -v flock >/dev/null 2>&1 || die "flock is required to prevent concurrent step-19 runs; install the standard util-linux package first."
exec 9>"${DATA_ROOT%/}/.19_model_setup.lock"
flock -n 9 || die "Another step-19 run holds the data-root lock; no install was started."

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
report="$REPORT_DIR/${timestamp}_19_model_env_report.json"
proc_file="$EVIDENCE_DIR/${timestamp}_active_install_processes.txt"
helper="${PROJECT_DIR}/linux_server_operation/19_model_setup_report.py"
wheel_helper="${PROJECT_DIR}/linux_server_operation/19_recover_pip_wheels.py"
bundle_dir="$EVIDENCE_DIR/${timestamp}_19_bundle"
bundle="$EVIDENCE_DIR/${timestamp}_19_model_setup.tar.gz"
mkdir -p -- "$bundle_dir"

package_evidence() {
  local status="$1" detail="$2" runtime="$3"
  local -a report_args=(--status "$status" --env-prefix "$ENV_PREFIX" --model-dir "$MODEL_DIR" \
    --report "$report" --process-file "$proc_file" --detail "$detail")
  [[ "$runtime" == yes ]] && report_args+=(--runtime)
  THOR_DISABLE_GRAPHICS_ENV=1 run_python "$helper" "${report_args[@]}"
  cp -- "$report" "$bundle_dir/"
  cp -- "$_lso_log" "$bundle_dir/"
  tar -czf "$bundle" -C "$(dirname -- "$bundle_dir")" "$(basename -- "$bundle_dir")"
  note "Evidence bundle: $bundle"
  note "Environment report: $report"
}

note "DATA_ROOT=$DATA_ROOT; model directory=$MODEL_DIR; environment prefix=$ENV_PREFIX"
note "Read-only process scan first; active installs will never be interrupted or duplicated."
ps -eo pid=,args= > "$proc_file"
: > "${proc_file}.matched"
while IFS= read -r process_line; do
  read -r pid args <<< "$process_line"
  [[ -n "${pid:-}" && "$pid" != "$$" ]] || continue
  if [[ "$args" == *"17_setup_model_env.sh"* ]]; then
    printf '%s\n' "$process_line" >> "${proc_file}.matched"
    continue
  fi
  [[ "$args" == *"$ENV_PREFIX"* ]] || continue
  if [[ "$args" =~ (pip(3(\.[0-9]+)?)?[[:space:]]+(install|download)|-m[[:space:]]+pip[[:space:]]+(install|download)|-m[[:space:]]+ensurepip|conda[[:space:]]+(install|create)) ]]; then
    printf '%s\n' "$process_line" >> "${proc_file}.matched"
  fi
done < "$proc_file"
mv -- "${proc_file}.matched" "$proc_file"
if [[ -s "$proc_file" ]]; then
  note "PENDING: install/download process(es) already target this model environment; not probing imports or starting pip/conda."
  package_evidence pending_active_install "Existing targeted package process detected; wait for it to finish, then rerun this step." no
  exit 2
fi

free_kib="$(df -Pk -- "$DATA_ROOT" | awk 'NR == 2 { print $4 }')"
if [[ ! "$free_kib" =~ ^[0-9]+$ ]]; then
  package_evidence disk_probe_failed "Could not read available DATA_ROOT filesystem space." no
  die "Could not read free space on DATA_ROOT filesystem; see $bundle"
fi
if (( free_kib < 20 * 1024 * 1024 )); then
  package_evidence insufficient_space "Less than 20480 MiB free; no package installation started." no
  die "Only $((free_kib / 1024)) MiB free; require 20480 MiB before resuming; see $bundle"
fi

if [[ ! -x "$ENV_PREFIX/bin/python" ]]; then
  if [[ -e "$ENV_PREFIX" ]]; then
    package_evidence incomplete_prefix "Prefix exists without executable Python; preserved and not recreated." no
    die "Model environment prefix is incomplete; preserve it and review the report before deciding recovery: $report"
  fi
  note "No existing prefix. Creating the pinned Python 3.11/pip prefix (no model or NVIDIA driver changes)."
  if ! "$CONDA_EXE" create --yes --prefix "$ENV_PREFIX" python=3.11 pip; then
    package_evidence conda_prefix_creation_failed "Conda could not create the missing prefix." no
    die "Conda prefix creation failed; see $bundle"
  fi
fi
ENV_PYTHON="$ENV_PREFIX/bin/python"
EXPECTED='{"torch":"2.10.0+cu128","torchvision":"0.25.0+cu128","transformers":"5.15.0","accelerate":"1.11.0","Pillow":"11.3.0"}'
set +e
versions_json="$("$ENV_PYTHON" - "$EXPECTED" <<'PY'
import importlib.metadata as md, json, sys
expected=json.loads(sys.argv[1]); installed={}; conflicts={}
for name,want in expected.items():
    try: got=md.version(name)
    except md.PackageNotFoundError: got=None
    installed[name]=got
    if got is not None and got != want: conflicts[name]={'installed':got,'expected':want}
print(json.dumps({'installed':installed,'conflicts':conflicts}))
PY
)"
version_rc=$?
set -e
if (( version_rc != 0 )); then
  package_evidence runtime_metadata_probe_failed "Could not read installed package metadata." yes
  die "Could not inspect model environment; see $bundle"
fi
conflict_count="$("$ENV_PYTHON" -c 'import json,sys; print(len(json.loads(sys.argv[1])["conflicts"]))' "$versions_json")"
if [[ "$conflict_count" != 0 ]]; then
  package_evidence version_conflict "Pinned direct package versions conflict; no packages were changed." yes
  die "Conflicting installed versions; no upgrade/reinstall attempted. Review $report"
fi
installed_torch="$("$ENV_PYTHON" -c 'import json,sys; print(json.loads(sys.argv[1])["installed"].get("torch") or "")' "$versions_json")"
missing_torchvision="$("$ENV_PYTHON" -c 'import json,sys; x=json.loads(sys.argv[1])["installed"]; print("" if x.get("torchvision") else "torchvision")' "$versions_json")"
missing_regular="$("$ENV_PYTHON" -c 'import json,sys; x=json.loads(sys.argv[1])["installed"]; print(" ".join(k for k in ("transformers","accelerate","Pillow") if not x.get(k)))' "$versions_json")"
missing_math="$("$ENV_PYTHON" - <<'PY'
import importlib.metadata as md
def has(name):
    try: md.version(name); return True
    except md.PackageNotFoundError: return False
print(" ".join(name for name in ("mpmath", "sympy")
                 if not has(name)))
PY
)"

note "Recovering intact cached wheel bodies into a data-disk wheelhouse (source cache remains untouched)."
if ! run_python "$wheel_helper" "$PIP_CACHE" "$WHEELHOUSE"; then
  package_evidence wheel_recovery_conflict "Wheel recovery encountered a destination conflict or unrecoverable cache issue; no existing wheel was overwritten." yes
  die "Cached wheel recovery could not safely complete; inspect the bundled summary and resolve the wheelhouse conflict: $bundle"
fi

if [[ -n "$missing_math" ]]; then
  note "Installing only missing ordinary math dependencies from PyPI first: $missing_math"
  if ! "$ENV_PYTHON" -m pip install --cache-dir "$PIP_CACHE" --find-links "$WHEELHOUSE" --index-url https://pypi.org/simple $missing_math; then
    package_evidence pypi_dependency_install_failed "PyPI math dependency repair failed; no PyTorch index was used for this stage." yes
    die "PyPI dependency repair failed; see $bundle"
  fi
fi
if [[ -z "$installed_torch" ]]; then
  note "Installing only the pinned CUDA wheel from the official cu128 index, with --no-deps to preserve installed/cached CUDA libraries."
  if ! "$ENV_PYTHON" -m pip install --cache-dir "$PIP_CACHE" --find-links "$WHEELHOUSE" --index-url https://download.pytorch.org/whl/cu128 \
      --no-deps 'torch==2.10.0+cu128'; then
    package_evidence torch_wheel_install_failed "Official CUDA 12.8 torch wheel install failed; no CUDA dependency resolution/download was requested." yes
    die "PyTorch wheel installation failed; see $bundle"
  fi
fi

torch_requirements="${TMPDIR%/}/19_torch_missing_requirements_${timestamp}.txt"
if ! "$ENV_PYTHON" - "$torch_requirements" <<'PY'
import importlib.metadata as md, sys
try:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.markers import default_environment
except Exception as exc:
    raise SystemExit(f"Cannot parse torch dependency markers with the environment's pip: {exc}")
try:
    requirements = md.distribution("torch").requires or []
except md.PackageNotFoundError:
    raise SystemExit("Pinned torch distribution is not installed")
env = default_environment()
missing = []
for text in requirements:
    req = Requirement(text)
    if req.marker and not req.marker.evaluate(env):
        continue
    try:
        installed = md.version(req.name)
    except md.PackageNotFoundError:
        installed = None
    if installed is None or (req.specifier and not req.specifier.contains(installed, prereleases=True)):
        missing.append(str(req))
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    stream.write("\n".join(missing) + ("\n" if missing else ""))
print("Missing platform-applicable torch requirements:", len(missing))
for item in missing:
    print("  " + item)
PY
then
  package_evidence torch_requirement_inspection_failed "Could not parse platform-applicable torch dependencies." yes
  die "Could not inspect torch dependencies; see $bundle"
fi
if [[ -s "$torch_requirements" ]]; then
  note "Installing only missing/incompatible platform-applicable torch requirements, preferring recovered wheels and PyPI (not the PyTorch index)."
  if ! "$ENV_PYTHON" -m pip install --cache-dir "$PIP_CACHE" --find-links "$WHEELHOUSE" \
      --index-url https://pypi.org/simple -r "$torch_requirements"; then
    package_evidence torch_dependency_install_failed "One or more torch requirements could not be restored from wheel cache/PyPI." yes
    die "Torch dependency repair failed; see $bundle"
  fi
fi
if [[ -n "$missing_torchvision" ]]; then
  note "Installing only pinned torchvision from the recovered wheelhouse first; --no-deps preserves the already pinned torch and its CUDA libraries."
  if ! "$ENV_PYTHON" -m pip install --cache-dir "$PIP_CACHE" --no-index --find-links "$WHEELHOUSE" \
      --no-deps 'torchvision==0.25.0+cu128'; then
    note "No usable matching torchvision wheel was recovered; fetching that exact wheel from the official cu128 index."
    if ! "$ENV_PYTHON" -m pip install --cache-dir "$PIP_CACHE" --index-url https://download.pytorch.org/whl/cu128 \
        --no-deps 'torchvision==0.25.0+cu128'; then
      package_evidence torchvision_wheel_install_failed "Could not install the pinned torchvision CUDA 12.8 wheel from recovered cache or official cu128 index." yes
      die "Pinned torchvision installation failed; see $bundle"
    fi
  fi
fi
if [[ -n "$missing_regular" ]]; then
  note "Installing missing pinned application packages and ordinary dependencies from PyPI: $missing_regular"
  if ! "$ENV_PYTHON" -m pip install --cache-dir "$PIP_CACHE" --find-links "$WHEELHOUSE" --index-url https://pypi.org/simple \
      'transformers==5.15.0' 'accelerate==1.11.0' 'Pillow==11.3.0'; then
    package_evidence pypi_application_install_failed "PyPI application dependency install failed; no PyTorch index was involved." yes
    die "PyPI package installation failed; see $bundle"
  fi
fi

package_evidence runtime_probe_recorded "No targeted install process was active; missing pinned packages were repaired from their designated sources." yes
if "$ENV_PYTHON" -c 'import json,sys,pathlib; d=json.loads(pathlib.Path(sys.argv[1]).read_text()); r=d.get("runtime_probe",{}); packages=r.get("packages",{}); pins=d.get("expected_pins",{}); cfg=d.get("model_config") or {}; ok=(all(packages.get(k)==v for k,v in pins.items()) and r.get("cuda",{}).get("available") and r.get("classes",{}).get("Qwen3_5ForConditionalGeneration") is True and cfg.get("model_type")=="qwen3_5" and bool(cfg.get("vision_config")) and r.get("processor",{}).get("loaded_local_only") and r.get("pip_check",{}).get("returncode")==0); sys.exit(0 if ok else 1)' "$report"; then
  runtime_rc=0
else
  runtime_rc=$?
fi
final_status="environment_ready"
if [[ "$runtime_rc" != 0 ]]; then
  final_status="runtime_check_incomplete"
  note "Environment report was produced, but pinned package/CUDA/model-class/config checks are incomplete. No weights were loaded."
fi
post_install_free_kib="$(df -Pk -- "$DATA_ROOT" | awk 'NR == 2 { print $4 }')"
if [[ ! "$post_install_free_kib" =~ ^[0-9]+$ ]] || (( post_install_free_kib < 8 * 1024 * 1024 )); then
  final_status="low_disk_headroom"
  runtime_rc=1
  note "Remaining DATA_ROOT space is below 8192 MiB; no model inference was run."
fi
run_python -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p,encoding="utf-8")); d["status"]=sys.argv[2]; d["runtime_checks_passed"]=sys.argv[2]=="environment_ready"; open(p,"w",encoding="utf-8").write(json.dumps(d,ensure_ascii=False,indent=2)+chr(10))' "$report" "$final_status"
note "Final status: $final_status"
cp -- "$report" "$bundle_dir/"
cp -- "$_lso_log" "$bundle_dir/"
tar -czf "$bundle" -C "$(dirname -- "$bundle_dir")" "$(basename -- "$bundle_dir")"
note "Evidence bundle: $bundle"
note "Environment report: $report"
if [[ "$runtime_rc" != 0 ]]; then exit 1; fi
note "Pinned environment and CUDA probe passed. No weights loaded, no inference run, no driver change."
