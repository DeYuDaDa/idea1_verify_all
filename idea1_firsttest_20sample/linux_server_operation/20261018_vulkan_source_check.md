# AI2-THOR 5.0.0 CloudRendering / Vulkan 日志核查

核查对象：主代理日志中初始化已进入 `find_build`，CloudRendering 平台校验失败，错误为 `Vulkan API driver missing. requires libvulkan1`。本文件只做官方源码与官方容器资料核对；没有运行 Python、模拟器、测试或安装操作。

## 诊断结论

AI2-THOR 5.0.0 的 `CloudRendering.validate()` **只检查动态链接器能否通过 `ctypes.util.find_library("vulkan")` 找到 Vulkan loader library**。查找成功就返回通过；失败就返回字符串 `Vulkan API driver missing.`。它没有查看 NVIDIA GPU、NVIDIA ICD JSON、`nvidia-smi`、Vulkan 物理设备，也没有尝试创建 Vulkan instance。

因此，这条日志**不能推出宿主 GPU 驱动坏了**。它能证明的只有：当前 Python 运行环境的动态库查找没有发现名为 `vulkan` 的 loader。若 `libvulkan1` 尚未装入当前容器，这正是最直接解释。报错文字把 loader 缺失称作 driver missing，措辞比实际检查范围更宽。

官方 `dependency_instructions()` 对 CloudRendering 明确建议 Ubuntu 安装 `libvulkan1`。官方 Dockerfile 也将 `libvulkan1` 列入 apt 安装包；它没有把 Vulkan ICD/GPU runtime 一并通过这个包解决。`vulkan-tools` 提供 `vulkaninfo`，属于下一阶段诊断工具，不是 `validate()` 的依赖，也不是该错误本身要求的包。

## 分层修复与诊断边界

1. **先补容器用户态 loader：** 在容器 Ubuntu 环境安装 `libvulkan1`；若后续要运行 `vulkaninfo`，另装 `vulkan-tools`。之后重跑与原来相同的 AI2-THOR build/platform 检查。这一步只解决 `find_library("vulkan")` 检查，不证明 GPU Vulkan 已正常。
2. **loader 找得到后，再验证 Vulkan driver/ICD：** 查看 `vulkaninfo --summary` 是否能创建 Vulkan instance、枚举实际 GPU。若出现 `ERROR_INCOMPATIBLE_DRIVER`、找不到 ICD、无 physical device，或者容器内没有 GPU-specific ICD 配置/相应用户态图形库，故障范围就转为 NVIDIA 宿主驱动 / 容器 GPU 注入 / graphics driver capability / ICD 可见性；这时不能再用 `libvulkan1` 安装成功来宣称 CloudRendering 可用。
3. **核实 Docker/NVIDIA GPU 注入：** 容器需实际获得宿主 NVIDIA 设备与图形用户态库。NVIDIA Container Toolkit 文档规定 Vulkan/OpenGL/EGL 需要 `NVIDIA_DRIVER_CAPABILITIES=graphics`；`nvidia-smi`/NVML 需要 `utility`。对无显示器的 CloudRendering，通常需要 `graphics,utility`；需要 X11/Wayland display 时再加 `display`。该变量会替换默认 capability 列表，不能只增加其中一项。NVIDIA CUDA 基础镜像的默认 capability 是 `compute,utility`，因此能看到 `nvidia-smi` 或能跑 CUDA 不等于容器已注入 Vulkan graphics 库。
4. **驱动归宿：** NVIDIA kernel driver 属于宿主机/云平台节点，不应在普通容器里安装内核模块。容器应该由受支持的 NVIDIA runtime/Container Toolkit 注入兼容的驱动用户态库、设备节点及 ICD 信息。若宿主/平台未配置 GPU 或未向容器注入 graphics/Vulkan 组件，应由宿主管理员或容器启动配置修复；不要靠在容器里装 `nvidia-driver`/伪造 `nvidia_icd.json` 来掩盖问题。
5. **不要用环境变量伪装挂载：** 不要将 `VK_ICD_FILENAMES` 指向不存在或手工拼出的 ICD JSON，也不要 export 一个路径来假装设备/库已挂入。只有当诊断确认有一个真实、有效、与已注入 driver 匹配的 ICD 文件时，才考虑为 Vulkan loader 指定该文件；这不是当前 loader 缺失错误的修复。
6. **再往后才是 Unity player：** 若 loader 可发现、`vulkaninfo` 可实际枚举 GPU，但 AI2-THOR CloudRendering Unity player 仍退出，才检查 AI2-THOR `Player.log`、GPU 型号/driver 兼容、容器挂载路径和 Unity Vulkan 初始化日志。那是比当前 `validate()` 报错更后面的故障阶段。

