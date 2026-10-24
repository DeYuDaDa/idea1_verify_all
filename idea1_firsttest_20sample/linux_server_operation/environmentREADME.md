# Linux 环境与迁移说明

2026-10-23 当前目标为普通 Linux 服务器、非 root 用户 `/home/mdy`，尚未安装 Conda；旧目标为 AutoDL `/root`。部署入口是 [32_user_server_migration.md](32_user_server_migration.md)，路径选择由 `server_paths.sh` 统一管理。旧诊断文档中的驱动版本和设备信息只描述历史机器。

新机模拟器 prefix 默认为 `$DATA_ROOT/thor_env`；旧 AutoDL 可不设 THOR_ENV_PREFIX 继续使用命名环境 `thor20`。两者均使用 Python 3.10、AI2-THOR 5.0.0、NumPy 1.23.5、OpenCV 4.8.1.78，完整 Python 依赖见项目 `requirements.txt`。新环境应在目标机器重新创建；不直接复制旧 Conda 环境文件夹。

CloudRendering 需要本机真实可用的 NVIDIA Vulkan 图形设备。它不要求桌面 X server，但仍需要厂商图形驱动、设备访问和用户态 Vulkan/EGL 等库。项目维持 `headless=False` 以保存 RGB；不能用关闭渲染的 headless=True 冒充图像生成已经可用。

旧日志给出的实际经验：

- 最初缺 libvulkan；后来 loader 已存在但仍无法创建 Vulkan instance。CUDA 或 nvidia-smi 成功不足以证明图形链路正常。
- 更深入跟踪确认过缺少 libEGL.so.1；补齐后才成功启动。因此新流程在 THOR 环境中检查 loader/EGL 和实际 NVIDIA Vulkan 枚举，不盲目迁移旧 ICD 或驱动库。
- 原生图形驱动与内核匹配、GPU 作业分配和设备访问权限由管理员提供。阶段 33 可准备用户态库，但不会安装系统驱动或改 /etc。
- 大 Unity ZIP 下载与实际启动分开。使用阶段 13 的 `--archive` 与 `--sha256-file` 导入已经下载好的文件；它检查大小、SHA-256、ZIP CRC、布局和可执行权限，之后 smoke 不应再下载同一个构建。
- 历史验证成功的 CloudRendering 构建为 `f0825767cd50d69f666c7f282e54abfe58f1e917`，ZIP 大小 835983275 字节，SHA-256 为 `1fd5f998644a6dd522a4cf6604c05360a75a5c27f450a7486c20e52dc2b67bb9`。仍保留匹配的官方 sidecar 作为导入依据，不用仅改文件名绕过验证。

可选的 Qwen 模型环境与 THOR 分离：Python 3.11、torch 2.10.0+cu128、torchvision 0.25.0+cu128、transformers 5.15.0、accelerate 1.11.0、Pillow 11.3.0。17/19 均已固定 torchvision，避免旧日志中处理器初始化缺依赖的失败。模型文件应完整迁入 QWEN_MODEL_DIR，脚本不自动下载模型权重。服务器是否支持这套 CUDA/BF16 推理，需看本机实际报告。

无 root 部署不执行阶段 09/12 的 apt 修复，不执行阶段 11 的安装 strace 选项，也不把旧 AutoDL 的 `/usr/lib`、ICD 配置或零字节占位库打包覆盖到新服务器。若机器本身没有可用图形驱动，请保留阶段 33 的证据并请管理员检查，反复重建 Python 环境无助于修复宿主驱动。

生成的 RGB、公开输入与答案核对材料可迁出离线运行模型，届时无需启动 Unity。只有重新生成场景或实时执行动作才依赖图形环境。