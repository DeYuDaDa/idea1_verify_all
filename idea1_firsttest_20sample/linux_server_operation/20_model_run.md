# 第 20 步：运行离线 Qwen3.5-4B 推理

本步骤使用第 17 步创建的独立 `model_env`，从已传到服务器的公开导出目录读取 `data/input/*.json` 和这些输入引用的 `data/media/*.png`。它只生成预测，不读取 `hidden_gold`、`private_logs`、review 文件或模拟器元数据，也不计算分数。运行时需要实际加载模型权重并使用 CUDA；第 17 步只检查依赖和 GPU，不能代替本步骤的首个推理 smoke。

## 前置条件

- 独立模型环境已成功安装并核验；本轮由第 19 步续接未完成的 17，路径默认是 `/root/autodl-tmp/idea1_firsttest_20sample/model_env`。
- 模型文件已在 `/root/autodl-tmp/model/qwen3.5-4b`。脚本使用本地文件，不联网下载权重。
- `--export-root` 必须指向完整导出根目录，至少包含 `data/input/`、`data/media/` 和供独立严格验证使用的 `hidden_gold/`；正式模式还需有当前数据指纹匹配的 review 记录。runner 的推理代码只打开 `data/input/` 里的 JSON 和所引用的 `data/media/` 图片。
- 正式模式用 `--review-approved` 时，shell wrapper 会先在独立的 `thor20` Conda 环境运行 `validate.py --strict`。只有严格验证成功，才会启动 `model_env` 推理；review fingerprint 不匹配、缺少 hidden 证据或验证未通过都会阻止正式运行。直接调用 Python runner 时也必须有 wrapper 设置的验证标记。
- 未完成 review 时，调试运行必须显式传 `--debug-unreviewed`，结果会标成 `debug_unreviewed_bypass`，不能作为正式分数或已审数据结果。

## 先跑一个图像 smoke

本轮可直接执行 `bash linux_server_operation/22_smoke_latest_candidates.sh`，它自动选择最新已完成构造且有候选的 v2 批次。下列通用示例中的 `exported` 仅是占位路径，需要替换成第 21 步打印的实际导出根：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
bash linux_server_operation/20_run_model.sh \
  --export-root /root/autodl-tmp/idea1_firsttest_20sample/exported \
  --limit 1 --debug-unreviewed
```

若人工 review 已通过，将最后一个参数换成 `--review-approved`。`--limit 1` 是默认行为，即使省略也只选一个样本；确认 smoke 的图像加载、CUDA 推理、输出格式和资源情况后，才显式请求全量：

```bash
bash linux_server_operation/20_run_model.sh \
  --export-root /root/autodl-tmp/idea1_firsttest_20sample/exported \
  --all --review-approved
```

也可用 `--limit N` 做小批量。`--all` 与 `--limit` 互斥。单次运行 batch size 为 1、greedy 解码、BF16、SDPA，默认最多生成 512 个 token；可用 `--max-new-tokens N` 调整。代码未依赖 FlashAttention。

## 输出与续跑

每次默认创建新的 UTC 时间戳目录：

`$DATA_ROOT/model_outputs/run_<timestamp>/`

其中 `run_manifest.json` 记录模型配置摘要、依赖版本、运行设置、所选公开 JSON 与图像 SHA-256、checkpoint 文件大小/修改时间及索引文件 SHA-256、review 调用状态和每个样本的输入边界；权重内容本身不做全量哈希。`predictions.jsonl` 每完成一个样本就追加并同步一行。预测保留模型原始文本、严格 JSON 格式状态、答案、匿名问题 ID 到原始 fact ID 的本地映射、输入/输出 token 数、耗时和缺失/意外问题 ID。原始 fact ID、样本 ID、A/B 标签及图像路径不会放进模型 prompt。

格式状态是 `ok`、`partial`、`invalid`、`json_parse_error` 或 `json_not_object`；模型调用失败单独标记 `error`。manifest 的 `complete` 只说明所选样本均已完成一次生成调用，不代表答案格式全部有效或答案正确。

脚本不会覆盖已存在的运行目录。要续跑失败项，必须显式指定同一 `--run-dir` 和 `--resume`；runner 会核对模型配置、软件版本、所有设置、review 调用状态及所选 JSON/图像哈希，不一致就拒绝追加。续跑会跳过已有成功行，只重试失败或尚无结果的样本。若任何样本推理失败，JSONL 保留失败行、manifest 标记 `incomplete_with_errors`，命令返回非零状态。示例：

```bash
bash linux_server_operation/20_run_model.sh \
  --export-root /root/autodl-tmp/idea1_firsttest_20sample/exported \
  --limit 1 --debug-unreviewed \
  --run-dir /root/autodl-tmp/idea1_firsttest_20sample/model_outputs/run_20261018T120000Z \
  --resume
```

默认输出根目录可用 `DATA_ROOT=/path` 覆盖；模型目录和 Conda prefix 可分别用 `QWEN_MODEL_DIR=/path`、`QWEN_ENV_PREFIX=/path` 覆盖。每次调用日志写到 `$DATA_ROOT/logs/<timestamp>_20_run_model.log`，缓存位置仍在数据盘。

模型调用使用本地 `AutoProcessor` 与 `Qwen3_5ForConditionalGeneration`，多图以 RGB 图像与有序 stage 信息输入；提示仅由公开协议说明、公开对象别名/类型、历史事实、规则、事件、图像和问题文本构成。问题在 prompt 中重编号为 `q001` 等匿名 ID。推理阶段没有评分子命令，也不将预测自动标为通过 review。
