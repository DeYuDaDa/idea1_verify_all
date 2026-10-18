# 第 17 步：隔离安装并核验 Qwen3.5-4B 推理环境

本步骤在 Linux 服务器的数据盘创建独立 Conda prefix：

`/root/autodl-tmp/idea1_firsttest_20sample/model_env`

它与 AI2-THOR 的 `thor20` 环境分开，不修改 Conda 全局配置，不触碰 NVIDIA 驱动，也不下载或加载模型权重。默认模型目录为 `/root/autodl-tmp/model/qwen3.5-4b`。本步骤只安装推理依赖、读取本地 `config.json` 和 processor 文件、检查 Transformers 类与 PyTorch GPU/显存；不运行生成、不做推理。

## 版本依据

固定使用 Python 3.11、PyTorch 2.10.0 CUDA 12.8 wheel、匹配的 torchvision 0.25.0 CUDA 12.8 wheel、Transformers 5.15.0、Accelerate 1.11.0 和 Pillow 11.3.0。PyTorch 官方历史版本安装页将 torch 2.10.0 与 torchvision 0.25.0 配对并提供 cu128 命令。第 17 步日志已证实缺少 torchvision 会阻止 `AutoProcessor.from_pretrained()`：Qwen 的 AutoProcessor 会加载视频处理器组件，即使本任务只输入图片也需要 torchvision。Transformers 5.15 文档说明 Python 3.10+、PyTorch 2.5+，其 Qwen3.5 文档包含 `AutoProcessor` 与 `Qwen3_5ForConditionalGeneration`；Qwen3.5-4B 官方模型卡给出多模态加载范式。这里采用稳定版，不安装 Transformers GitHub `main`。

官方依据：[Qwen3.5 Transformers 文档](https://huggingface.co/docs/transformers/v5.15.0/model_doc/qwen3_5)、[Transformers 5.15 安装与兼容范围](https://huggingface.co/docs/transformers/v5.15.0/en/installation)、[Qwen3.5-4B 模型卡](https://huggingface.co/Qwen/Qwen3.5-4B)、[PyTorch 官方版本与 CUDA wheel 列表](https://pytorch.org/get-started/previous-versions/)、[Accelerate 1.11 文档](https://huggingface.co/docs/accelerate/v1.11.0/quicktour)。Qwen 模型卡没有声明精确的最低 Transformers/PyTorch 版本；上述 pin 是依据正式 Qwen3.5 模型文档与官方兼容范围选出的固定组合，不应解释成模型卡公布的最低版本。

## 运行

本步骤可独立于相机探针和第 15 步运行；会自行创建 DATA_ROOT 及其缓存/日志目录。先确认模型目录已存在，然后只在 Linux 服务器执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && \
bash linux_server_operation/17_setup_model_env.sh
```

脚本先检查 DATA_ROOT 所在文件系统空间，低于 20 GiB 可用空间就停止，然后才创建目录或下载依赖。20 GiB 是保守的操作门槛，不是对 wheel 实际体积的测量；压缩下载包、解压后的环境和缓存均会占用数据盘。安装后还要求至少剩余 8 GiB，供后续环境运行和结果写入。模型权重已在单独的 `/root/autodl-tmp/model/qwen3.5-4b` 路径，脚本不会复制或下载它们。

依赖安装会从官方 PyTorch CUDA 12.8 wheel 索引安装 torch 与 torchvision，再从默认 PyPI 获取 Transformers、Accelerate 和 Pillow。torchvision 的 metadata pin 是 `0.25.0+cu128`。下载总量会随 wheel、平台依赖和缓存状态变化；本步骤没有实测下载大小，因此不提供伪精确的 GB 数。Conda 包缓存、pip 缓存、Hugging Face 缓存与临时目录都指向 `DATA_ROOT`。脚本不会升级已存在的冲突包版本；若发现任一固定包同名但版本不符，会停止并保留现状。若 prefix 已存在且 Python 可执行，脚本复用该 prefix。

可选路径覆盖：

```bash
DATA_ROOT=/root/autodl-tmp/idea1_firsttest_20sample \
QWEN_MODEL_DIR=/root/autodl-tmp/model/qwen3.5-4b \
CONDA_EXE=/root/miniconda3/bin/conda \
bash linux_server_operation/17_setup_model_env.sh
```

检查成功会生成：

- `$DATA_ROOT/transfer_reports/<时间>_17_model_env_report.json`：Python/包版本（含 torchvision）、本地模型 `model_type`、`architectures`、`vision_config`、processor 类、Transformer 模型类可用性、PyTorch CUDA 构建、GPU 驱动查询及空闲/总显存。
- `$DATA_ROOT/qwen_model_env.sh`：后续推理 shell 使用的数据盘缓存变量。
- `$DATA_ROOT/logs/<时间>_17_setup_model_env.log`：安装与检查日志。

缓存激活文件使用独立的 `qwen_model_env.sh` 名称，不覆盖第 15 步可能生成的 `model_env.sh`；`model_env` 目录是本步骤的 Conda prefix，两者不会重名冲突。

验证只通过 `AutoConfig.from_pretrained(..., local_files_only=True)` 和 `AutoProcessor.from_pretrained(..., local_files_only=True)` 读取配置/processor；不调用任何模型 `from_pretrained` 权重加载、不调用 `generate`。配置须为 `model_type: qwen3_5` 且包含 `vision_config`，processor 须可从本地目录读取，并要求 `Qwen3_5ForConditionalGeneration` 可导入、PyTorch 能访问 CUDA。未满足条件时脚本仍先写出 JSON 报告，再以失败结束。报告中的 GPU 显存是检查当时的瞬时值。

后续独立推理步骤开始前，在同一 shell 中执行：

```bash
source /root/autodl-tmp/idea1_firsttest_20sample/qwen_model_env.sh
conda run --no-capture-output -p /root/autodl-tmp/idea1_firsttest_20sample/model_env python -c \
  'import torch, transformers; print(torch.__version__, transformers.__version__, torch.cuda.is_available())'
```

如果 PyTorch 找不到 CUDA，先保留第 17 步报告与日志核对驱动兼容性；不要在本步骤升级 NVIDIA 驱动。此时尚未加载模型权重，也没有生成任何模型预测。第 17 步成功只证明依赖、配置、processor 和 GPU 检查通过，不代表模型已经完成推理验证。
