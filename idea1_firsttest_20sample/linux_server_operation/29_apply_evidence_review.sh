#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
print_settings
resolve_conda
env_exists || die "Run 01_setup_env.sh first."

[[ $# -eq 4 && "$1" == "--export-root" && "$3" == "--form" ]] || die "Usage: bash linux_server_operation/29_apply_evidence_review.sh --export-root /absolute/path/to/exports --form /absolute/path/review_form.json"
export_root="$(realpath -e -- "$2")"
form="$(realpath -e -- "$4")"
[[ -d "$export_root" ]] || die "Export root is not a directory: $export_root"
[[ -f "$form" ]] || die "Review form is not a file: $form"

run_python "${PROJECT_DIR%/}/evidence_workflow.py" check --export-root "$export_root" --form "$form" || die "Evidence review did not pass; formal approval was not recorded."
destination="${export_root%/}/evidence_review.json"
[[ ! -L "$destination" ]] || die "Refusing a symbolic-link review destination: $destination"
if [[ -e "$destination" ]]; then
  if cmp -s -- "$form" "$destination"; then
    printf 'The same approved form is already recorded at %s\n' "$destination"
  else
    die "Refusing to overwrite a different evidence review: $destination"
  fi
else
  # noclobber also refuses a file created after the existence check.
  ( set -o noclobber; cat -- "$form" > "$destination" ) || die "Could not create review without overwriting an existing path."
  cmp -s -- "$form" "$destination" || die "Recorded review differs from checked form."
  printf 'Approved evidence review recorded: %s\n' "$destination"
fi
printf 'Evidence approval does not replace the legacy three-check review.py approval or strict 06_validate.sh gate. Continue with those original review steps before formal evaluation.\n'
