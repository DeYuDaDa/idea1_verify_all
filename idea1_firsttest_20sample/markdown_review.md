# Markdown 审核材料导出器

`New-MarkdownReview.ps1` 使用 PowerShell 7 和 .NET 标准库，将本地已有的 Mechanism 诊断记录或 Dataset 公开输入整理为可在 Obsidian、Typora 中查看和勾选的 Markdown 审核包。导出只读取来源并在新的输出目录写文件；不会改写来源数据，也不会运行模型、Python、Unity 或安装软件。

## 运行要求

- Windows PowerShell 7（`pwsh`）
- `SourceRoot` 指向符合下面目录约定的现有数据目录
- `OutputRoot` 必须是尚不存在的新目录，且必须位于 `SourceRoot` 之外。若目录已存在，脚本会停止以保护已有审核勾选。

## 命令

在 PowerShell 7 中进入 `New-MarkdownReview.ps1` 所在的实验代码目录后使用下列命令，或将 `-File` 后的脚本名改为绝对路径。这是现有数据到审核材料的文件整理，不运行实验 Python、模拟器或模型。本次审核包已经生成，不需要为本次再次运行；后续批次使用新的 OutputRoot。

本次 Mechanism 审核包：

```powershell
pwsh -NoProfile -File .\New-MarkdownReview.ps1 `
  -SourceRoot 'F:\md\Academic\ICML2026 paper\主线1\will_not_be_push_to_git\operation_data\20261024T085851Z_mechanism_probe_20261024T085851Z_APRo2E_31_mechanisms' `
  -OutputRoot 'F:\md\Academic\ICML2026 paper\主线1\will_not_be_push_to_git\operation_data\审核文档_20261024_机制探测' `
  -Mode Mechanism
```

后续 Dataset 批次（`SourceRoot` 须含 `data/input/*.json` 与其引用的 `data/media/` 图片）：

```powershell
pwsh -NoProfile -File .\New-MarkdownReview.ps1 `
  -SourceRoot 'F:\path\to\reviewed_export' `
  -OutputRoot 'F:\path\to\new_review_folder' `
  -Mode Dataset
```

`-Mode Auto` 可依据 `observations/attempts` 或 `data/input` 自动识别格式。为了方便复用，也可把脚本放在任意工作目录，通过绝对路径调用。

## 输出结构

```text
OutputRoot/
  README.md                # 总索引，没有重复复选框
  manifest.json            # 选定输入文件 SHA-256、模式、项目/问题/图片计数
  items/<stable-id>/
    review.md              # 每个 attempt 或 sample 的审核页
    evidence/               # 原始公开 JSON 或压缩后的诊断台账
  assets/<sha256>.<ext>     # 被引用的 RGB，按内容哈希去重并复核复制哈希
```

Markdown 复选框只出现在对应 item 页：`- [ ] 不通过`，并在其下留有 `原因：`。未勾选只表示尚未拒绝，不能解释为审核通过。图片引用使用相对路径，可随整个输出目录移动。来源中缺失或越界的图片会以红旗标出并计入 manifest。

这些 Markdown 勾选只记录人工意见，不会自动删除数据、改 Gold 或登记正式评测批准。总索引只导航，勾选在对应 item 页维护。`image_ref_count` 是来源中引用数，`copied_image_ref_count` 是实际可复制数；缺图时不要混用。源码版本更新后的新导出有该细分字段，旧审核包无需为补字段而覆盖。

## 内容边界

### Mechanism

每个 `result.json` attempt 生成一页；显示原报告 case、scene、fact、family、状态、错误（如有）、角色绑定、原始检查及全部 capture_index 顺序的 RGB。状态明确标为脚本原报告而非审核结论。完整动作序列复制到 `evidence/actions_by_reset.json` 并从审核页链接；检查与角色绑定另存为精简 `evidence/result_evidence.json`。原 `result.json` 路径用于溯源，不会把整份大型 summary 或 snapshot JSON 复制进输出。

页面明确说明未调用模型、没有正式 `model_input`/`questions`，且图片只是诊断 RGB。F1–F11 对应的问题是审核者核验问题，不是模型原题。case、fact、内部 ID、角色绑定和 simulator metadata 只放在私有审计区。

### Dataset

只枚举 `data/input/*.json` 并逐条展示公开 `model_input` 字段和所有公开 frames；不会读取 `hidden_gold` 或预测答案。逐题呈现公开 question、subject、predicate、answer_mode 和审核勾选项。媒体仅按每条公开 `frames[].path` 精确定位，不扫描其他图片。

页面额外给出当前 `offline_run_qwen.py:build_prompt` 白名单对应的重建请求文本，包含固定回答格式要求（JSON 对象、`unknown`、`not_applicable` 及 `change_status` 的允许值）。它说明 `fact_id` 与路径不会进入模型文本，并明确历史请求原文及 processor chat-template 展开没有保存：展示内容是按当前 runner 重建的文本，不是历史 prompt 原文、exact tokens 或 processor 最终输入。原始公开 JSON 复制到每题 `evidence/public_input.json` 供追溯，不会把其中所有字段都宣称为模型可见内容。

`manifest.json` 的来源 SHA-256 只覆盖本次导出实际使用的记录及其引用图片：Mechanism 的 result/capture/action/RGB 文件，或 Dataset 的 `data/input` JSON 与准确引用的 `data/media` 图片。Dataset 模式不会递归读取 `hidden_gold` 或无关目录来计算哈希。

## 持续审核

完成勾选后保留该输出目录作为审核记录。后续批次使用新的 `OutputRoot` 生成独立审核包；不要对已有输出目录重跑，因为脚本会拒绝覆盖。Obsidian、Typora 可直接打开输出目录中的 `README.md`，再沿索引进入对应审核页。
