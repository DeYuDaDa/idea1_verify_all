# 第 14 步：打包现有 pilot 诊断证据

现有结果：请求六组，得到 C13、M01、B19 三组、六条候选。C13/B19 的机制检查通过；M01 因额外位置差异为 inconclusive。T16、S05、P20 构造失败。本轮上传的文本从中途开始，T16 的具体错误缺失；审核表虽存在，但六条样本的检查项仍全部未确认。

本轮已经有成功候选和失败 attempt；不需要重跑生成。本脚本只读取并选择性打包现有文件，不运行模拟器、不修改审核表，也不生成标签。服务器执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && bash linux_server_operation/14_collect_pilot_evidence.sh
```

默认读取 `/root/will_not_be_push_to_git/idea1_firsttest_20sample/exports`。若要收集另一组实验，可显式传入 `--export-root PATH`。脚本把归档与可检查的暂存目录放在 `DATA_ROOT/pilot_evidence/`，并打印可上传的 ZIP 绝对路径。

归档包括 generation summary、specs、pair receipts、六个成功样本的 A/B public input、hidden gold、RGB 帧及 `private_logs/*_setup.json`；失败 attempt 的所有 `failure.json` 摘要；每个失败 pair 最多五份精选 attempt 的 action log、A/B（若已生成）public/hidden JSON、RGB 帧和 pair check；最近的 04/04b 原始日志、最新 review form，以及 smoke report/RGB。S05 温度保持/RoomTemp 到 Hot、P20 Apple carrying boundary/`_parent_Plate` 的诊断 attempt 会优先入选，再补充首末 attempt 和不同错误类型。其余 attempt 的大 action log 不会全部打包。

`manifest.json` 记录每个归档文件的来源、大小、修改时间、用途和 attempt 选择理由，也列出缺失文件。归档排除整个 `unity_cache`、build ZIP、instance/depth 图像与未选中 action log。**包内含 `hidden_gold`，本次可回传给此对话用于代码和数据审核；不能将它作为待评测模型的作答输入。** 正式离线测试仍使用第 07 步的纯公开输入包。Review form 原样复制，脚本不会更改其中的检查项。

本轮还对未来生成增加了尝试时间、简短终端错误和失败时的真实元数据快照；放置搜索改动属于后续限时尝试，不能据此认定三个失败机制已修复。旧失败样本可能没有完整失败快照，这是旧版只导出成功样本的局限；不会通过重新运行来冒充本轮原始证据。代码修改后生成指纹会改变，不直接在旧 exports 里重跑 04。

新增放置搜索默认为最多 16 个去重、空间分散的原生候选点。达到该上限仅表示本次有限搜索失败，不证明场景不存在合法放置。对应边界测试已加入但未在 Windows 运行；后续若决定试运行新版生成器，先在服务器运行已有的 `bash linux_server_operation/02_unit_checks.sh`。本轮取证命令不调用生成器，也不执行这些测试。

后续核查时，先从原始 action log 确认 `No valid Receptacle found in view` 发生在哪个动作，不能直接归因到 PutObject。官方 [交互物理文档](https://ai2thor.allenai.org/ithor/documentation/interactive-physics/) 给出了生成落点查询的 `anywhere` 参数和携带容器的规则；P20 还需区分实际位置变化与拾取期间的关系字段。官方仓库的 [Issue #1209](https://github.com/allenai/ai2thor/issues/1209) 有拾取后容器关系元数据的相关报告，但不等于已证明本轮是同一原因。S05_B 的日志明确记录 RoomTemp 到 Hot，必须核对实际位置和控制状态，而非把结果强改成“保持”。

用户当前服务器为单张 4090、20 核 CPU、90 GB RAM。批量阶段可从两个独立 Unity 工作进程做吞吐测试，并隔离输出、日志及服务端口，同一对 A/B 在同一进程完成。现阶段先收本轮证据；不把增加并发作为重复失败的处理方式，也不在本轮启动新的模拟器任务。
