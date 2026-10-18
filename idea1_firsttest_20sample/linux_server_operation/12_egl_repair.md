# 第 12 步：补齐 EGL loader 并验证 NVIDIA Vulkan

**该服务器已执行完成系统修复：** `20261018T042328Z` 日志确认 EGL 能加载，`vulkaninfo` 退出 0 并枚举 NVIDIA RTX 4090。后续失败是第 03 步从网络下载约 797 MiB 构建包时连接中断，不是 EGL 或 Vulkan 再次失败。请转到 [第 13 步构建包准备](13_thor_build.md)，不重复本页安装流程。新版第 03 步会先检查本地缓存，避免隐式进入长时间下载。

第 11 步发现 NVIDIA GLX 初始化缺少 `libEGL.so.1`，其余已检查的 580 图形库与 `gpucomp` 可加载。Ubuntu Jammy 的 `libegl1` 提供这个 loader，并会安装包管理器声明的必需依赖（包括 Mesa EGL）；这不等于安装 NVIDIA 驱动。参考 [Ubuntu libegl1 文件列表](https://packages.ubuntu.com/jammy/amd64/libegl1/filelist) 和 [libegl1 依赖信息](https://packages.ubuntu.com/jammy/amd64/libegl1)。

同步代码后，在服务器执行推荐命令：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && \
bash linux_server_operation/12_fix_egl.sh --smoke
```

脚本先用 `thor20` 检查 `find_library("EGL")` 和 `CDLL("libEGL.so.1")`。缺失时会模拟 `apt-get install --no-install-recommends libegl1`，把计划写到外部目录；计划有任何移除项或 NVIDIA 驱动相关改动就停止。通过后仅请求安装 `libegl1` 及包管理器必需依赖，不运行 `apt update`，只用 root 或免密 sudo。`--check-only` 可跳过安装，只执行 EGL/Vulkan 核验。

安装后只有基线 `vulkaninfo --summary` 退出码为 0、vendor ID 为 `0x10de` 且设备名含 NVIDIA 才算 GPU Vulkan 验证成功。基线失败时脚本会额外采集一次 `LD_DEBUG=libs,files`，但这次仅用于诊断，不能将基线失败改判为成功。脚本也会收集现有 EGL vendor JSON 和 `libEGL_nvidia.so.0` 的解析/依赖信息。`--smoke` 仅在基线 NVIDIA Vulkan 枚举成功后运行既有 `03_smoke.sh FloorPlan1`；该 smoke 可能按 AI2-THOR 既有行为下载 CloudRendering build，且会实际启动 Unity。它失败时脚本仍保存 stdout、退出码和本阶段新生成的 smoke JSON/图像，并打包证据。Unity Player.log 不包含在本包中；若需进一步定位下载或 Unity 启动失败，请按 smoke 输出中的路径另行收集该日志。

所有输出位于 `/root/will_not_be_push_to_git/idea1_firsttest_20sample/egl_repair/<时间戳>/`，脚本会打印外部 `.tar.gz` 路径。它不请求更换 glibc 或 NVIDIA 驱动，不手工重写驱动链接；EGL 包自身的文件和链接由 apt 管理。即使日志中出现 `__malloc_hook` 的 `fatal` 字样，也不要据此修改系统库。当前已证实缺少 EGL，但补齐后是否还有后续阻塞，仍由本次验证确定。
