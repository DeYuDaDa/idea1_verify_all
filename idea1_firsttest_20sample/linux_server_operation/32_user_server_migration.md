# 普通 Linux 用户空间迁移与启动步骤

这份说明用于在没有 sudo/root 权限的普通 Linux 账号下，从干净服务器准备本项目的 AI2-THOR 环境。所有 Conda、Python 包、Vulkan/OpenGL 用户态库、项目缓存、日志和数据都放在用户目录或数据盘；不要求管理员安装 Conda，也不要求复制旧机器的 Conda 环境或 NVIDIA 驱动。Linux 主机仍须由管理员提供可用的 NVIDIA 驱动与 Vulkan ICD。

## 迁移前准备

请先在目标服务器确认账号可以写入 `$HOME`，系统是 Linux x86_64，并且项目要使用的磁盘空间足够。当前项目源码建议放在 `$HOME/idea1_verify_all/idea1_firsttest_20sample`；可以在 Linux 上 clone 仓库，或把 Windows checkout 上传过去。若要保留本地 Git 管理和提交状态，上传/克隆时保留 `.git`。排除 Python 缓存、旧 Conda 环境、`__pycache__`、旧机器日志、自动生成数据以及 `will_not_be_push_to_git` 私有证据目录。不要上传或恢复旧服务器的环境目录、`LD_LIBRARY_PATH`、NVIDIA 驱动文件或系统 Vulkan ICD 文件。

复用你之前已经下载好的 AI2-THOR ZIP，不必重新下载大文件。先在目标服务器创建上传目录：

```bash
mkdir -p "$HOME/installers/ai2thor"
```

第 13 步记录的固定 AI2-THOR 5.0.0 CloudRendering ZIP 是 835,983,275 字节，SHA-256 为 `1fd5f998644a6dd522a4cf6604c05360a75a5c27f450a7486c20e52dc2b67bb9`。同时上传匹配的官方 `.sha256` 文件；若没有保留，只补下载这个小文件即可。下面官方地址用于核对来源或补文件：

- ZIP：<https://s3-us-west-2.amazonaws.com/ai2-thor-public/builds/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917.zip>
- 官方 SHA-256 sidecar：<https://s3-us-west-2.amazonaws.com/ai2-thor-public/builds/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917.sha256>

保存/上传后的精确文件名和位置应为：

```text
$HOME/installers/ai2thor/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917.zip
$HOME/installers/ai2thor/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917.sha256
```

下面的命令按上述统一文件名编写；如果继续保留 `build.zip` / `build.sha256` 等旧名字，只需把第 13 步的两个参数改为实际文件路径。校验取决于文件内容，不依赖文件名。如果要在新主机使用已有 Qwen3.5-4B 权重，可选上传到 `$HOME/model/qwen3.5-4b/`；AutoDL profile 则使用 `$HOME/autodl-tmp/model/qwen3.5-4b/`。模型权重缺失不影响 AI2-THOR 基础环境和 simulator-only 阶段。

## 选择数据盘并保存本次登录配置

登录新服务器后，先进入项目目录。普通 Linux 默认把数据写到 `$HOME/experiment_data/idea1_firsttest_20sample`；AutoDL profile 使用 `$HOME/autodl-tmp/idea1_firsttest_20sample`。确认 `$HOME/miniforge3` 所在文件系统允许执行程序，数据目录所在文件系统可写且有足够配额；部分共享盘带 `noexec` 挂载选项或用户配额很小。遇到这种情况，在下方 `server.env` 配置的 Optional 位置填写自己的 DATA_ROOT，例如 `export DATA_ROOT=/mnt/user-data/idea1_firsttest_20sample`，指向有执行权限、空间充足且用户可写的数据卷，并保持配置中的 `THOR_ENV_PREFIX="$DATA_ROOT/thor_env"`、`QWEN_ENV_PREFIX="$DATA_ROOT/model_env"`。Miniforge 仍安装在 `$HOME/miniforge3`；若 `$HOME` 也挂载为 `noexec`，请管理员提供可执行的用户目录或卷，不能用 sudo 绕过限制。明确选择 profile，避免在普通 Linux 上误写 AutoDL 路径：

