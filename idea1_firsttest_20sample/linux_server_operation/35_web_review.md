# 网页审核与后续请求留档

本次本地网页已生成，不需要服务器生成，也不必为审核重跑模型或 THOR。Windows 用 Chrome/Edge 打开 `operation_data/网页审核_20261024/index.html` 即可。使用说明见项目 `web_review.md`。

后续 `offline_run_qwen.py` 会在 predictions.jsonl 每行保存 request_text 与顺序说明；图像仍按对应 source_sha256/media_sha256 定位。它只留档用户文本，不声称保存了 processor 的图片 patch 或 chat-template 展开。错误行留档不证明模型已经完成推理。

本轮只修改源码，没有在 Windows 执行项目 Python。同步代码后，在 Linux 先执行已有 runner 检查（不加载模型）：

```bash
source "$HOME/.config/thor20/server.env" && \
cd "$HOME/idea1_verify_all/idea1_firsttest_20sample" && \
bash linux_server_operation/02_unit_checks.sh
```

后续按原 step 20 正常运行，带回新 predictions.jsonl 可核对 request_text；无需为了旧题补留档而重新跑全量。此前已完成的行在 resume 时不会自动补历史原文。

人工网页验收建议用一个无需正式批准的副本：打开任一题、看原图、点不通过并写原因、切题后返回、刷新、导出 JSON、在另一浏览器打开同一包再恢复。输入框键入不会触发切题快捷键。结束后把验收用意见恢复未审核，或使用单独浏览器配置测试，避免测试意见进入正式审核。浏览器拒绝 file:// 的工具不代表用户的桌面 Chrome/Edge 已验证可用；需要真实打开验收。
