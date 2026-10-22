# Development contract

- This Windows checkout is for editing and Git file management only. Do not run project Python, tests, simulators, WSL, dependency installation or environment setup here.
- Server project path: `/root/idea1_verify_all/idea1_firsttest_20sample`.
- Put every requested Linux execution command in `idea1_firsttest_20sample/linux_server_operation/`, with execution order and expected result documented there.
- New generated datasets, machine reports, execution logs, model environments and caches belong under `/root/autodl-tmp/idea1_firsttest_20sample` on the server data disk. The existing model is `/root/autodl-tmp/model/qwen3.5-4b`. Preserve legacy evidence under `/root/will_not_be_push_to_git/idea1_firsttest_20sample`; stage 15 copies selected artifacts without deleting originals. The Windows non-Git directory remains `F:/md/Academic/ICML2026 paper/主线1/will_not_be_push_to_git`.
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

