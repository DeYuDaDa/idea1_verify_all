# 第 15 步：准备数据盘副本并检查模型配置

这一步把旧数据根中的三个成功候选、审核表和已校验的 CloudRendering build 复制到 `/root/autodl-tmp/idea1_firsttest_20sample`。旧根保持原样，失败 attempt 的大 action log 和旧日志不迁移。脚本不改 `/root/autodl-tmp/model/qwen3.5-4b` 下的模型文件，不装包、不加载模型、不训练，也不启动 Unity。

服务器执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && bash linux_server_operation/15_prepare_data_disk.sh
```

若推理依赖在另一个已存在的 Conda 环境，可传 `--model-env 环境名`；默认用当前 server env（`thor20`）做只读探测。缺少 PyTorch 或 Transformers、或 `AutoModelForImageTextToText` 类不可用，都会记录在报告里，不会安装依赖或阻止数据搬运。

目标根默认由 `DATA_ROOT` 指向 `/root/autodl-tmp/idea1_firsttest_20sample`。复制前报告新盘可用空间并预留余量；不够则停止，不改旧数据。只复制已有成功 pair receipt 对应的 A/B public input、hidden gold、RGB 帧、setup action log、receipt、specs、generation summary，旧根和旧根 `review/` 子目录中的 review forms，以及带官方校验 receipt 的 AI2-THOR build。Build receipt 必须匹配固定 commit、大小及官方 SHA-256 `1fd5f998644a6dd522a4cf6604c05360a75a5c27f450a7486c20e52dc2b67bb9`。失败 `_attempts`、旧 logs、build ZIP 和模型权重不复制。若目标文件已有且哈希相同则幂等跳过；内容冲突时保留现有目标并报错。文件先复制到临时 staging，再用同盘原子硬链接逐文件安装，避免覆盖已有文件。

脚本只读取模型 `config.json` 的少量架构字段，并通过文件名/大小检查 safetensors 与 index 是否存在，不读取权重内容。HF snapshot 中的符号链接按目标文件读取和统计，并在报告中标明链接属性。推理环境报告包含 PyTorch/Transformers 版本、`AutoModelForImageTextToText` 导入支持情况及 `torch.cuda` 可见性/设备名称。

构建 receipt 会原样保留其中旧的 `installed_cache` 路径；报告另列旧缓存路径到新缓存路径的映射。新路径为 `/root/autodl-tmp/idea1_firsttest_20sample/unity_cache/releases/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917`，供后续结构检查与 smoke 使用。

报告写入新根 `/root/autodl-tmp/idea1_firsttest_20sample/transfer_reports/`，脚本会打印具体 JSON 路径；公共操作日志写入新根 `logs/`。新根会创建 `hf_home`、`pip_cache`、`tmp`、`model_outputs`，并提供 `model_env.sh`。以后启动模型或下载缓存前，在当前 shell 执行 `source /root/autodl-tmp/idea1_firsttest_20sample/model_env.sh`，让 HF、pip 和临时文件落在数据盘；这不会改 `HOME` 或全局 Conda 配置。

副本仍含 `hidden_gold`，仅用于代码和数据审核，绝不能作为模型输入。旧根和其余旧材料会保留在原位置。
