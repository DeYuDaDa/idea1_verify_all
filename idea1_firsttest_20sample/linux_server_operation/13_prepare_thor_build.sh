#!/usr/bin/env bash
# Download/validate/cache the pinned CloudRendering build; never launches Unity.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
DATA_ROOT="$(realpath -m -- "$DATA_ROOT")"
print_settings
[[ "$(uname -s)" == Linux ]] || die "This stage is Linux-only."
resolve_conda
env_exists || die "Conda environment '$CONDA_ENV' is missing; run 01_setup_env.sh first."

task_archive_arg=""
task_sha_arg=""
task_check_only=false
while (($#)); do
  case "$1" in
    --archive) (($# >= 2)) || die "--archive requires a ZIP path"; task_archive_arg="$2"; shift 2 ;;
    --sha256-file) (($# >= 2)) || die "--sha256-file requires an official SHA-256 sidecar path"; task_sha_arg="$2"; shift 2 ;;
    --check-cache) task_check_only=true; shift ;;
    *) die "Usage: bash linux_server_operation/13_prepare_thor_build.sh [--check-cache | --archive ZIP --sha256-file SHA256]" ;;
  esac
done
if [[ ( -n "$task_archive_arg" && -z "$task_sha_arg" ) || ( -z "$task_archive_arg" && -n "$task_sha_arg" ) ]]; then
  die "For offline import, provide both --archive ZIP and --sha256-file official-sidecar."
fi
if [[ "$task_check_only" == true && ( -n "$task_archive_arg" || -n "$task_sha_arg" ) ]]; then
  die "--check-cache cannot be combined with archive arguments."
fi

task_helper="${PROJECT_DIR%/}/linux_server_operation/13_thor_build.py"
require_file "$task_helper"
export PROJECT_DIR DATA_ROOT CONDA_EXE CONDA_ENV THOR_PLATFORM
if [[ "$THOR_PLATFORM" != CloudRendering ]]; then
  die "This stage prepares only the pinned CloudRendering build; THOR_PLATFORM='$THOR_PLATFORM'."
fi

if [[ "$task_check_only" == true ]]; then
  set +e
  run_python "$task_helper" --check-cache --data-root "$DATA_ROOT"
  task_check_status=$?
  set -e
  (( task_check_status == 0 )) || die "Pinned CloudRendering build is not ready in DATA_ROOT/unity_cache."
  exit 0
fi

task_build="thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917"
task_url="https://s3-us-west-2.amazonaws.com/ai2-thor-public/builds/${task_build}.zip"
task_sha_url="${task_url%.zip}.sha256"
task_stage="${DATA_ROOT%/}/thor_build_prepare/${_lso_timestamp}"
mkdir -p -- "${task_stage%/*}"
task_stage="$(mktemp -d -- "${task_stage}_XXXXXX")"
printf 'Evidence/staging directory: %s\n' "$task_stage"

set +e
run_python "$task_helper" --check-cache --data-root "$DATA_ROOT"
task_cache_status=$?
set -e
if (( task_cache_status == 0 )); then
  printf 'Pinned build cache is already structurally valid; no download or Unity launch needed.\n'
  exit 0
fi
task_cache_path="${DATA_ROOT%/}/unity_cache/releases/${task_build}"
if [[ -e "$task_cache_path" ]]; then
  die "Cache path exists but is incomplete; it is preserved. Inspect it before choosing a new DATA_ROOT: $task_cache_path"
fi

if [[ -n "$task_archive_arg" ]]; then
  task_archive="$(realpath -e -- "$task_archive_arg")"
  task_sha_file="$(realpath -e -- "$task_sha_arg")"
  printf 'Using supplied ZIP and SHA-256 sidecar; no build download will be attempted.\n'
else
  command -v curl >/dev/null 2>&1 || die "curl is required for the bounded official download."
  command -v timeout >/dev/null 2>&1 || die "GNU timeout is required to enforce the 5-minute overall download deadline."
  task_download_dir="${DATA_ROOT%/}/thor_build_downloads"
  mkdir -p -- "$task_download_dir"
  task_part="$task_download_dir/${task_build}.zip.part"
  task_archive="$task_download_dir/${task_build}.zip"
  task_sha_file="$task_download_dir/${task_build}.sha256"
  task_sha_candidate="$task_sha_file"
  task_phase_start="$(date +%s)"
  if [[ ! -s "$task_sha_file" ]]; then
    task_sha_candidate="${task_sha_file}.download"
    printf 'Fetching official SHA-256 sidecar from %s\n' "$task_sha_url"
    set +e
    timeout --foreground 30s curl --fail --silent --show-error --location --connect-timeout 15 --max-time 30 "$task_sha_url" --output "$task_sha_candidate"
    task_sha_download_status=$?
    set -e
    if (( task_sha_download_status != 0 )); then die "Could not fetch official SHA-256 sidecar (exit $task_sha_download_status). Use browser-fetched .zip plus its matching .sha256 file."; fi
  fi
  if ! run_python "$task_helper" --check-sha --sha256-file "$task_sha_candidate" --data-root "$DATA_ROOT" > "$task_stage/sidecar_check.json" 2>&1; then
    cat "$task_stage/sidecar_check.json"
    die "SHA-256 sidecar is invalid; no ZIP download was started. Preserve the evidence and supply the official sidecar."
  fi
  if [[ "$task_sha_candidate" != "$task_sha_file" ]]; then mv -- "$task_sha_candidate" "$task_sha_file"; fi
  if [[ -f "$task_archive" ]]; then
    printf 'Reusing existing complete ZIP candidate for size/hash verification: %s\n' "$task_archive"
  else
    task_existing_size=0
    [[ -f "$task_part" ]] && task_existing_size="$(stat -c %s -- "$task_part")"
    if (( task_existing_size == 835983275 )); then
      mv -- "$task_part" "$task_archive"
      printf 'Promoted full-size resumed download to ZIP candidate for cryptographic verification.\n'
    else
      printf 'Downloading pinned build; ZIP transfer has a 300-second overall deadline. A stopped .part is preserved at %s.\n' "$task_part"
      set +e
      timeout --foreground 300s curl --fail --location --show-error --progress-bar \
        --connect-timeout 15 --max-time 300 --speed-limit 5120 --speed-time 30 \
        -C - "$task_url" --output "$task_part"
      task_download_status=$?
      set -e
      printf 'Download phase elapsed: %s seconds\n' "$(( $(date +%s) - task_phase_start ))"
      if (( task_download_status != 0 )); then
        die "Official download stopped (exit $task_download_status). Keep the .part file; rerun to resume with HTTP Range, or provide browser-downloaded ZIP and sidecar."
      fi
      task_actual_size="$(stat -c %s -- "$task_part")"
      if (( task_actual_size != 835983275 )); then
        die "Download size is $task_actual_size bytes; expected 835983275. Keeping partial/untrusted file at $task_part."
      fi
      mv -- "$task_part" "$task_archive"
    fi
  fi
fi

task_phase_start="$(date +%s)"
set +e
run_python "$task_helper" --install --archive "$task_archive" --sha256-file "$task_sha_file" --data-root "$DATA_ROOT" --stage-dir "$task_stage"
task_install_status=$?
set -e
printf 'Verify/extract/install phase elapsed: %s seconds\n' "$(( $(date +%s) - task_phase_start ))"
(( task_install_status == 0 )) || die "Pinned build preparation failed. Retain the stage directory and log for diagnosis: $task_stage"
printf 'Build cache is ready. Stage output: %s\n' "$task_stage"
printf 'Next: run bash linux_server_operation/03_smoke.sh FloorPlan1 explicitly when ready; this script did not start Unity.\n'
