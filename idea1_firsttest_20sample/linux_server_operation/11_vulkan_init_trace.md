# 第 11 步：Vulkan 初始化取证

**本机结果已收齐：** `20261018T041434Z` 的两份 loader 日志和 strace 均记录 NVIDIA 图形库动态加载 `libEGL.so.1`，各系统路径全部 ENOENT；未记录 GPU 设备访问。580 GLX、eglcore、glvkspirv 均是非空 ELF，常规依赖解析成功。下一步改执行 [第 12 步 EGL 修复](12_egl_repair.md)，不要重复本页跟踪。缺少通用 EGL dispatcher 是已证实的阻塞点；是否还有后续问题，要由修复后的真实枚举和试启动确认。

第 10 步已确认真实 580 GLX、其依赖及 580 `gpucomp` 能加载，且 Vulkan 当前、清理覆盖和私有 ICD 路径均未成功枚举设备；loader 协商返回 `-3`。本阶段收集初始化期间的动态库加载和设备访问线索，不再重复前一阶段的 ICD 变体。

同步代码后，在服务器运行推荐命令：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && \
bash linux_server_operation/11_trace_vulkan_init.sh --install-strace
```

脚本仅在 `strace` 缺失时、且显式传入 `--install-strace` 才尝试安装 `strace` 单个小型系统包；只用 root 或免密 sudo，不运行 `apt update`。安装失败仍继续 `LD_DEBUG=libs,files` 取证。若容器禁止 ptrace，脚本会检测 strace 权限错误并用 LD_DEBUG 单独重跑该探针。每个探针最多 35 秒。不会安装 NVIDIA 驱动、修改系统链接或配置、启动 Unity/AI2-THOR。

结果位于 `/root/will_not_be_push_to_git/idea1_firsttest_20sample/vulkan_init_trace/<时间戳>/`，收集与当前宿主版本匹配的 GLX、`glvkspirv`、`eglcore` 的 ELF/动态段/依赖信息，选择性的 NVIDIA 容器环境变量、`/dev/nvidia*` 和 `/dev/dri/*` 节点元数据，以及两种初始化过程的 loader/syscall 日志。节点清单采集只做 stat 与读写权限检查；初始化探针本身可能尝试打开 GPU 设备，这些尝试正是本次跟踪的对象。节点存在或文件权限允许，不单独证明容器设备访问已获准。

阶段尝试把本目录和自身日志合成一个 `.tar.gz`；请上传终端打印的包路径。压缩失败时上传目录和第 11 步日志。打印“取证完成”只表示材料收集结束，不表示 Vulkan 已修好。
