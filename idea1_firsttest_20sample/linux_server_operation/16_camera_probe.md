# 第 16 步：三场景相机校准探针

本步只校准观察姿态，不生成样本、不读取 hidden gold、不启动模型推理，也不安装依赖。脚本在一个 AI2-THOR Controller 中依次处理 FloorPlan5 的 CoffeeMachine、FloorPlan201 的 Laptop、FloorPlan9 的 Microwave；每个场景会重置到初始状态。Laptop 和 Microwave 若报告 `openable=True` 且当前关闭，会先记录并执行开门 setup，以匹配已检查的观察条件。

每个目标保存原生 `GetInteractablePoses` 首姿态下的 RGB 和 instance mask，以及根据真实 `cameraPosition - agent.position` 高度差、目标 `axisAlignedBoundingBox.center` 重新计算 yaw/horizon 后的 RGB 和 mask。随后调用真正的 `Interactions.look`，另存 validated RGB/mask 和目标框，并在结果中记录 pass/fail。目标框取自 rendered instance detections，若不可用再从 instance mask 计算；metadata 的 `visible` 字段不作为画面可见证明。每场景 `metadata.json` 记录目标、agent/camera metadata、各阶段 bbox、错误和耗时，并有 `action_log.json`；总 `manifest.json` 汇总三场景状态和总耗时。场景失败会记录后继续下一场景，最终以非零退出码报告失败。

## 运行

先完成第 15 步的数据盘准备。第 16 步先调用第 13 步 helper 对 `/root/autodl-tmp/idea1_firsttest_20sample/unity_cache` 做本地 cache 检查，再显式将该目录交给 Controller；cache 无效时不会启动 Unity，也不会隐式下载，而会写出三场景 preflight failure manifest。即使 cache 检查或 probe 失败，也会打包本步脚本、文档、操作日志和已有探针产物，以便诊断。服务器上执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
bash linux_server_operation/16_camera_probe.sh
```

默认 DATA_ROOT 为 `/root/autodl-tmp/idea1_firsttest_20sample`，输出写到 `camera_probe/<UTC时间戳>/`，打包探针脚本、runtime/interactions 源码、相机单测、16 步脚本/说明、当前操作日志及本次输出到 `logs/<UTC时间戳>_camera_probe_bundle.zip`。脚本使用 Python 标准库打包，不依赖系统 `zip`。脚本不会改 `HOME`。

这是实际模拟器探针，需在 Linux server 的既有 `thor20` 环境和已准备的 THOR build 下运行。它串行使用一个 Controller，不并发启动多个 Unity。`look` 的原生姿态候选会按 XYZ 去重，最多尝试 4 个不同位置。

## 不启动模拟器的单元检查

代码提交前可在 Linux server 环境执行项目现有检查脚本：

```bash
bash linux_server_operation/02_unit_checks.sh
```

该脚本只编译 Python 并运行 unittest discovery；`runtime.py` 在 import 阶段不会导入 ai2thor，`tests/test_camera.py` 使用伪造 metadata/可达点检查相机偏移和 AABB 中心几何。Windows 工作区不运行项目或测试，本次只做静态审阅。

## 解释限制

单次 probe 只能显示这三个初始场景中的相机几何表现。`look` 在运行时最多尝试 4 个原生姿态位置，并在每个位置重新计算朝向；只有真实渲染检测/实例 mask 给出非微小且未贴边的目标框才返回成功。若都失败会明确抛错，不把 `visible=True` 当作观察成功。微波炉开门 setup 会改变该场景本次探针的状态，因此该帧不能代表关门初始场景。