## 本机日志可支持与不能支持的陈述

| 观察 | 可下结论 | 不能据此下结论 |
|---|---|---|
| `CloudRendering.validate()` 报 `Vulkan API driver missing` | Python 的 `find_library("vulkan")` 没找到 Vulkan loader。 | NVIDIA 宿主 driver 已坏、GPU 不存在或 ICD 一定损坏。 |
| 安装 `libvulkan1` 后 validate 通过 | Loader library 现在可被动态库查找找到。 | Vulkan instance 能创建、GPU ICD 被注入、Unity player 能运行。 |
| 容器内 `nvidia-smi` 成功 | NVIDIA utility/NVML 路径可用且至少有设备被 runtime 暴露。 | graphics capability/ICD/Vulkan 可用。 |
| `vulkaninfo --summary` 成功并列出 NVIDIA GPU | Vulkan loader 能通过 ICD 枚举 GPU。 | Unity/AI2-THOR 5.0.0 一定能启动；仍须实际看 player 日志。 |

主代理可让 repair/diagnostic 工具按以上阶段分别给结果，例如 `loader_missing`、`loader_found_vulkan_unverified`、`vulkan_icd_or_device_failed`、`vulkan_gpu_enumerated_unity_unverified`、`player_started`，不要把单一 `validate()` 结果记录成 GPU/运行成功的 truth。

## 官方来源

- AI2-THOR 5.0.0 `platform.py`：CloudRendering.validate、依赖提示与 Linux GLX 检查。https://github.com/allenai/ai2thor/blob/5.0.0/ai2thor/platform.py
- AI2-THOR 5.0.0 `controller.py`：CloudRendering 下指定 `gpu_device` 时会调用 `vulkaninfo` 与 `nvidia-smi` 做设备映射；Vulkan 初始化后 Unity 立即退出时报告 Player.log。https://github.com/allenai/ai2thor/blob/5.0.0/ai2thor/controller.py
- AI2-THOR 官方 Dockerfile：安装 `libvulkan1`，使用 NVIDIA CUDA Ubuntu 镜像并预下载 CloudRendering build。https://github.com/allenai/ai2thor-docker/blob/main/Dockerfile
- AI2-THOR 官方 Docker README：运行 3D 渲染需宿主 NVIDIA GPU。https://github.com/allenai/ai2thor-docker/blob/main/README.md
- AI2-THOR 官方 Docker `install_nvidia.sh`：读取宿主 `/proc/driver/nvidia/version`，安装对应用户态驱动且传 `--no-kernel-module`；这说明其容器逻辑不是在容器里装 kernel module。https://github.com/allenai/ai2thor-docker/blob/main/scripts/install_nvidia.sh
- NVIDIA Container Toolkit Docker capability 说明：`graphics` 用于 OpenGL/EGL/Vulkan，`utility` 用于 nvidia-smi/NVML，`display` 用于 X11/Wayland 且隐含 graphics，默认 capability 为 compute,utility。https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html
- NVIDIA Container Toolkit release note：在 graphics/display capability 下支持容器化 headless Vulkan，包括 Vulkan ICD loader 和 direct rendering devices 注入。https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/1.12.0/release-notes.html

以上结论用于区分 loader 检查和 GPU/ICD 运行检查；是否已安装 `libvulkan1`、NVIDIA ICD 或 Vulkan 可枚举设备，必须由当前容器自身的只读诊断结果确认。
