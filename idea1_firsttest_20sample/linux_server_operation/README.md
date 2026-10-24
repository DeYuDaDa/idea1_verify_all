# Linux server operation

Research task after deployment (2026-10-22): skip stage 30 and follow [31_机制探测与困难组.md](31_机制探测与困难组.md). Stage 31 runs private native mechanism probes in the existing simulator environment; it does not load a model or generate approved hard-group data. The conditional designs are in `../hard_group_plan.json` and `../困难组设计与机制依赖.md`.

Earlier evidence-quality workflow: [30_工作流核验与下一步.md](30_工作流核验与下一步.md). Stages 28/29 prepare and check per-question evidence review; they do not generate scenes or repair camera views. These are not prerequisites for stage 31. Formal model inference retains its existing review checks.

These scripts are for the Linux machine only. Run them from the repository checkout or another working directory; each script locates the project from its own location. Do not run these stages on the Windows authoring machine.

## Deployment moved on 2026-10-23

The current target is an ordinary Linux server, non-root user, home `/home/mdy`, with no Conda installed. Start with [32_user_server_migration.md](32_user_server_migration.md). Stages 32/33 provide user-space bootstrap and graphics checks. Do not replay the old privileged AutoDL graphics repairs as a clean-deployment sequence.

| Setting | Ordinary Linux (`home`) | Previous AutoDL (`autodl`) |
|---|---|---|
| Checkout | `$HOME/idea1_verify_all/idea1_firsttest_20sample` | same home-relative location |
| DATA_ROOT | `$HOME/experiment_data/idea1_firsttest_20sample` | `$HOME/autodl-tmp/idea1_firsttest_20sample` |
| QWEN_MODEL_DIR | `$HOME/model/qwen3.5-4b` | `$HOME/autodl-tmp/model/qwen3.5-4b` |
| Legacy evidence | `$HOME/will_not_be_push_to_git/idea1_firsttest_20sample` | same home-relative location |

`server_paths.sh` selects `THOR_SERVER_PROFILE=auto|home|autodl`; explicit environment overrides win. Scripts discover PROJECT_DIR from their own checkout. New data and environments stay outside Git. The machine-specific settings and full command order are in the migration guide; load that profile in each new shell. No script changes HOME to impersonate another machine.

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
9. `09_fix_vulkan.sh` installs only `libvulkan1` and `vulkan-tools`, then checks actual NVIDIA enumeration. Its `--check-only` mode does not install packages. These repairs succeeded on the previous AutoDL host. They do not establish graphics readiness on the new host. New non-root deployments use stage 33 instead.
10. `10_diagnose_nvidia_icd.sh` collects library, ICD and isolated loader probes. It writes diagnostic files outside Git; it does not install packages, rewrite system driver configuration or start Unity.
11. `11_trace_vulkan_init.sh` follows initialization-time library and device access after stage 10 has ruled out the basic path and gpucomp hypotheses. See `11_vulkan_init_trace.md` for the next command and optional strace installation. It does not install NVIDIA drivers or launch Unity.
12. `12_fix_egl.sh` addresses the missing `libEGL.so.1` confirmed by stage 11. It requests Ubuntu `libegl1` and required dependencies, verifies actual NVIDIA Vulkan enumeration, and optionally runs the existing smoke probe. See `12_egl_repair.md` for the current server command and evidence paths.
13. `13_prepare_thor_build.sh` prepares the CloudRendering build separately from simulator startup. See `13_thor_build.md` for bounded, resumable downloading or importing a manually uploaded ZIP. Only after local cache preparation should stage 03 run.
14. `14_collect_pilot_evidence.sh` packages existing candidate frames/states, original pilot logs and representative failed attempts for diagnosis. It does not start the simulator or approve review forms. Its bundle contains private scoring data for human/code review and must not be used as model input; see `14_pilot_diagnosis.md`.

Historical 2026-10-18 continuation is preserved in stages 25–27. The prior model run and single-question recheck completed; do not follow obsolete missing-torchvision status notes as a description of the new host. New deployments start with 32, then continue the selected experiment workflow.

See `08_after_smoke.md` for the pilot inspection/review/package sequence and the full-generation command. Older stage notes retain historical output paths; current paths come from `server_paths.sh`. Use an explicit `DATA_ROOT` only when intentionally inspecting old output.

For new-host installation commands, use `32_user_server_migration.md`. `00_start_here.md` is the old AutoDL first-run record. Recommended order: preflight, environment setup, reviewed unit checks, graphics readiness and stage 13 build preparation, smoke, pilot, inspect and validate the pilot, then decide whether to run the full generation stage. Validate again before packaging. A pilot is intentionally separate from the full run.

If a stage fails, its command output remains in that stage's log. Resolve the reported prerequisite or simulator error and rerun the relevant stage. Stage 09 may invoke `apt` for the two stated Vulkan packages; stage 11 may install `strace` when explicitly requested; stage 12 requests `libegl1` and its required dependencies, which can include Mesa EGL. These use root or noninteractive `sudo`. No stage installs NVIDIA kernel drivers or evaluates shell code from environment values.
