# 第 19 步：安全续接模型环境安装

第 17 步日志停在下载 `mpmath`，目前不能视为安装成功。对这次未完成状态，使用本步骤续装，不要重跑旧的第 17 步安装命令。本步骤先扫描是否已有针对该 `model_env` 的 pip/conda 安装进程。发现仍在运行时，只读取 dist-info 元数据、模型配置和 `nvidia-smi` 状态，打包报告与日志，然后以 pending 退出；不会在安装中导入 Python 包、启动第二个安装或终止原进程。请等原进程自行结束后再运行一次。

在服务器执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && bash linux_server_operation/19_continue_model_setup.sh
```

没有安装进程时，脚本从 pip `http-v2` 缓存中识别完整 wheel body，在数据盘建立 hardlink 优先的 `recovered_wheels` wheelhouse；原缓存不改动。之后先从 PyPI 补普通 `mpmath`/`sympy`，CUDA PyTorch 仅从官方 cu128 wheel 索引安装。对已安装的 torch 发行版，脚本按当前 Python 平台 marker 解析其依赖；仅对缺失或版本不满足的依赖，从 wheelhouse/PyPI 安装。这样可以恢复缓存中的 NVIDIA CUDA wheels，且不走 PyTorch 索引下载慢速的普通数学依赖。其余 Transformers、Accelerate、Pillow 及普通依赖从 PyPI 获取。四个直接依赖 pin 沿用第 17 步：torch `2.10.0+cu128`、transformers `5.15.0`、accelerate `1.11.0`、Pillow `11.3.0`；任一已安装版本冲突就停止，不替换这些直接依赖。为满足 torch 发布元数据，缺失或不兼容的传递依赖可能被安装或调整。

每次执行都会在 `$DATA_ROOT/transfer_reports/` 写环境报告，并在 `$DATA_ROOT/model_setup_evidence/` 保存包含本阶段日志和报告的 tar.gz。完成探测检查固定包版本、`pip check`、Transformers 类、从本地目录加载 processor、模型 vision 配置和 `torch.cuda`；不会读取权重。若此前进程仍在运行，报告状态为 `pending_active_install`；等待结束后重跑本步骤即可。安装前要求至少 20 GiB 可用空间，完成后保留至少 8 GiB；Conda 包缓存、pip/HF 缓存和临时目录都指向 `$DATA_ROOT`。

大文件缓存继续放在数据盘的 `$DATA_ROOT/pip_cache` 与 `$DATA_ROOT/tmp`。默认模型目录仍是 `/root/autodl-tmp/model/qwen3.5-4b`；脚本不会修改模型目录。
