# 第 10 步：只读诊断 NVIDIA Vulkan ICD

**该服务器的最新结果：** `20261017T172728Z/diagnosis_report.json` 确认 `libGLX_nvidia.so.0` 指向真实 580.105.08 ELF，`ldd` 没有未找到的依赖，且同版本 gpucomp 已映射到进程。环境覆盖为空；清理环境和私有绝对路径 ICD 均失败，接口协商返回 `-3`。不要重复本页测试，改执行 [第 11 步初始化跟踪](11_vulkan_init_trace.md)。这仍不证明全部运行时依赖完整，也不证明 595 空文件是根因。

最新的第 09 步日志显示：宿主 NVIDIA 驱动为 580.105.08，Vulkan loader 已可加载，`nvidia-smi` 可看到 RTX 4090，系统注册了 580 系列 graphics 库，但 `vulkaninfo` 无法通过 `vk_icdGetInstanceProcAddr` 取得 `vkCreateInstance`。日志还提示大量 595.71.05 库文件为零字节。零字节文件是需要追查的线索，单凭它不能断定本次 ICD 失败的根因。

## 只运行诊断

先将本次代码同步到服务器，然后运行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && \
bash linux_server_operation/10_diagnose_nvidia_icd.sh
```

脚本只读取 ICD manifest、驱动和动态库信息；只在外部数据目录写诊断材料。它不会运行 Unity/AI2-THOR、安装系统包、改 `/etc`、改系统符号链接或安装驱动。每个 `vulkaninfo`、ctypes 探测都是独立超时子进程，单个探测崩溃或超时不会跳过其它探测。

脚本检查实际 ICD JSON 和选择性 Vulkan/动态加载器环境变量；跟踪 `libGLX_nvidia.so.0` 的符号链接、文件大小、ELF 头和 `ldd`，并收集与宿主版本有关的 `libnvidia-gpucomp` 依赖证据。ctypes 子进程按 Vulkan ICD ABI 先协商 loader 接口版本（若该符号导出），再查询 `vkCreateInstance`，并记录自身 `/proc/self/maps`。随后分别比较当前环境、清除脚本记录的 `VK_*`/`LD_*` 覆盖后的 `vulkaninfo --summary`。

只有找到真实 NVIDIA ICD manifest、非零 ELF GLX 库且库版本与当前宿主驱动匹配，脚本才会在 `$DATA_ROOT/vulkan_diagnosis/<时间戳>/` 写一份私有 ICD。该文件只把来源 manifest 中的 `ICD.library_path` 改成真实 GLX 库的绝对路径，并用 `VK_ICD_FILENAMES` 在独立子进程中测试。系统配置不变。

最终成功只认 `vulkaninfo` 实际枚举出 vendor ID `0x10de` 且设备名称包含 NVIDIA 的 GPU，并且命令退出码为 0。ctypes 成功、loader 存在或 `nvidia-smi` 可用都不单独算成功；枚举成功仍不证明 Unity 或 AI2-THOR 能启动。

诊断文件和当前第 10 步日志会尝试合并成 Git 外的单个 `.tar.gz`，位置会在终端打印。如果压缩工具不可用或压缩失败，直接上传终端所列诊断目录和阶段日志。若某个变体成功枚举 NVIDIA GPU，目录会包含 `retry_smoke.sh`，选择 baseline、清理覆盖或私有 ICD 中已成功的配置。确认后可手动执行 `bash /root/will_not_be_push_to_git/idea1_firsttest_20sample/vulkan_diagnosis/<时间戳>/retry_smoke.sh`；诊断脚本不会运行它。

该试启动脚本复用诊断所用的 `thor20` Python、输出路径和已成功的库选择配置，执行与第 03 步相同的 `probe.py`。它直接调用该环境的 Python，避免再次激活环境时重新加入被清除的库路径；执行日志仍写入 Git 外的 `logs`。
