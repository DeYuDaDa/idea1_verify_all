#!/usr/bin/env bash
# Raw native observations only; stage 30 and model inference are not prerequisites.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
[[ "$(uname -s)" == Linux ]] || die "Linux server only."
resolve_conda
env_exists || die "Existing THOR environment '${THOR_ENV_PREFIX:-$CONDA_ENV}' is missing; load the migrated server.env and complete stage 32 deployment first. No install was attempted."
command -v flock >/dev/null 2>&1 || die "flock is required to avoid overlapping Unity generation."
mkdir -p -- "$DATA_ROOT"
exec 9>"${DATA_ROOT%/}/generation.lock"
flock -n 9 || die "Another simulator generation/probe is running."
cd -- "$PROJECT_DIR"
export DATA_ROOT
probe_selection=("$@")
while (($#)); do
  case "$1" in
    --facts|--cases|--scenes|--max-scenes|--sample-steps|--seed|--view-mode|--suite)
      (($# >= 2)) || die "$1 requires a value."
      shift 2 ;;
    *) die "Allowed options: --facts, --cases, --scenes, --max-scenes, --sample-steps, --seed, --view-mode, --suite (each with a value)." ;;
  esac
done

# Only new mechanism contract tests. No stage-30 pipeline or model env is used.
run_python -m compileall -q mechanism_probe.py mechanism_probe_common.py mechanism_probes_thermal_liquid.py mechanism_probes_relations.py view_planning.py observation_views.py nested_setup.py mechanism_rechecks.py
for pattern in 'test_mechanism*.py' 'test_view_planning.py' 'test_observation_views.py' 'test_nested_setup.py'; do
  if run_python -m unittest discover -s tests -p "$pattern" -v; then
    :
  else
    die "Mechanism preflight tests failed: $pattern. Unity has not started, no new mechanism data exists, and no mechanism ZIP was generated. Preserve this stage log."
  fi
done
run_python "${PROJECT_DIR%/}/mechanism_probe.py" --list "${probe_selection[@]}"
run_python "${PROJECT_DIR%/}/linux_server_operation/13_thor_build.py" --check-cache --data-root "$DATA_ROOT"

probe_out="$(mktemp -d -- "${DATA_ROOT%/}/mechanism_probe_${_lso_timestamp}_XXXXXX")"
probe_args=(--out "$probe_out" --platform "$THOR_PLATFORM" --build-cache-dir "${DATA_ROOT%/}/unity_cache")
if [[ -n "${THOR_LOCAL_EXECUTABLE_PATH:-}" ]]; then
  probe_args+=(--local-executable-path "$THOR_LOCAL_EXECUTABLE_PATH")
fi
probe_status=0
if run_python "${PROJECT_DIR%/}/mechanism_probe.py" "${probe_args[@]}" "${probe_selection[@]}"; then
  :
else
  probe_status=$?
fi

archive="${LOG_DIR%/}/${_lso_timestamp}_$(basename -- "$probe_out")_31_mechanisms.zip"
if run_python - "$archive" "$probe_out" "$PROJECT_DIR" "$_lso_log" <<'PY'
import sys
import zipfile
from pathlib import Path

archive_path, probe_root, project, log = map(Path, sys.argv[1:])
names = ("mechanism_probe.py", "mechanism_probe_common.py", "mechanism_probes_thermal_liquid.py",
         "mechanism_probes_relations.py", "runtime.py", "interactions.py", "frame_evidence.py",
         "hard_group_plan.json", "困难组设计与机制依赖.md", "config.json",
         "view_planning.py", "observation_views.py", "nested_setup.py", "mechanism_rechecks.py",
         "tests/test_view_planning.py", "tests/test_observation_views.py", "tests/test_nested_setup.py",
         "tests/test_mechanism_common.py", "tests/test_mechanism_registry.py", "tests/test_mechanism_rechecks.py",
         "linux_server_operation/31_probe_native_mechanisms.sh", "linux_server_operation/41_recheck_r1_r2.sh")
with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(probe_root.rglob("*")):
        if path.is_file():
            bundle.write(path, "observations/" + path.relative_to(probe_root).as_posix())
    for name in names:
        path = project / name
        if path.is_file():
            bundle.write(path, "source/" + name)
    if log.is_file():
        bundle.write(log, "logs/" + log.name)
print("Private mechanism bundle:", archive_path)
PY
then
  :
else
  printf 'ERROR: Could not package evidence; preserve raw directory %s\n' "$probe_out" >&2
  (( probe_status != 0 )) || probe_status=1
fi
printf '\nProbe root: %s\nBundle: %s\nExecution status: %s\n' "$probe_out" "$archive" "$probe_status"
printf 'Setup-unavailable and inconclusive results are expected observations, not benchmark failures. Review exact conditions, trajectories and visual evidence before accepting any mechanism or hard group.\n'
exit "$probe_status"
