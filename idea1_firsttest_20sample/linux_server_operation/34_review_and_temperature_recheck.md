# 34：本次运行核对、Markdown 审核与温度字段复查（2026-10-24）

## 本轮已有结果

20261024T085851Z 批次确实完成 90 次尝试。退出码 2 来自 4 条被归类为 probe_error 的摆放失败，不等于整批没跑。旧包是原始证据，保持不变；新代码与新运行另存目录，不能重写旧包使它假装通过。

本次 Markdown 审核已经在 Windows 用 PowerShell 整理现有 JSON/图片完成；这不是运行项目 Python、模拟器或模型。工具为项目根目录 `New-MarkdownReview.ps1`，使用方法见 `markdown_review.md`。以后下载完整导出目录后可用同一工具生成新的审核包，不覆盖已勾选的旧包。

当前机制批次没有 model_input/questions，也没有调用模型。审核包必须保留这一事实，不能将原生探针检查包装成模型原题。正式公开数据则使用 Dataset 模式，按公开字段和图片顺序导出逐题审核材料；若历史请求未记录，应标记为按当前 runner 重建，不能声称恢复 exact prompt。

## 需要修正后复查的记录

- 真实 metadata 用 `temperature`；F2/F4 某些读取请求为 `ObjectTemperature`，原公共读取器只单向兼容，导致 8 条错误的 setup_unavailable。新代码双向处理别名，不填默认温度、不修改原始 snapshot。
- F1 两处前后温度键不一致也已修正，避免将缺失值与有值比较误算成变化。
- 已知摆放失败通过 ProbeUnavailable 明确记录，不当作代码异常或成功事件的机制反例。
- F5 水流开启且物体在水槽里不等于已验证水流接触。新代码保留无效果记录，并对接触未确认的开水失败条件保守标 inconclusive。旧包三个 counterexample 原标签不改。

下面只复查受温度读取影响的八个探测模板，每个最多两个场景，共最多 16 次尝试。不会重跑全部 45 个模板，也不运行模型。31 会先执行新的契约检查；本轮没有在 Windows 执行这些 Python 检查。

```bash
source "$HOME/.config/thor20/server.env" && \
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample" && \
bash linux_server_operation/31_probe_native_mechanisms.sh \
  --cases f1_toaster_enter_then_activate,f1_toaster_activate_then_enter,f1_microwave_enter_then_activate,f1_microwave_activate_then_enter,f2_microwave_inside,f2_microwave_outside,f4_uncooked_then_heated_and_cooled,f4_cooked_then_reheated_and_cooled \
  --max-scenes 2
```

预期是原来“温度字段缺失”不再因键名不一致而失败，不是预先保证机制一定成功。如果原生状态/摆放/冷却仍不满足，继续保存其真实失败或未知结果。返回新 ZIP 和运行日志即可。F5 要先确认接触位置，F10/F11 要先建立可用构造，不建议无改动反复全量重跑。
