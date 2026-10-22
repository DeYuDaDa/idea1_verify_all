#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Run 01_setup_env.sh first."
cd -- "$PROJECT_DIR"

[[ $# -eq 2 && "$1" == "--export-root" ]] || die "Usage: bash linux_server_operation/28_prepare_evidence_review.sh --export-root /absolute/path/to/exports"
export_root="$(realpath -e -- "$2")"
[[ -d "$export_root" ]] || die "Export root is not a directory: $export_root"

run_python -m unittest discover -s "${PROJECT_DIR%/}/tests" -p 'test_evidence_workflow.py' || die "Evidence workflow unit checks failed; no review packet was prepared."

mkdir -p -- "${DATA_ROOT%/}/evidence_reviews" "$LOG_DIR"
export_name="$(basename -- "${export_root%/}")"
review_dir="${DATA_ROOT%/}/evidence_reviews/${export_name}_${_lso_timestamp}_$$"
[[ ! -e "$review_dir" ]] || die "Review packet path already exists: $review_dir"
run_python "${PROJECT_DIR%/}/evidence_workflow.py" prepare --export-root "$export_root" --output-dir "$review_dir"
archive="${LOG_DIR%/}/$(basename -- "$review_dir").zip"
[[ ! -e "$archive" ]] || die "Review archive already exists: $archive"
run_python -c 'import shutil,sys; shutil.make_archive(sys.argv[1][:-4], "zip", sys.argv[2])' "$archive" "$review_dir"
printf '\nPrivate review directory: %s\nDownloadable review packet: %s\nThe packet contains public inputs and RGB previews only; send it to a human reviewer.\n' "$review_dir" "$archive"
