#!/usr/bin/env bash
# Install a pinned Miniforge release under the current user's HOME. No sudo/root.
set -Eeuo pipefail

task_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "${task_script_dir}/server_paths.sh" ]]; then
  # shellcheck source=/dev/null
  source "${task_script_dir}/server_paths.sh"
fi
task_data_root="${DATA_ROOT:-${HOME}/experiment_data/idea1_firsttest_20sample}"
task_prefix="${HOME}/miniforge3"
task_version="26.7.2-1"
task_asset="Miniforge3-${task_version}-Linux-x86_64.sh"
task_release="https://github.com/conda-forge/miniforge/releases/download/${task_version}"
task_installer_url="${task_release}/${task_asset}"
task_sha_url="${task_installer_url}.sha256"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Linux ]] || die 'Run this bootstrap on Linux.'
[[ "$(uname -m)" == x86_64 ]] || die 'This pinned CloudRendering setup supports Linux x86_64 only.'
[[ -n "${HOME:-}" && -d "$HOME" && -w "$HOME" ]] || die 'HOME must be an existing writable user directory.'
[[ ! -e "$task_prefix" ]] || die "Refusing to overwrite existing path: $task_prefix. Inspect and choose/reuse it manually."
command -v curl >/dev/null 2>&1 || die 'curl is required; ask the server administrator to provide it if unavailable.'
command -v sha256sum >/dev/null 2>&1 || die 'sha256sum is required.'
command -v timeout >/dev/null 2>&1 || die 'GNU timeout is required.'
task_repo_root="$(realpath -m -- "${task_script_dir}/../..")"
task_data_absolute="$(realpath -m -- "$task_data_root")"
case "${task_data_absolute%/}/" in "${task_repo_root%/}/"*) die "DATA_ROOT must be outside idea1_verify_all: $task_data_root" ;; esac
mkdir -p -- "${task_data_root%/}/logs"
task_log="${task_data_root%/}/logs/$(date -u +%Y%m%dT%H%M%SZ)_32_install_user_conda.log"
exec > >(tee -a "$task_log") 2>&1

task_download_dir="${task_data_root%/}/installers/miniforge-${task_version}"
mkdir -p -- "$task_download_dir"
task_installer="${task_download_dir}/${task_asset}"
task_sidecar="${task_download_dir}/${task_asset}.sha256"
task_part="${task_installer}.part"
printf 'Miniforge release: %s\nInstall prefix: %s\nDownload cache: %s\n' "$task_version" "$task_prefix" "$task_download_dir"
printf 'Installer download has a 5-minute per-attempt bound; a partial file can resume on retry.\nLog: %s\n' "$task_log"

if [[ ! -s "$task_sidecar" ]]; then
  timeout --foreground 60s curl --fail --silent --show-error --location --connect-timeout 15 --max-time 60 "$task_sha_url" --output "${task_sidecar}.part" || die 'Could not fetch the official SHA-256 sidecar; preserve partial files and retry later.'
  mv -- "${task_sidecar}.part" "$task_sidecar"
fi
if [[ ! -s "$task_installer" ]]; then
  timeout --foreground 300s curl --fail --silent --show-error --location --connect-timeout 20 --max-time 300 -C - "$task_installer_url" --output "$task_part" || die 'Installer download did not finish within 5 minutes. Partial file is preserved; retry the bootstrap or provide a verified installer and sidecar.'
  mv -- "$task_part" "$task_installer"
fi
task_expected="$(awk 'NR==1 {print $1}' "$task_sidecar")"
[[ "$task_expected" =~ ^[[:xdigit:]]{64}$ ]] || die 'Official sidecar does not contain a SHA-256 digest.'
printf '%s  %s\n' "$task_expected" "$task_installer" | sha256sum --check --status || die 'Installer SHA-256 mismatch. Installer is preserved for inspection; do not run it.'
printf 'Official installer SHA-256 verified: %s\n' "$task_expected"

task_log="${task_download_dir}/install_${task_version}_$(date -u +%Y%m%dT%H%M%SZ).log"
if ! bash "$task_installer" -b -p "$task_prefix" >"$task_log" 2>&1; then
  printf 'Installer failed. Log: %s\n' "$task_log" >&2
  exit 1
fi
[[ -x "${task_prefix}/bin/conda" ]] || die 'Installer returned success but conda is missing at the expected prefix.'
"${task_prefix}/bin/conda" --version
printf 'User-space Miniforge installation completed. No shell startup file was modified.\nInstaller log: %s\n' "$task_log"
printf 'Set CONDA_EXE=%q for the project commands.\n' "${task_prefix}/bin/conda"
