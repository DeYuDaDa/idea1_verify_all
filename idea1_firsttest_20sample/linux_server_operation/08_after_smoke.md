# 首轮试启动成功后

2026-10-18 已有实际服务器证据：固定构建包导入成功，第 03 步在 FloorPlan1 返回 `simulator_started`、`rgb_shape: [480, 640, 3]`、`object_count: 77`、`controller_version: 5.0.0`。下一步验证场景构造，无需重复环境修复或下载。

只在 Linux 服务器执行以下命令。先检查 `smoke/report.json` 和 `smoke/scene_rgb.png`，不要只根据 Python 未报错就判定渲染画面正确。

## 六组试生成与检查

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
bash linux_server_operation/04_generate_pilot.sh
bash linux_server_operation/04b_inspect_pilot.sh
```

`04` 返回 2 表示至少一组构造失败。已经成功的候选及失败日志都会保留。先把 `generation_summary.json`、有关 `_attempts/.../failure.json` 和当前阶段日志返回，不要靠反复改 Gold 来凑齐结果。

本轮只运行上面两条阶段命令，目标是六组 A/B、12 条场景记录。将以下材料返回后再决定修复或扩展：`exports/generation_summary.json`、第 04 与 04b 阶段日志，以及 `smoke/scene_rgb.png`。如有构造失败，再附对应 `_attempts` 下的失败记录。所有路径均在 `/root/will_not_be_push_to_git/idea1_firsttest_20sample/` 内；日志在 `logs/`。`pending_review` 表示候选尚未人工核验，不能当作已验收数据。

## 审阅候选

```bash
bash linux_server_operation/06a_prepare_review.sh
```

该命令打印审核表的路径。表里有每条样本的图像路径和三个检查项，初值均为 false。检查同一对 A/B 的当前关系、前置条件、视野和声明规则是否充分。某项不成立时保留 false，并说明需要修复的数据或场景；不要改变隐藏元数据的事实值来通过校验。

检查完成后，使用真实的审核表路径与审核人标识：

```bash
bash linux_server_operation/06b_apply_review.sh /root/will_not_be_push_to_git/idea1_firsttest_20sample/实际审核表文件名.json 实际审核人
bash linux_server_operation/06_validate.sh /root/will_not_be_push_to_git/idea1_firsttest_20sample/exports C13,T16,M01,S05,B19,P20
```

审核表与 JSON、图像绑定；修改数据后需要重新检查。审核记录不能把失败的原生机制转为成功。

## 六组也可以先离线测试

```bash
bash linux_server_operation/07_package_offline.sh /root/will_not_be_push_to_git/idea1_firsttest_20sample/exports /root/will_not_be_push_to_git/idea1_firsttest_20sample/pilot_public_inputs.zip C13,T16,M01,S05,B19,P20
```

ZIP 只含公开模型输入和 RGB，私有评分映射单独留在 `exports/packaging_maps`。模型只读 `model_input` 与图像内容，不读隐藏答案或审核表。复制这个 ZIP 到模型平台后无需运行 AI2-THOR。

## 扩展到全部设计

```bash
bash linux_server_operation/05_generate_all.sh
```

该命令使用 `--resume`，只在代码指纹相同且配对完整时跳过已有候选。代码改变后，为新一轮设置新的 Git 外 `DATA_ROOT`；不要覆盖旧证据。全量完成后重新生成覆盖当前数据的审核表、审核、严格校验，再执行打包。
