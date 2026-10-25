# 修复嵌套角色登记后重跑第 36 步

对应日志：`20261025T035023Z_31_probe_native_mechanisms.log`。

已通过：机制基础测试 10 项、视角规划测试 8 项、相机封装测试 4 项。
嵌套搭建测试 3 项中 1 项通过，2 项在读取角色表时触发 `KeyError: 'support'`。
失败发生在 Unity 启动和实验输出目录创建之前，因此没有本轮图片或机制 ZIP。

修复：`establish_nested()` 主动登记传入的固定角色，不再依赖调用方预先登记。
换候选而重置场景后，也在重置回调及后续摆放之前恢复固定角色。测试仍从空角色表
开始，并额外检查清空角色表的重置路径；没有通过跳过测试来继续运行。

先将以下修订同步到服务器：

- `nested_setup.py`
- `tests/test_nested_setup.py`
- `linux_server_operation/31_probe_native_mechanisms.sh`

继续沿用当前可工作的 Conda 配置，不需要安装、重建或修改初始化。

```bash
source "$HOME/.config/thor20/server.env" &&
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample" &&
bash linux_server_operation/36_recheck_views_and_nested.sh
```

先执行四组相关测试，全部通过后才进入 16 次机制尝试。实验结束后会打印
`Probe root:`、`Bundle:` 和 `Execution status:`；ZIP 位于 `$DATA_ROOT/logs/`。
若预检仍失败，日志会明确提示 Unity 尚未启动、没有新机制 ZIP。

Windows 端只进行了修订和静态检查；Python 测试与原生机制结果以 Linux 重跑为准。