```bash
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample"
```

当前 `/home/mdy` 只执行下面这组 home 配置。迁回 AutoDL 的替代配置在文档后半部分，当前不要执行。配置保存在用户目录，每次重新登录后先 source；不会改 `.bashrc`：

```bash
mkdir -p "$HOME/.config/thor20"
cat > "$HOME/.config/thor20/server.env" <<'EOF'
unset DATA_ROOT THOR_ENV_PREFIX QWEN_ENV_PREFIX QWEN_MODEL_DIR CONDA_EXE PYTHONPYCACHEPREFIX OLD_DATA_ROOT
export THOR_SERVER_PROFILE=home
export SERVER_HOME="$HOME"
# Optional: export DATA_ROOT=/mnt/user-data/idea1_firsttest_20sample
source "$HOME/idea1_verify_all/idea1_firsttest_20sample/linux_server_operation/server_paths.sh"
export THOR_ENV_PREFIX="${THOR_ENV_PREFIX:-$DATA_ROOT/thor_env}"
EOF
source "$HOME/.config/thor20/server.env"
```

以后重新登录时，先运行：

```bash
source "$HOME/.config/thor20/server.env"
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample"
```

请同步完整源码，包括 `server_paths.sh`。若换用其他数据盘，在配置文件注释的位置写自己的 DATA_ROOT，然后再 source profile。之后改变 DATA_ROOT 时，也同步调整 THOR_ENV_PREFIX、QWEN_ENV_PREFIX 和 PYTHONPYCACHEPREFIX。切换 profile 使用新的登录 shell，以免旧环境变量覆盖新默认值。

## 先做无安装的脚本检查

在上面配置已加载的同一个 shell 中执行。第一行只检查 shell 语法；第二行使用临时目录和假的 Conda 入口检查路径/环境选择，不下载、不启动 Unity：

```bash
(
  set -e
  for script in linux_server_operation/*.sh; do bash -n "$script"; done
  bash linux_server_operation/test_portable_paths.sh
)
```

如果检查失败，先保留输出，不开始安装。Python 字节码缓存默认重定向到 `$DATA_ROOT/pycache`，单测阶段不会把新缓存写进代码目录。配置中显式 THOR_ENV_PREFIX 时，01/02/03/31 都使用同一个 prefix；未设置时，旧脚本继续支持名为 thor20 的环境。

## 安装 Miniforge 和 THOR 用户态图形库

先保存机器信息。该步骤只做静态预检，不启动 Unity：

```bash
bash linux_server_operation/00_preflight.sh
```

如果 `$HOME/miniforge3` 不存在，安装脚本会从 conda-forge 官方 GitHub Release 下载固定版本 Miniforge `26.7.2-1` 的 Linux x86_64 installer 和官方 `.sha256` sidecar，完整校验 SHA-256 后才运行批处理安装。每次 installer 下载最多 5 分钟，重跑可续传 `.part`；失败时保留下载文件和日志。脚本拒绝覆盖已存在的 `$HOME/miniforge3`，不会运行 `conda init`，也不改 shell 启动文件。已经有 Miniforge 时跳过此步骤并确认 `CONDA_EXE` 指向其可执行文件：

```bash
bash linux_server_operation/32_install_user_conda.sh &&
export CONDA_EXE="$HOME/miniforge3/bin/conda"
```

若服务器不能访问 GitHub，可在另一台电脑下载下面两个固定版本文件，上传到 `$DATA_ROOT/installers/miniforge-26.7.2-1/`，再重跑 32；已有完整文件会复用并校验，不会执行未校验的安装器：

