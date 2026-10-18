# Development contract

- This Windows checkout is for editing and Git file management only. Do not run project Python, tests, simulators, WSL, dependency installation or environment setup here.
- Server project path: `/root/idea1_verify_all/idea1_firsttest_20sample`.
- Put every requested Linux execution command in `idea1_firsttest_20sample/linux_server_operation/`, with execution order and expected result documented there.
- New generated datasets, machine reports, execution logs, model environments and caches belong under `/root/autodl-tmp/idea1_firsttest_20sample` on the server data disk. The existing model is `/root/autodl-tmp/model/qwen3.5-4b`. Preserve legacy evidence under `/root/will_not_be_push_to_git/idea1_firsttest_20sample`; stage 15 copies selected artifacts without deleting originals. The Windows non-Git directory remains `F:/md/Academic/ICML2026 paper/主线1/will_not_be_push_to_git`.
- Never report code as tested, data as generated, or design hypotheses as simulator ground truth without server execution evidence.
- Keep model-visible input and hidden scoring metadata physically separate. Derive labels from actual before/after metadata and audit event success, capability applicability, knowledge conditions and paired controls.
- The design contains 20 A/B pairs, 40 scene records. Unsupported mechanisms or failed construction attempts must remain explicit failures, not fabricated samples.

