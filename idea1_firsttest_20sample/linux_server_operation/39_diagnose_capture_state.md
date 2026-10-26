# Step38 图片生产失败：先跑一次取景状态诊断

2026-10-26 最新返回：`20261026T073627Z_..._foxXn6_31_mechanisms.zip`。
暂停及15次Add/Update相机调用成功，未检出被保护字段差异；首次差异和拒绝在
index=17的 `UnpausePhysicsAutoSim`，7个对象有位置/旋转变化，另有运动标记变化。
3张候选视图被作废，4张诊断图仅供定位；没有执行咖啡事件，不能新增机制结论。
不能由此区分相机影响和恢复物理时的背景演化，保护仍保留。

第40步原生状态验证已经成功。**当前无需重跑39、40或全45组；
先交回Idea讨论，按新组选中的必要条件补验证。图片链路尚未验收，不作为机制讨论的前置条件。**

此前 `20261025T163737Z_..._VRxZVu` 返回包的首次阻断是暂停时的 `isMoving` 控制变化，
源码随后已按阶段修订比较。下文保留历史诊断流程；schema v2 另有 `first_rejected_action`
和 `guard_changed_entities`，用来区分“原始字段变化”与“真正触发拒绝的变化”。

对应用户的原包：`20261025T073047Z_mechanism_probe_20261025T073047Z_gN20Ns_31_mechanisms.zip`。

本轮发现：16 次尝试都在首次取景触发原生状态变化检查，后续取景被停用；原始包的证据图片不完整，16 条原生测量也被标为无效。解压并未丢失 ZIP 里的 PNG。旧网页另把 13 个不要求拍图的重置快照算成了缺图。

当前修改还不能宣称修好了状态变化的根因，也没有放松状态检查。
已增加字段级诊断，并在首次取景失败后停止该次尝试，避免继续产出大量空图。
新包的 `diagnostics/observer/` 会保存出错时的原始前后元数据及可取得的诊断图；
恢复物理推进后被作废的已写图片移到 `diagnostics/invalidated_rgb/`，不进入题目证据。
不要直接重跑 16 条或 45 个模板。

先同步这些源码到当前 Linux checkout：

- `observation_views.py`
- `mechanism_probe_common.py`（新增 `image_requested`，明确区分拍图与只存状态）
- `mechanism_probe.py`（取景失败和原生测量失效会直接提示并返回非零）
- `tests/test_observation_views.py`
- `tests/test_mechanism_registry.py`
- `tests/test_mechanism_common.py`
- `mechanism_probes_relations.py`（F10 观察仍推进 36 次 Pass，图像改用共享采样并补干预前截图）
- `linux_server_operation/31_probe_native_mechanisms.sh`
- `linux_server_operation/39_diagnose_capture_state.sh`

继续使用当前可工作的已有环境，不安装或重建。运行：

```bash
source "$HOME/.config/thor20/server.env" &&
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample" &&
bash linux_server_operation/39_diagnose_capture_state.sh
```

它沿用第31步的相关测试、锁、缓存和证据打包，只运行 **1 个模板 × FloorPlan2 一个场景**，后续 Pass 观察缩短为 0。目标是复现首张 `scene_initial` 取景问题，不是正式机制重测。该首张取景发生在后续 Pass 观察前，缩短后续观察不改变这一步的定位目标。

如果同样失败，新的非零退出是正确告警，不表示诊断包没有保存。把终端最后的 `Bundle:` ZIP 和该次31日志带回；不要只拷贝网页目录。重点字段：

```text
capture_index.json[*].camera_audit.state_diff_audit
  first_changed_action: phase / action / action_index
  action_checks[*].changes[*]:
    object_id / status / selected_target_roles / unrelated_object
    fields.<字段名>.before / after
```

覆盖 Pause、Add、Update、选定视角、Unpause 各阶段；对象与字段差异有上限，截断会明确标记。
`diagnostics/observer/<capture>/before.json` 和对应 `*_after.json` 另存原始元数据。
原有变化检测与作废规则保留；首次失败的收据写完即停止该次实验，收尾只存状态。
只有拿到这些真实差异，才能区分场景尚在稳定、真实状态变化和表示比较过敏，并据此修复；之后才重新生成受影响的正式图片。

Windows 本轮只执行数据导出和静态检查，没有执行 Python 测试、Unity 或模型。这些新增测试和真实诊断须以 Linux 结果为准。
