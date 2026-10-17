# 2026-10-18：第 03 步缺少 Vulkan 库

**最新进展：** 上传的 `20261017T164735Z_09_fix_vulkan.log` 已确认 loader 安装完成且可加载，后续失败在 NVIDIA ICD 初始化。已有该结果的服务器请改用 [第 10 步诊断](10_nvidia_icd_diagnosis.md)，不要重复本页安装命令。以下保留供仍缺少 loader 的机器参考。

已根据上传日志确认：Python 3.10 与 ai2thor 5.0.0 安装完成；服务器的 18 项单元测试通过。第 03 步在 `CloudRendering.validate` 阶段提示 `Vulkan API driver missing`，并要求安装 `libvulkan1`。日志没有证明显卡驱动损坏，也尚未证明 Unity 能启动。

这不是 Python 依赖重装问题。先安装系统 Vulkan loader，再确认容器能实际枚举 NVIDIA Vulkan 设备。脚本只安装 `libvulkan1`、`vulkan-tools`，不重装 CUDA、NVIDIA 内核驱动，不改容器运行参数，也不生成数据。

## 本轮只执行这一段

先将本次代码更新同步到服务器。随后在服务器执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && \
bash linux_server_operation/09_fix_vulkan.sh && \
bash linux_server_operation/03_smoke.sh FloorPlan1
```

这会复用现有 `thor20` 环境，无需重跑 01、02。服务器当前是 root；脚本也支持具备免密 sudo 的非 root 用户。系统包下载失败时会停止，错误保留在当前阶段日志。

## 怎样判断

- 打印 `VULKAN_LOADER_LOADABLE`：Conda 内 Python 能发现和加载 Vulkan 库；不代表显卡图形接口已经可用。
- 打印 `VULKAN_DEVICE_READY`：Vulkan 枚举到了 NVIDIA 设备；仍需第 03 步实际启动 Unity 并保存 RGB。
- 第 03 步成功：检查 Git 外输出的 `smoke/report.json`、`smoke/scene_rgb.png`；当前依然只完成试启动，没有生成 20 组数据。
- `vulkaninfo` 失败或只出现 llvmpipe/lavapipe：继续检查容器暴露的 NVIDIA 图形库/ICD。不要自行在 GPU 容器内安装 NVIDIA 内核驱动，也不要通过跳过 AI2-THOR 校验来假装就绪。

无显示器服务器的 Vulkan 工具可能输出 DISPLAY/XDG 相关提示；脚本以设备枚举的退出状态及 NVIDIA 设备信息判断，不要求创建桌面。

## 需要返回的材料

修复阶段日志、同时间戳的 `*_vulkan_summary.txt`；若修复通过但 smoke 失败，再附新的第 03 步日志。它们都在：

`/root/will_not_be_push_to_git/idea1_firsttest_20sample/logs`

只读重新诊断而不安装系统包时，可以执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
bash linux_server_operation/09_fix_vulkan.sh --check-only
```

本轮修改仅写入代码仓库，未在 Windows 执行安装、诊断脚本或模拟器。上传的 `operation_data` 原文件保留，并加入 Git 忽略规则。
