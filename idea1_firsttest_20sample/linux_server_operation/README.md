# Linux server operation

These scripts are for the Linux machine only. Run them from the repository checkout or another working directory; each script locates the project from its own location. Do not run these stages on the Windows authoring machine.

The matching server paths are:

- Project: `/root/idea1_verify_all/idea1_firsttest_20sample`
- New data, logs, reports, caches and model environment: `/root/autodl-tmp/idea1_firsttest_20sample`
- Export root: `/root/autodl-tmp/idea1_firsttest_20sample/exports`
- Legacy data (preserved): `/root/will_not_be_push_to_git/idea1_firsttest_20sample`
- Local model: `/root/autodl-tmp/model/qwen3.5-4b`

The scripts accept `PROJECT_DIR`, `DATA_ROOT`, `CONDA_EXE`, `CONDA_ENV`, and `THOR_PLATFORM` overrides. For example:

```bash
PROJECT_DIR=/root/idea1_verify_all/idea1_firsttest_20sample \
DATA_ROOT=/root/autodl-tmp/idea1_firsttest_20sample \
CONDA_ENV=thor20 THOR_PLATFORM=CloudRendering \
bash /root/idea1_verify_all/idea1_firsttest_20sample/linux_server_operation/00_preflight.sh
```

Run each file with `bash path/to/stage.sh`; executable-bit changes are not needed. Scripts use strict Bash error handling and record console output in timestamped files under `$DATA_ROOT/logs`. `00_preflight.sh` also writes a compact machine report there. The report intentionally excludes environment-variable values and credentials.

## Stages

1. `00_preflight.sh` checks paths, disk availability, GPU/Vulkan tool visibility, Conda discovery, and expected project files. It does not install or modify anything.
2. `01_setup_env.sh` discovers Conda on PATH or at common installation paths, or uses `CONDA_EXE`. If `CONDA_ENV` exists, it leaves the environment itself intact, checks Python 3.10, and installs/reconciles the pinned `requirements.txt` inside that environment. Otherwise, it creates the dedicated environment with Python 3.10 and installs the pinned requirements. If Conda is missing, it stops with setup guidance; it never installs Conda or downloads simulator assets.
3. `02_unit_checks.sh` compiles the project and runs unittest discovery in `tests/`. Run after tests have been added and the environment is set up.
4. `03_smoke.sh [SCENE]` first checks the pinned CloudRendering cache locally and stops with stage 13 guidance if absent. It then runs the simulator probe. The scene defaults to `FloorPlan1`; output goes to `$DATA_ROOT/smoke` (the probe adds this subdirectory). Large build downloading is kept separate from this startup stage.
5. `04_generate_pilot.sh` generates only `C13,T16,M01,S05,B19,P20` into `$DATA_ROOT/exports` using `THOR_PLATFORM` (default `CloudRendering`).
6. `05_generate_all.sh` is the explicit full generation stage. It passes `--resume` and writes under the same export root. No other stage starts a full generation run.
7. `04b_inspect_pilot.sh` prints the six-pair diagnostic report without approving it. `06_validate.sh [EXPORT_ROOT] [PAIRS]` runs strict validation; the optional path defaults to `$DATA_ROOT/exports`, and an optional comma-separated PAIRS limits validation to a reviewed subset. The validator's nonzero status is preserved.
8. `06a_prepare_review.sh` creates a review form; `06b_apply_review.sh FORM REVIEWER` records a completed review. `07_package_offline.sh [EXPORT_ROOT] [OUTPUT_FILE] [PAIRS]` packages only public input data, optionally for a reviewed subset. Defaults are the export root and `$DATA_ROOT/offline_public_input.zip`.
9. `09_fix_vulkan.sh` installs only `libvulkan1` and `vulkan-tools`, then checks actual NVIDIA enumeration. Its `--check-only` mode does not install packages. On the current server this and the stage 12 EGL repair have already succeeded; the remaining blocker is build downloading, covered by stage 13.
10. `10_diagnose_nvidia_icd.sh` collects library, ICD and isolated loader probes. It writes diagnostic files outside Git; it does not install packages, rewrite system driver configuration or start Unity.
11. `11_trace_vulkan_init.sh` follows initialization-time library and device access after stage 10 has ruled out the basic path and gpucomp hypotheses. See `11_vulkan_init_trace.md` for the next command and optional strace installation. It does not install NVIDIA drivers or launch Unity.
12. `12_fix_egl.sh` addresses the missing `libEGL.so.1` confirmed by stage 11. It requests Ubuntu `libegl1` and required dependencies, verifies actual NVIDIA Vulkan enumeration, and optionally runs the existing smoke probe. See `12_egl_repair.md` for the current server command and evidence paths.
13. `13_prepare_thor_build.sh` prepares the CloudRendering build separately from simulator startup. See `13_thor_build.md` for bounded, resumable downloading or importing a manually uploaded ZIP. Only after local cache preparation should stage 03 run.
14. `14_collect_pilot_evidence.sh` packages existing candidate frames/states, original pilot logs and representative failed attempts for diagnosis. It does not start the simulator or approve review forms. Its bundle contains private scoring data for human/code review and must not be used as model input; see `14_pilot_diagnosis.md`.

Current server continuation: see `18_current_next_steps.md`. Stage 15 copies selected legacy evidence/cache to the new data disk. Stage 16 checks camera framing in three scenes. Stage 17 prepares a separate model environment. Existing candidate generation receipts are not visual approval; do not run full generation until the camera probe is reviewed.

See `08_after_smoke.md` for the pilot inspection/review/package sequence and the full-generation command. Older stage notes retain historical output paths; `common.sh` now defaults to the data disk. Use an explicit `DATA_ROOT` only when intentionally inspecting old output.

For first-run commands, use `00_start_here.md`. Recommended order: preflight, environment setup, reviewed unit checks, graphics readiness and stage 13 build preparation, smoke, pilot, inspect and validate the pilot, then decide whether to run the full generation stage. Validate again before packaging. A pilot is intentionally separate from the full run.

If a stage fails, its command output remains in that stage's log. Resolve the reported prerequisite or simulator error and rerun the relevant stage. Stage 09 may invoke `apt` for the two stated Vulkan packages; stage 11 may install `strace` when explicitly requested; stage 12 requests `libegl1` and its required dependencies, which can include Mesa EGL. These use root or noninteractive `sudo`. No stage installs NVIDIA kernel drivers or evaluates shell code from environment values.
