# 本地网页审核

入口是网页包中的 `index.html`，用新版 Chrome 或 Edge 直接打开。不需要安装、Python、Conda、服务器或联网。源码位于 `review_web/`；网页只是读已有文件与记录审核意见，不会运行实验。

本次已经生成：

`F:\md\Academic\ICML2026 paper\主线1\will_not_be_push_to_git\operation_data\网页审核_20261024\index.html`

## 页面上看什么

- 左侧选题；同一 sample 的多个问题分别审核，但完整输入仍包含该次请求的全部问题。
- 正文显示问题、按原顺序的图片、模型文本输入。点击图片看原尺寸。旧批次没保存请求文本时，明确标注按当前 runner 重建，不能称历史原文。
- 默认不显示动作日志、坐标、可见对象列表、模型预测。公开历史和规则如果确实属于输入，则完整保留；不能为了简洁删掉这些决定可答性的前提。
- 参考答案在折叠区。审核“能否答出来”至少需要题目和完整输入；审核“标签对不对”还需核对参考答案。模拟器坐标不是默认必需项，只有在追查标签或拍摄问题时才需要。
- 机制探测虽然没有历史模型调用，仍须有明确的审题材料。新版为每条展示具体中文场景、初态、实际过程/失败点、物理问题草案、实测参考答案及每张截图用途；下方可展开拟提供给模型的完整文本。草案不是历史输入，不要求先运行模型；未完成测量不补写 Gold。原始 result/capture/actions 链接集中在最底部。

## 记录意见

每个问题有未审核、通过、不通过三个状态，可以点常见原因并补充文字。点一个不通过原因会切换为不通过。通过时会清空原因标签，但保留文字备注。缺少原因的不通过可以保存，但页面会提醒补充。

自动保存只写浏览器 localStorage。结束时点击“导出审核结果”，下载带批次标识的 JSON；这是跨设备、换浏览器和向后续分析提供意见的持久文件。浏览器可能在移动网页、更换配置或清理数据后丢失本地状态，不能只依赖自动保存。

“恢复审核”要求当前批次的内容哈希一致、问题键一致；只合并较新的记录，保留本地较新的意见。浏览器保存不可用时会明确提示，当前页内容仍可导出。审核结果不会删除源文件、改 Gold 或自动登记严格评测批准。旧 Markdown 中的勾选不会自动导入网页。

键盘：Alt+左/右切题，Alt+1通过，Alt+2不通过。输入框内不触发这些快捷键。

## 后续数据：直接打开文件夹

正式题在网页里点“打开数据文件夹”，选择含 `data/input/*.json` 和 `data/media/` 的根目录。机制原始目录需要相匹配的 `review_presentation.json` 才能直接导入；若没有，先用下方 `New-WebReview.ps1` 为该批次生成带场景说明的网页包。不能再将只有诊断截图、无具体题意的目录伪装为可审题界面。一次只选一个批次，不选总目录。文件在本地解析，不上传；目录导入不读取 Gold 或模型预测。

文件夹模式没有 Gold，也不会读取旁边的历史 predictions。输入文本按网页所对应的当前 `offline_run_qwen.py:build_prompt` 重建（字段内容对应，不能称历史逐字原文）。若需附上参考答案或运行时原文，使用下面的导出脚本。文件夹模式和打包模式的批次标识分别计算；不要混用两者的审核 JSON。

目录格式是版本化契约，不承诺未来永远不变。新增输入模态、system/多轮消息、帧选取方式或 prompt 协议时，应同步更新适配器；当前只支持项目现有的静态多图单轮请求。截图本身不证明模型 processor 没有缩放，因此像素/patch 层面排查另做。

## 后续数据：生成双击即开的完整网页包

以下命令仅做已有数据的文件整理，可在 Windows 的 PowerShell 7 运行；不涉及实验 Python。OutputRoot 必须是尚不存在、且位于所有 SourceRoot 外的新目录，保护已有审核。

```powershell
pwsh -NoProfile -File .\New-WebReview.ps1 `
  -SourceRoot 'F:\path\to\export' `
  -OutputRoot 'F:\path\to\new_web_review' `
  -IncludeReferenceAnswers
```

`-IncludeReferenceAnswers` 可省略。启用时只输出 `hidden_gold/<输入同名 JSON>.query_targets` 中通过 fact_id 对齐的 expected_answer；不会把完整模拟器状态塞进网页输入，也不会把模型预测显示出来。参考答案仍是待审核标签，不自动成为真值证明。公开输入格式不满足契约时应修适配器，而不是手工伪造 prompt。

多个批次可在 PowerShell 中调用：

```powershell
& .\New-WebReview.ps1 `
  -SourceRoot @('F:\path\batch_A', 'F:\path\batch_B') `
  -BatchName @('批次 A', '批次 B') `
  -OutputRoot 'F:\path\new_review_bundle' `
  -IncludeReferenceAnswers
```

后续 runner 会在每行 predictions 中附带实际传入 `_infer_one` 的 `request_text`（用户文本，不是 chat-template 展开），含错误行时需结合运行状态判断是否完成模型调用。新包可加 `-PredictionsPath 'F:\path\predictions.jsonl'`，脚本核对 sample_id、公开 JSON SHA-256 与有序图片 SHA-256 一致才采用已保存原文。不含 request_text 的旧预测行仍按重建处理。一个 PredictionsPath 用于对应的单个 Dataset 批次；不要把多个同名 sample 的运行合并成一个文件。脚本不展示预测回答。

输出的 `assets/` 按 SHA-256 去重，但页面仍保留每次请求的全部帧及其顺序，不会把相同帧自行删掉。移动网页包应移动整个文件夹。批次标识含来源和展示内容；任何输入/图片/参考答案变化会产生新身份，避免旧意见套到新数据。

现有网页补充具体机制说明，可运行 `Update-WebReviewScenes.ps1 -WebRoot '已有网页包目录'`。它保留旧页面文件副本、原始来源和浏览器旧版审核存储；新版 `scene-v2` 的审核范围包括场景/题意/证据，不能把旧版只看截图的通过自动带入。旧版审核 JSON 会因范围不同被明确拒绝，原文件不受影响。新版没有把模拟器数据宣称成图上可见；每题的参考答案仍需和视觉可答性分别审查。

## 核验边界

本轮在 Windows 执行了 PowerShell 整理、JavaScript 语法检查和图片引用/哈希核对。工具浏览器拒绝打开 file://，所以没有完成真实浏览器点击、刷新持久化、导入导出和布局交互验收。没有运行 Python 测试、模型或模拟器；runner 的保存改动需在 Linux 验证，见 `linux_server_operation/35_web_review.md`。
