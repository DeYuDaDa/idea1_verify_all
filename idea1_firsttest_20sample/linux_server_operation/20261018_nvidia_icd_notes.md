# NVIDIA ICD 故障：证据与下一步

依据服务器上传的 `20261017T164735Z_09_fix_vulkan.log` 和同时间戳 `vulkan_summary.txt`：

- `libvulkan1`、`vulkan-tools` 安装成功；同一个 Conda 环境能加载 `libvulkan.so.1`。
- `nvidia-smi` 显示 RTX 4090、驱动版本 `580.105.08`。
- 系统登记了部分 `580.105.08` 图形库，但同时有大量 `595.71.05` 的零字节库文件。
- Vulkan loader 尝试通过 `libGLX_nvidia.so.0` 的 `vk_icdGetInstanceProcAddr` 获取 `vkCreateInstance` 失败。Unity 尚未启动。

这些信息将故障定位到 NVIDIA ICD / 用户态图形库加载这一层。它们还不能证明：空的 595 文件被实际加载、580 库本身损坏，或宿主机内核驱动需要重装。

## 为什么第 10 步这样检查

Khronos 的 ICD 接口要求驱动提供 `vk_icdGetInstanceProcAddr`，并返回包括 `vkCreateInstance` 在内的入口。错误说明入口获取失败，但不能单凭一句报错区分库路径错误、依赖缺失、错误版本或容器挂载不完整。需要同时看实际 manifest、符号链接终点、ELF 内容、依赖以及子进程实际加载的库。

NVIDIA 的容器组件列表中，`libnvidia-gpucomp.so` 用于 D3D/Vulkan/OpenGL/光线追踪的 shader 编译，`libnvidia-glvkspirv.so` 是 Vulkan SPIR-V 库。因此检查这些组件有依据；它们是否是本机缺失依赖，仍以本机真实 ELF 和加载日志为准，不能预先下结论。

第 10 步的私有 ICD 仅将已有 manifest 的库路径改为已发现、与宿主版本匹配的真实非空 ELF，供单个子进程隔离测试。它不修改系统 manifest 或符号链接，也不替换驱动实现。环境覆盖清理也仅作用于测试子进程。成功标准仍是 `vulkaninfo` 实际枚举 NVIDIA 设备。

## 官方依据

- [AI2-THOR 5.0.0 平台检查源码](https://github.com/allenai/ai2thor/blob/5.0.0/ai2thor/platform.py)：`CloudRendering.validate()` 只检查 loader 是否可发现；无法判断本次 ICD 初始化是否成功。
- [Khronos Vulkan loader / ICD 接口](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md)：manifest 库路径、入口查询与接口协商。
- [NVIDIA 容器库组件清单](https://github.com/NVIDIA/libnvidia-container/blob/main/src/nvc_info.c)：图形库、SPIR-V 和 GPU shader compiler 的用途。
- [NVIDIA 容器能力配置](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html)：Vulkan 所需的 graphics 能力与 nvidia-smi 的 utility 能力不同；容器里能看到 GPU 不等于图形接口完整。

若诊断确认所需的同版本图形库缺失，下一步才考虑恢复平台的 graphics 库注入，或在私有目录验证匹配版本的用户态库。不在当前证据不足时安装 NVIDIA 内核驱动、重建 Python 环境或混用其它版本的图形库。
