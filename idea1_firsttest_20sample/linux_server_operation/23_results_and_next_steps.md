# 本轮结果与执行命令（2026-10-18）

## 已返回的证据

| 步骤 | 本轮结论 | 依据 |
|---|---|---|
| 15 | 复制成功 | `20261018T083428Z_15_prepare_data_disk.log` 报 `installed_or_identical_files`；约 1.11 GB 文件复制到数据盘，旧根保留 |
| 02 | 通过 | `20261018T083436Z_02_unit_checks.log`：30 tests，OK |
| 16 | 程序检查失败；实际校准图已入镜 | `20261018T083440Z_camera_probe_bundle.zip` 的三目标 after_calibrated RGB 有咖啡机、笔记本和微波炉；分割图也有目标，框却全为 null |
| 17 | 上传的日志不足以证明安装完成 | `20261018T083439Z_17_setup_model_env.log` 末尾仍为 Downloading mpmath，没有安装完成、Transformers 安装或最终报告；不能据此确定安装仍在运行、被中断还是只上传了未完成日志 |

16 的代码缺陷已定位：AI2-THOR 的检测框/mask 是惰性 Mapping，原代码只接收 dict，因而拒绝了真实分割结果。现已支持惰性映射及数组式框值，继续要求实际画面区域，未改用 metadata.visible 放行。增加回归测试，但新修改尚未在服务器运行。新探针记录源码哈希，生成入口只接受当前代码对应的通过结果。

## 先同步本轮代码，然后两个终端分别执行

终端一：修复检测读取后，自动测试、检查三目标相机，再生成新候选批次。

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
export DATA_ROOT=/root/autodl-tmp/idea1_firsttest_20sample
bash linux_server_operation/21_generate_candidates.sh
```

这条命令内部执行 02 和 16，任一失败就不会生成。通过后尝试全部 20 组 A/B 设计；每组先查两个房间、两个种子，每次放置最多 16 个去重候选。优先使用已有证据较多的房间。这是有界的首轮搜索，失败意味着本轮没构造出来，不能据此断言机制不支持。暂时串行用一个 Controller，避免同时变更并发和样本构造逻辑。

新批次写入 `$DATA_ROOT/exports_scope_v2_<时间>_<随机后缀>`，与旧 exports 分开，但共用已有 Unity 缓存。每组仍要求实际机制对照通过才能发布，构造失败保留原生证据。即使部分失败，也先写验证报告、未勾选的审核表及本轮 ZIP，再以非零状态退出；不补造缺失条目。ZIP 含 hidden gold，仅用于这里的审查，不能给模型当输入。

终端二：检查并续接模型环境安装。

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
export DATA_ROOT=/root/autodl-tmp/idea1_firsttest_20sample
bash linux_server_operation/19_continue_model_setup.sh
```

若 17 的安装仍在跑，19 会报告 pending 并退出，不同时运行第二个安装任务。等原安装结束后再执行 19。若没有安装进程，19 优先恢复已完整下载的 wheel，普通依赖从 PyPI 补装，避免在 PyTorch 索引慢速下载普通包。它不删除旧环境，不改 NVIDIA 驱动。详细行为见 `19_continue_model_setup.md`。本次用 19 续接，不重跑 17 的旧安装命令。

## 新批次产生候选、19 最终核验通过后

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
export DATA_ROOT=/root/autodl-tmp/idea1_firsttest_20sample
bash linux_server_operation/22_smoke_latest_candidates.sh
```

22 只选最新 v2 批次的一条公开输入，通过第 20 步加载本地 `/root/autodl-tmp/model/qwen3.5-4b`，检验“模型加载 → 多图输入 → 回答 → 保存原始输出”能否跑通，不同时启动 THOR。它不回退到旧批次；最新批次未完成或没有候选时直接停止。它明确使用 `--debug-unreviewed`，不会把这次结果当作有效评测分数。

推理进程只读公开 history、rules、event、questions 及 RGB，问题编号会匿名化；不读取隐藏答案或把 A/B 文件名传入 prompt。输出包含原始回答、格式错误/缺题信息及输入图片哈希。正式批量比较须先审核新样本；全部输入的显式调用和续跑说明见 `20_model_run.md`。

## 这轮需要返回

- 21 打印的本批取证 ZIP，以及 21 日志；其中包含构造结果、验证报告、失败原因、源代码快照及审核表。
- 若 16 又失败，返回其新的 camera_probe_bundle ZIP（21 会在生成前停止）。
- 19 打印的环境取证包及最终报告；pending 也会记录。
- 22/20 的日志及对应 `model_outputs/run_*/run_manifest.json`、`predictions.jsonl`。

这些文件都在 `/root/autodl-tmp/idea1_firsttest_20sample` 下。旧证据没有被改写。本轮 Windows 端只读证据、修改代码并做静态检查；尚未执行新脚本或获得当前 4B 的模型结果。
