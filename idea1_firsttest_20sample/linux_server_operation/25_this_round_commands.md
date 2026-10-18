# 本轮结论与继续操作

## 已确认

- 新取景检查通过，40 项单元测试通过。
- 20 组中发布了 14 组、28 条候选，6 组没有构造出来。已有候选不用重新生成。
- 19 的 `runtime_check_incomplete` 和 22 的 traceback 均明确指向缺少 torchvision。22 在处理器初始化时退出，尚未加载权重或生成答案，所以目前没有模型更新过多/不足的证据。
- 这是安装脚本漏依赖。现已给 17/19 补上与 torch 2.10.0/cu128 匹配的 torchvision 0.25.0+cu128；本轮继续使用 19，不重新安装 THOR 或驱动。
- 本地尚未收到新候选数据 ZIP，因此 28 条记录还不能逐帧、逐状态验收。不要用旧的三目标相机 ZIP 代替新数据包。

## 同步代码后执行

在服务器执行以下命令。前面任一步失败，就不继续启动后面的推理。

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
export DATA_ROOT=/root/autodl-tmp/idea1_firsttest_20sample
bash linux_server_operation/19_continue_model_setup.sh && \
bash linux_server_operation/22_smoke_latest_candidates.sh && \
bash linux_server_operation/20_run_model.sh \
  --export-root /root/autodl-tmp/idea1_firsttest_20sample/exports_scope_v2_20261018T101136Z_wHG53v \
  --all --debug-unreviewed
```

22 先做单条试跑；成功后，20 对本批已有的 28 条候选做初步筛查。两次运行各有独立输出目录，不覆盖失败记录。`--debug-unreviewed` 表明这些预测用于定位候选问题；须在数据验收后才能解释为模型能力结果。运行结束只意味着请求结束，仍需检查回答格式、缺题和实际正确性。

不需要重新运行 21。若 19 报 active-install pending，等原安装结束再重跑；若报告其他失败，保留日志，不跳过检查强行评分。

无论上面的执行成功还是失败，再单独执行收集命令：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample
bash linux_server_operation/24_collect_current_audit.sh \
  --export-root /root/autodl-tmp/idea1_firsttest_20sample/exports_scope_v2_20261018T101136Z_wHG53v
```

24 只收集现有结果，不启动模型、仿真或安装。它把本批生成 ZIP、相机检查包、19 报告和日志、20/22 日志及最新模型原始输出放进一个总 ZIP，并记录缺失文件、预测行数和运行状态。最终总包放在 `$DATA_ROOT/logs/`，终端会打印具体路径。

请将该总包复制到本轮 Windows operation_data 目录，下一轮即可同时检查实际状态/画面与模型答案。总包内含隐藏评分证据，只供本次审查，不能作为模型输入。

本轮修改仅做静态审阅，未在 Windows 执行任何项目代码或安装。
