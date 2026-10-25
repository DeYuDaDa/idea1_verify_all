# 第 36 步预检测试样例修复后重跑

适用日志：`20261025T032512Z_31_probe_native_mechanisms.log`。

本次停止于 `test_sink_groups_fixture_contents_and_fixture_detail`。测试原先
给 Faucet 提供了包围盒，却要求返回“缺包围盒、使用位置回退”。修复测试数据：
先不提供 Faucet 包围盒验证回退，再补回包围盒验证正常规划。没有修改规划算法，
没有放宽断言，也没有修改 Conda 初始化或查找逻辑。

该日志中前一组 10 项测试通过，相机规划的 8 项测试中 7 项通过、1 项失败；
后续相机运行封装与嵌套搭建测试尚未执行，Unity 尚未启动，没有本轮新图片。

先将修订后的源码同步到 Linux 服务器，特别是 `tests/test_view_planning.py`。
沿用当前可工作的 shell 配置（用户已注释 `.bashrc` 中的 Conda 初始化段）。
不需要重新安装环境或重做第 32、33 步。

```bash
source "$HOME/.config/thor20/server.env" &&
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample" &&
bash linux_server_operation/36_recheck_views_and_nested.sh
```

第 36 步会调用第 31 步，先重新执行全部相关预检测试；全部通过后才启动
8 种设计 × 2 个房间的 16 次机制尝试。运行日志名称仍包含
`31_probe_native_mechanisms`，这是正常的内部调用。每次实验另建输出目录，
不覆盖旧结果。若后续测试出现新的失败，保留新的阶段日志即可；尚未通过的
测试不能视为本次已经验证。

Windows 端只完成代码修订和静态差异检查；Python 测试结果以 Linux 重跑为准。
