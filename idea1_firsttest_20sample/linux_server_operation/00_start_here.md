# 首次运行说明（Linux 服务器）

此文档中的命令只在服务器执行。先把代码同步到 `/root/idea1_verify_all/idea1_firsttest_20sample`，并确认测试文件已经由负责的开发者提交且完成 review。Windows 机器只用于编辑代码。

默认路径如下：

- 项目：`/root/idea1_verify_all/idea1_firsttest_20sample`
- 不推送到 Git 的输出：`/root/will_not_be_push_to_git/idea1_firsttest_20sample`
- 数据集导出目录：`/root/will_not_be_push_to_git/idea1_firsttest_20sample/exports`

首次建议只运行预检、环境、单元检查和 smoke。下面是一条连续命令：任一阶段失败时，`&&` 会停止后续阶段。复制后在服务器终端执行：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && \
bash linux_server_operation/00_preflight.sh && \
bash linux_server_operation/01_setup_env.sh && \
bash linux_server_operation/02_unit_checks.sh && \
bash linux_server_operation/03_smoke.sh FloorPlan1
```

如 Conda 不在 PATH 或常见安装路径，可把 `CONDA_EXE=/绝对路径/conda` 加在具体命令前。若使用其他环境名或输出路径，也可在命令前设置 `CONDA_ENV=...`、`DATA_ROOT=...`；CloudRendering 默认值为 `THOR_PLATFORM`。每阶段的日志和预检机器报告都会写到 `$DATA_ROOT/logs`，默认位于上述 Git 外输出目录。

首轮 smoke 只启动一个场景探针，结果写入 `$DATA_ROOT/smoke`。如果它成功，再单独执行 `04_generate_pilot.sh` 生成六个指定 pair；检查并严格验证 pilot 后，再自行决定是否执行耗时更长的 `05_generate_all.sh`。不要把 pilot 或全量生成与首次预检命令合并。

若首轮任一阶段失败，查看该阶段日志并只重跑修复后的阶段。预检报告不会写入环境变量或凭据。
