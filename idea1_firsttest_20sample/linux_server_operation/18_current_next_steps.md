# 当前证据结论与下一步

## 本轮查看的材料

Windows 原始证据位于：

`F:/md/Academic/ICML2026 paper/主线1/will_not_be_push_to_git/idea1_firsttest_20sample/pilot_evidence/20261018T072839Z_77w260/`

这是人工/代码审计包，包含 hidden gold，不能作为模型输入。

| 候选 | 实际看到的情况 | 处理 |
|---|---|---|
| C13 | 咖啡机制对照通过，但前后 RGB 主要是柜门与地面，咖啡机/杯子被边缘裁切 | 不通过视觉验收，修相机后重新构造 |
| B19 | Laptop 的 metadata 事件通过，但 RGB 是天花板/灯具，笔记本不在画面 | 不通过视觉验收，修相机后重新构造 |
| M01 | 微波炉及开门内容物能看到；原生机制通过，但 A/B 碗位置还有约 3.77 cm 的额外差异 | 保留待查，不能宣称严格配对已通过 |

核查图像包含 `C13_A_00_before_event_rgb.png`、`C13_A_02_event_settled_rgb.png`、`C13_B_02_event_settled_rgb.png`、`B19_A_00_before_event_rgb.png`、B19 A/B settled 及 M01 A/B 开门帧、A 关闭帧。图像在证据包 `exports/data/media`。没有修改原图、原状态或审核勾选。

相机几何的具体错误：旧代码把眼高固定设为 agent.y + 0.675 m，但这批事件里 `cameraPosition.y` 与 `agent.position.y` 相同；还使用物体原点而非包围盒中心。原生 `GetInteractablePoses` 的首姿态也不能直接当作渲染正确的证明。新代码使用实际相机偏移与包围盒中心，并用真实渲染框/mask 拦截缺失、过小或贴边的目标。这些修改尚需服务器实测。

失败样本还有以下构造问题：

- T16 多次失败发生在坐标查询或画面门槛；部分已完成原生烹饪对照，不能据此说加热机制不支持。setup 坐标查询改为 `anywhere=True`，真实放置、关系和观察仍需验证。
- S05 B 有 RoomTemp → Hot 的实际记录，违反本设计的“不受热”控制，继续判构造失败。现有失败日志不足以确定热源/接触原因；不改 Gold，不据此认为模型出错。
- P20 部分尝试中苹果的实际位移已满足要求，却因拾起后 `parentReceptacles=[]` 被拒。新代码在事件前确认支撑关系，事件后继续要求实际位移对照，父容器字段仅留作审计并排除相应问答。没有移动的尝试仍拒绝。
- 旧放置搜索有数百次失败重试；新代码已有每次最多 16 个去重候选的预算，避免再做无界式搜索。

## 当前服务器执行顺序

先自行将本轮 Git 代码同步到服务器，再执行。这里不包含自动提交或推送。

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
export DATA_ROOT=/root/autodl-tmp/idea1_firsttest_20sample
bash linux_server_operation/15_prepare_data_disk.sh && \
bash linux_server_operation/02_unit_checks.sh && \
bash linux_server_operation/16_camera_probe.sh
```

第 15 步复制必要缓存和旧候选，保留旧根。第 16 步只看三个目标，不重复批量生成。若任何一步失败，保留该步日志和报告，不继续全量。探针即使失败也应返回其取证包。

用户已确认模型环境尚未配置，可在另一终端独立执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
export DATA_ROOT=/root/autodl-tmp/idea1_firsttest_20sample
bash linux_server_operation/17_setup_model_env.sh
```

第 17 步安装独立模型环境，会下载依赖，详细版本和磁盘检查见同目录 `17_model_env.md`。它不加载模型权重，不启动正式推理，不更改 `thor20`。模型仍使用现有 `/root/autodl-tmp/model/qwen3.5-4b`。

本轮请返回 15 的 JSON 报告、02 日志、16 的探针 ZIP，以及 17 的环境报告和日志。报告/日志路径会由脚本打印，均在新数据根下。确认画面后再建立新的生成输出批次，不能覆盖这次已审计的旧候选，也不能把旧 receipt 当作新代码运行结果。

独立离线 VLM 推理不需要同时运行 AI2-THOR。当前没有取得 4B 模型分数，不能作更新能力结论。