- [Miniforge 安装器](https://github.com/conda-forge/miniforge/releases/download/26.7.2-1/Miniforge3-26.7.2-1-Linux-x86_64.sh)，保留文件名 `Miniforge3-26.7.2-1-Linux-x86_64.sh`。
- [匹配的官方 SHA-256 文件](https://github.com/conda-forge/miniforge/releases/download/26.7.2-1/Miniforge3-26.7.2-1-Linux-x86_64.sh.sha256)，保留文件名 `Miniforge3-26.7.2-1-Linux-x86_64.sh.sha256`。

先给专用 THOR Python 3.10 prefix 安装用户态 Vulkan/OpenGL loader 与工具，再安装项目 Python requirements。该命令不会修改系统驱动、系统 ICD 或其他 Python 环境：

```bash
bash linux_server_operation/33_user_graphics_check.sh --install-user-libs && \
bash linux_server_operation/01_setup_env.sh && \
bash linux_server_operation/02_unit_checks.sh
```

`33` 会在 `$THOR_ENV_PREFIX` 创建 Python 3.10 环境（若尚无环境），并从 conda-forge 安装 `vulkan-tools`、`libvulkan-loader`、`libegl`、`libgl` 和 `libglvnd`。这些包只放在 THOR 环境。它写出 `$DATA_ROOT/thor_graphics.env`，由项目公共 `run_python` 在 THOR 命令运行时临时把 `$THOR_ENV_PREFIX/lib` 加到 `LD_LIBRARY_PATH`；不会把该路径全局加到登录 shell，也不会传给独立 Qwen 推理环境。第 01 步沿用已有 `requirements.txt` 的版本 pin，包括 Python 3.10、AI2-THOR 5.0.0、NumPy 1.23.5 和 OpenCV 4.8.1.78。

在 Unity 启动前，运行一次不带安装参数的图形检查。它要求 `nvidia-smi` 能查询设备、限时 30 秒的 `vulkaninfo --summary` 能枚举 NVIDIA vendor `0x10de`，并验证 EGL/Vulkan loader 可加载及 `cv2` 可导入：

```bash
bash linux_server_operation/33_user_graphics_check.sh
```

如果 `nvidia-smi` 不存在、报错，或者 Vulkan 只看到 llvmpipe/CPU 而没有 NVIDIA GPU，先确认共享服务器是否要求申请 GPU job/交互式 GPU allocation；在获分配的作业 shell 中重试 33。仍失败时停止并把第 00、33 步日志交给服务器管理员检查驱动和 GPU 分配。普通用户不能修复内核驱动或主机 ICD；不要照搬旧机器的 ICD 修改或 root 权限修复步骤。此时不要启动 Unity。

## 导入固定 CloudRendering build 并做 THOR 冒烟检查

把已上传的 ZIP 与官方 sidecar 通过第 13 步工具导入。它会再校验精确文件大小、SHA-256 和 ZIP 内容，安装到数据目录缓存，但不会启动 Unity：

```bash
bash linux_server_operation/13_prepare_thor_build.sh \
  --archive "$HOME/installers/ai2thor/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917.zip" \
  --sha256-file "$HOME/installers/ai2thor/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917.sha256"
```

核对缓存并运行一个场景的短 smoke。只有 33 图形检查和缓存导入都通过后才执行：

```bash
bash linux_server_operation/13_prepare_thor_build.sh --check-cache && \
bash linux_server_operation/03_smoke.sh FloorPlan1
```

Smoke 成功后，可按需运行已有相机探针和当前机制探测流程：

```bash
bash linux_server_operation/16_camera_probe.sh &&
bash linux_server_operation/31_probe_native_mechanisms.sh --max-scenes 2
```

第 31 步是当前独立机制探测，不依赖旧的 stage 30，也不会自动生成旧的 20 对样本。每次生成/探测都应检查输出与失败项；“脚本退出成功”本身不等同于研究样本有效或机制假设成立。

## 可选：单独准备 Qwen 推理环境

THOR 成功后，如需本机运行 Qwen3.5-4B，再确认 `$QWEN_MODEL_DIR` 里包含模型配置、processor 文件和权重。模型目录没有上传时，跳过本节即可继续只用 THOR。模型环境固定安装在 `$QWEN_ENV_PREFIX`，不复制旧机器 Conda 环境，不升级既有 pin，也不与 THOR 图形库环境合并：

```bash
bash linux_server_operation/17_setup_model_env.sh
```

若 17 步的安装进程中断或报告待续，不要再开第二个 pip/Conda 安装；确认原进程已结束后使用已有的 19 步续接脚本：

```bash
bash linux_server_operation/19_continue_model_setup.sh
```

当前固定组合为 torch `2.10.0+cu128`、torchvision `0.25.0+cu128`、Transformers `5.15.0`、Accelerate `1.11.0`、Pillow `11.3.0`。它们沿用已有脚本 pin，不应为了新服务器而升级。CUDA wheel 只提供用户态 PyTorch runtime，不能替代服务器 NVIDIA 驱动；新机器 GPU 型号、驱动版本、CUDA 可用性和显存未知，必须以 17/19 阶段报告为准。若 GPU/CUDA 检查不通过，保留报告，不要尝试无管理员权限升级驱动。检查通过后，再按 `20_model_run.md` 决定是否运行推理；本迁移流程不会自动启动模型推理。

## 可选：迁移已有实验数据

只准备新场景时，无须搬旧数据。若要继续此前的离线评测，把需要的完整导出批次复制到 `$DATA_ROOT/<原批次目录名>/`，包括 `data/input`、`data/media` 和用于核对/验证的 `hidden_gold`、收据与审核文件。公开输入与私有评分目录继续分开；模型只读取公开输入和 RGB。

历史预测、日志、审查报告可单独存到 `$OLD_DATA_ROOT/old_machine_archive/`，不放进 Git，也不必把所有旧日志都放入新运行目录。保留材料里的原始路径和指纹，不批量改 JSON 让旧记录假装是在新主机生成。新代码/机器上的新运行使用新输出目录；是否能 resume 由原有指纹检查决定，不能修改清单绕过检查。

模型目录需包含实际权重及 tokenizer/processor/config 文件；如果复制的是 Hugging Face snapshot 的软链接，还需迁移链接指向的文件或保持完整 cache 结构。THOR 的 Unity 构建按第 13 步从 ZIP 重新导入，不必搬旧主机的 Conda 环境和图形配置。

## 从普通 Linux 迁回 AutoDL 或另一台机器

迁移时搬源码、必要模型权重、需要保留的实验材料和那两个经过验证的 CloudRendering 安装文件。不要搬 `thor_env`、`model_env`、`miniforge3`、pip/conda 缓存或系统驱动文件。目标主机上重新执行 32、33 和 01，以目标主机自己的 NVIDIA 驱动为准；复用同一已校验的官方 THOR ZIP 和 sidecar 即可。

在 AutoDL 新登录 shell 选择 `autodl` profile，并在 AutoDL 实际数据盘上传/保留 CloudRendering 安装文件：

```bash
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample"
mkdir -p "$HOME/.config/thor20"
cat > "$HOME/.config/thor20/server.env" <<'EOF'
unset DATA_ROOT THOR_ENV_PREFIX QWEN_ENV_PREFIX QWEN_MODEL_DIR CONDA_EXE PYTHONPYCACHEPREFIX OLD_DATA_ROOT
export THOR_SERVER_PROFILE=autodl
export SERVER_HOME="$HOME"
# Optional: export DATA_ROOT=/mnt/user-data/idea1_firsttest_20sample
source "$HOME/idea1_verify_all/idea1_firsttest_20sample/linux_server_operation/server_paths.sh"
export THOR_ENV_PREFIX="${THOR_ENV_PREFIX:-$DATA_ROOT/thor_env}"
EOF
source "$HOME/.config/thor20/server.env"
bash linux_server_operation/00_preflight.sh
```

AutoDL 的 `server_paths.sh` profile 应将项目放在 `$HOME/idea1_verify_all/idea1_firsttest_20sample`、数据放在 `$HOME/autodl-tmp/idea1_firsttest_20sample`，模型路径为 `$HOME/autodl-tmp/model/qwen3.5-4b`。之后从 32、33、01 开始按上述顺序准备该主机。不要假定不同 AutoDL 实例仍是原来的 4090；记录实际 `nvidia-smi` 输出和驱动状态。

## 返回已有 AutoDL 环境时可选择复用

上面的 AutoDL 流程针对干净实例，会创建新的 prefix。若回到原来那台机器且命名环境 `thor20`、图形依赖和缓存都还在，可以复用，不必重装 Miniforge/THOR。使用新的登录 shell，只执行以下配置与检查：

```bash
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample"
unset DATA_ROOT QWEN_MODEL_DIR QWEN_ENV_PREFIX OLD_DATA_ROOT THOR_ENV_PREFIX PYTHONPYCACHEPREFIX
export THOR_SERVER_PROFILE=autodl
export SERVER_HOME="$HOME"
export CONDA_ENV=thor20
source linux_server_operation/server_paths.sh
bash linux_server_operation/00_preflight.sh && \
bash linux_server_operation/02_unit_checks.sh && \
bash linux_server_operation/13_prepare_thor_build.sh --check-cache && \
bash linux_server_operation/03_smoke.sh FloorPlan1
```

这里不设置 THOR_ENV_PREFIX，因而使用旧的命名环境。若旧环境或缓存已经不存在，就回到完整迁移流程。不要把新机器生成的 `thor_graphics.env` 复制来替换旧机图形配置；如旧数据根已存在这个文件，先核实它指向的环境仍是本机要使用的那一个。

## 出错时返回哪些材料

不要在失败后继续启动后续阶段。返回 `$DATA_ROOT/logs` 中对应本次执行时间的 00、32、33、01、02、13、03 日志即可；若 Miniforge 安装器自身失败，再附 32 提示的 installer 日志。图形失败附同一目录的 `*_vulkaninfo.txt`。模型部分附 17/19 的报告与日志。不同阶段不要求全部执行，保留实际失败的那一步足以继续定位。

## 官方依据与历史证据

- conda-forge 官方 Miniforge release 与版本化 installer / `.sha256` sidecar：<https://github.com/conda-forge/miniforge/releases/tag/26.7.2-1>。官方安装说明支持 `bash installer -b -p PREFIX`，其中 `-b` 是非交互安装且不执行 shell 初始化：<https://github.com/conda-forge/miniforge>。
- AI2-THOR 官方文档说明 `CloudRendering` 用于无屏幕 headless 初始化，首次 Controller 会下载 Unity build 到本地缓存：<https://ai2thor.allenai.org/ithor/documentation/>。
- conda-forge 官方包页确认 `vulkan-tools`、`libvulkan-loader`、`libegl`、`libgl` 与 `libglvnd` 包名及 Linux 64 位可用性：<https://anaconda.org/conda-forge/vulkan-tools>、<https://anaconda.org/conda-forge/libvulkan-loader>、<https://anaconda.org/conda-forge/libegl>、<https://anaconda.org/conda-forge/libgl>、<https://anaconda.org/conda-forge/libglvnd>。conda-forge 文档记录 OpenCV 类软件常见的 `libGL.so.1` 缺失与 OpenGL provider 需求：<https://conda-forge.org/docs/maintainer/maintainer_faq/>。
- PyTorch 官方历史版本页提供对应的 CUDA 12.8 wheel 版本组合依据：<https://pytorch.org/get-started/previous-versions/>。项目已有 17/19 步脚本锁定具体组合，迁移时沿用这些 pin。
- 本项目先前第 11/12 步日志记录过 `libEGL` 初始化缺失，第 13 步日志记录过官方 ZIP 导入校验成功、SHA-256 为 `1fd5f998644a6dd522a4cf6604c05360a75a5c27f450a7486c20e52dc2b67bb9`，随后固定 CloudRendering 冒烟启动成功。旧机器上的 repair 步骤包含特定环境修复，不属于普通用户迁移流程，也不应在新主机上照搬。

这些步骤在 Windows checkout 中只写入文件；新服务器实际安装、驱动兼容性、Vulkan enumeration、Unity smoke 和模型检查都需要在目标 Linux 主机上执行并保留日志，不能由本地静态修改推断为已通过。
