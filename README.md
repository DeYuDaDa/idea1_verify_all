# 主线 1：场景事实更新实验

当前工作：在事件发生后，检查模型是否只改变应改变的事实，并保留仍有效的事实。代码位于 `idea1_firsttest_20sample/`。

## 2026-10-23 服务器迁移

当前目标是普通 Linux 服务器，用户目录 `/home/mdy`，没有 root 权限，也尚未安装 Conda。之前的 AutoDL 环境位于 `/root`。新服务器的硬件、驱动和运行结果需重新确认，旧机器成功日志不代表新机器已经可用。

**从 [无 root 权限迁移文档](idea1_firsttest_20sample/linux_server_operation/32_user_server_migration.md) 开始，按文档分段依次执行。** 文档覆盖上传目录、用户级 Conda、图形依赖检查、已有 AI2-THOR ZIP 校验导入、真实启动、测试，以及可选的离线模型环境。

| 用途 | 新普通服务器 | 原 AutoDL |
|---|---|---|
| Git 根目录 | `/home/mdy/idea1_verify_all` | `/root/idea1_verify_all` |
| 实验代码 | `/home/mdy/idea1_verify_all/idea1_firsttest_20sample` | `/root/idea1_verify_all/idea1_firsttest_20sample` |
| 新数据、日志、Unity 缓存、模型环境 | `/home/mdy/experiment_data/idea1_firsttest_20sample` | `/root/autodl-tmp/idea1_firsttest_20sample` |
| 本地模型（可选上传） | `/home/mdy/model/qwen3.5-4b` | `/root/autodl-tmp/model/qwen3.5-4b` |
| 待导入 THOR ZIP 和匹配的 SHA-256 文件 | `/home/mdy/installers/ai2thor` | `/root/installers/ai2thor` |
| 旧材料可选落点 | `/home/mdy/will_not_be_push_to_git` | `/root/will_not_be_push_to_git` |

`linux_server_operation/server_paths.sh` 统一选择路径：`THOR_SERVER_PROFILE=home` 或 `autodl`，默认 `auto`。已有 `DATA_ROOT`、`QWEN_MODEL_DIR` 等显式配置优先，因此可把大文件改放到其他可写数据盘。切换机器时按迁移文档重新加载本机配置，不修改源代码中的用户目录，不修改 HOME。

Windows 仍只编辑代码、检查已有日志和管理 Git，不运行项目 Python、测试、模拟器或安装环境。Windows 不进 Git 的材料继续放在 `F:/md/Academic/ICML2026 paper/主线1/will_not_be_push_to_git`。

迁移不应重放旧机器的系统修复。特别是阶段 09/12 的 apt 修复与阶段 11 的可选 strace 安装，不属于新服务器的无 root 部署流程。新机器缺少 NVIDIA 驱动或设备访问权限时，应由管理员处理；用户环境只能安装用户态依赖。

## 继续实验

部署并通过本机检查后，按 [实验说明](idea1_firsttest_20sample/README.md) 和 [机制探测流程](idea1_firsttest_20sample/linux_server_operation/31_机制探测与困难组.md) 继续。迁移流程不自动生成新数据，不覆盖旧证据，不启动全量模型评测。

已有 RGB、公开问题和隐藏评分证据可以迁移后离线评测，无需同时运行模拟器。只有重新生成场景或让模型实时执行动作时才需要 AI2-THOR。