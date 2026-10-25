# Development contract

- This Windows checkout is for editing and Git file management only. Do not run project Python, tests, simulators, WSL, dependency installation or environment setup here.
- Current deployment (2026-10-23): ordinary Linux host, non-root user, home `/home/mdy`; this host has no preinstalled Conda. Previous AutoDL deployment used `/root`. Do not assume the old GPU, RAM, driver version, root permissions, or container library layout on the new host.
- Project path is derived from the checkout. Typical locations: `/home/mdy/idea1_verify_all/idea1_firsttest_20sample` (new host) and `/root/idea1_verify_all/idea1_firsttest_20sample` (AutoDL). Never change HOME to emulate the previous machine.
- Put every requested Linux execution command in `idea1_firsttest_20sample/linux_server_operation/`, with execution order and expected result documented there.
- Use `linux_server_operation/server_paths.sh` for deployment defaults. `THOR_SERVER_PROFILE=home` uses `$HOME/experiment_data/idea1_firsttest_20sample` and `$HOME/model/qwen3.5-4b`; `autodl` uses `$HOME/autodl-tmp/idea1_firsttest_20sample` and `$HOME/autodl-tmp/model/qwen3.5-4b`. `auto` selects AutoDL only when its data directory is present and writable. Explicit `DATA_ROOT`, `QWEN_MODEL_DIR`, `QWEN_ENV_PREFIX`, `THOR_ENV_PREFIX`, `CONDA_EXE`, and `SERVER_HOME` overrides take precedence.
- New generated datasets, machine reports, execution logs, model environments and caches must stay outside Git under DATA_ROOT. Preserve old evidence under `$HOME/will_not_be_push_to_git/idea1_firsttest_20sample` or the explicitly configured OLD_DATA_ROOT; stage 15 is an optional legacy-artifact copy, not a prerequisite for a clean migration. The Windows non-Git directory remains `F:/md/Academic/ICML2026 paper/主线1/will_not_be_push_to_git`.
- The authoritative clean-deployment sequence is `idea1_firsttest_20sample/linux_server_operation/32_user_server_migration.md`. Recreate Python environments at their new paths; transfer the verified Unity ZIP + matching SHA-256 sidecar, model directory, and needed experiment artifacts. Do not copy relocated Conda environments or vendor driver libraries from AutoDL.
- On the new host, use user-space installation/check stages 32/33. Do not invoke historical privileged repair stages 09, 11 --install-strace, or 12 as part of migration. A working host NVIDIA graphics driver and device permission must be provided by the administrator; no project script may install a kernel driver, rewrite system ICD files, or infer Vulkan readiness from CUDA/nvidia-smi alone.
- New clean deployments explicitly set THOR_ENV_PREFIX to `$DATA_ROOT/thor_env`; legacy AutoDL can leave it unset to reuse the named CONDA_ENV=thor20. Setup and every execution stage must target the same environment. Python bytecode defaults to `$DATA_ROOT/pycache`.
- Keep graphics-library path adjustments scoped to THOR child processes; do not globally export LD_LIBRARY_PATH into the separate model environment. Never report the new server ready merely because AutoDL worked before; require this host's graphics check and actual Unity smoke evidence.
- Never report code as tested, data as generated, or design hypotheses as simulator ground truth without server execution evidence.
- Keep model-visible input and hidden scoring metadata physically separate. Derive labels from actual before/after metadata and audit event success, capability applicability, knowledge conditions and paired controls.
- The design contains 20 A/B pairs, 40 scene records. Unsupported mechanisms or failed construction attempts must remain explicit failures, not fabricated samples.

## Advisory notes for scene planning and capture (not mandatory gates)

These are suggestions learned from earlier attempts, not additional mandatory
requirements or approval steps. The 20-pair count above describes the original
pilot; new mechanism probes and conditional hard-group plans are separate work.
Stage 30 is not a prerequisite for the mechanism investigation requested on
2026-10-22. Preserve the existing evidence and label raw probes as private,
unreviewed simulator observations.

### Helpful checks while designing and programming

- Plan the evidence for each queried fact, including why unaffected facts should
  remain true. Distinguish an actual wrong final fact from an unnecessary
  update operation whose final value is still correct.
- Separate native action success, actual state change, and sufficient evidence
  for the model. A supported metadata field or an object bbox alone establishes
  neither visual readability nor answerability.
- Calibrate the actual build, asset, relation/contact region, ordering and time
  window before assuming a mechanism generalizes to multiple objects or nested
  containers. Missing objects, placement/capacity failures and failed actions
  are not evidence that a mechanism is false.
- Native PutObject uses objectId for the destination. Read the held source from
  pre-event inventory. Use live relations after placement and after camera/setup
  actions; later Pass success must not hide an earlier event failure.
- Avoid assuming extra same-type objects can be spawned. Inspect native scene
  inventory first. Multi-object examples need calibrated objects and room for
  all of them; otherwise retain a smaller controlled design and mark the larger
  design conditional.
