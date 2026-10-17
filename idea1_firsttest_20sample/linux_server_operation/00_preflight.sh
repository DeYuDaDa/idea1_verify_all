#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings

report="${LOG_DIR%/}/machine_preflight_${_lso_timestamp}.txt"
{
  printf 'UTC time: '; date -u --iso-8601=seconds
  printf 'Hostname: '; hostname
  printf 'Kernel: '; uname -srmo
  printf 'OS: '; ( . /etc/os-release 2>/dev/null && printf '%s %s\n' "${PRETTY_NAME:-unknown}" "${VERSION_ID:-}" ) || true
  printf 'Project path: %s\n' "$PROJECT_DIR"
  printf 'Data path: %s\n' "$DATA_ROOT"
  printf '\nDisk space:\n'; df -h "$PROJECT_DIR" "$DATA_ROOT" 2>&1 || true
  printf '\nGPU summary:\n'; if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1 || true; else printf 'nvidia-smi not found\n'; fi
  printf '\nVulkan tools:\n'; if command -v vulkaninfo >/dev/null 2>&1; then vulkaninfo --summary 2>&1 | head -n 60 || true; else printf 'vulkaninfo not found\n'; fi
  printf '\nConda discovery:\n'; if [[ -n "$CONDA_EXE" ]]; then printf 'CONDA_EXE configured (path omitted from report)\n'; elif command -v conda >/dev/null 2>&1; then printf 'conda available on PATH\n'; else printf 'conda not found\n'; fi
  printf '\nRequired project files:\n'
  for f in requirements.txt specs.json runtime.py exporter.py validate.py generator.py probe.py package_offline.py; do
    if [[ -f "${PROJECT_DIR%/}/$f" ]]; then printf 'present %s\n' "$f"; else printf 'missing %s\n' "$f"; fi
  done
} > "$report"
cat "$report"
printf '\nPreflight report saved to: %s\n' "$report"
printf 'This report intentionally excludes environment variables and credential values.\n'