- For held containers, missing post-pickup parentReceptacles may reflect metadata
  conventions. Inspect world displacements and relative trajectories separately;
  do not silently convert missing metadata into a physical relation label.
- Record event ordering, intermediate states, elapsed wall time and any native
  simulation-time evidence. Equal numbers of Pass actions do not establish equal
  physical time; distinguish ongoing heating/cooling from the event effect.
- Plan views by role, predicate and phase: front/screen, inside/contents,
  local detail and joint relations as appropriate. Moving the camera, opening a
  door or holding an object can disturb the scene or advance physics; record
  those actions and recheck relevant preconditions rather than silently staging
  a more convenient screenshot after the evaluated event.
- Retain failed attempts and source/build fingerprints. Consider matched
  event/no-event, relation-removal and unrelated-fact controls before adding
  object count or history length. More operations do not by themselves make a
  selective-update problem structurally harder.

### Suggestions that still need the actual images

- Mechanism probes can use role-based third-party evidence cameras. Keep
  geometry candidates in `view_planning.py` and native camera/mask handling in
  `observation_views.py`; do not let incidental pickup-facing views stand in
  for deliberate task views. Use actual positions/bounds and camera-specific
  instance masks to screen framing. Complementary views from one event belong
  to one capture group, not extra physical events. Camera changes are native
  calls: record them separately, preserve pre-existing physics pauses, compare
  task state before/after, and invalidate affected mechanism measurements if
  the observation changes state. A pause does not establish an attribute clock.
- For nested setup, consider final placement of outer containers before placing
  their contents. Check each native containment edge and recheck after settling.
  Bounded alternative objects/placement paths should retain actual identities,
  reset boundaries and failed receipts; failed construction cannot refute the
  intended propagation mechanism.

- The user now prefers the reusable local web reviewer (`review_web/`,
  `New-WebReview.ps1`, `web_review.md`) over opening Markdown review pages.
  Default view: question, ordered model-visible images, and request text;
  no action logs, coordinates, visible-object inventories or model predictions.
  Reference answers belong in an optional collapsed audit area. Per-question
  decisions and reasons must be exportable; protect existing review edits.
  `New-MarkdownReview.ps1` remains an optional legacy export. Review packaging is
  an audit deliverable, not an additional simulator run or approval gate.
  Use non-Git output directories. Mechanism-only probes have no model request or
  formal questions. Old request reconstructions must be labeled as such, never
  as historical verbatim input. Read current runner/source evidence when the
  model interface changes; do not assume every future batch keeps this schema.
  For mechanism-only runs, lack of a historical model request must not leave the
  reviewer with unexplained pictures. Generate a concrete Chinese scene story,
  planned versus executed steps, physical question drafts, observed reference
  answers (or explicit incomplete measurement), and a purpose for every capture.
  Keep raw JSON/actions at the bottom. Never use a generic F-category title as
  the scenario description, and never replace missing results with design
  expectations. Separate native-mechanism verification from visual answerability.
  `Update-WebReviewScenes.ps1` enriches an existing site without changing source
  records; the expanded review has a separate namespace so old screenshot-only
  approvals are preserved rather than silently reused as full question approval.
  When source media is incomplete, state that directly before discussing viewer
  compatibility. Distinguish native capture failure/disabled observation,
  metadata-only snapshots, named-but-missing files, and incompatible paths.
  Do not attach orphan PNGs discarded by observation-state checks as evidence.
  Inspect `native_measurement_valid` separately: existing PNG bytes cannot rescue
  an observation-contaminated mechanism measurement. Export diagnostic pages
  with explicit failure reasons and preserve originals; do not call such a
  batch complete. Future camera records should carry `image_requested` so
  metadata-only captures do not require label-based inference.

- Check that the relevant face and state are visible, not just the object:
  a laptop back does not show a screen, and a device exterior may hide contents.
  Small distant cups/bowls and reflective liquids may be ambiguous.
- Inspect joint visibility of directly affected, indirectly affected and
  preserved objects; check identity across views and occlusions. Bbox/mask area
  can flag obvious framing problems, but cannot approve semantic evidence.
- Compare intended visual state cues at the actual asset/view before treating
  water/coffee, filled/empty, dirty/clean, power/breakage as distinguishable.
  Keep unreadable attributes inferential only when permitted public premises,
  event evidence and rules really determine the answer.
- Identical immediate/settled RGB can be normal after a scene stabilizes.
  Reused pictures for separate questions are also expected. Check missing
  expected cues and provenance before attributing repetition to stale rendering.
- Keep visual, visual-history-plus-rules and explicitly supplied oracle-history
  evidence distinct. Inspect raw inputs before using model errors to decide that
  an item is a reliable update-scope bad case. These hints do not mean every
  inferred final property must be directly visible.

