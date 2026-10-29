# Frontier 视觉 API 调用与成本核查

**查证时间：2026-10-29（Asia/Shanghai）**  
**范围：** OpenAI、Anthropic Claude、Google Gemini 官方 API 模型目录、图像/视频说明、定价与批处理/缓存文档。只核对资料和估算，没有调用模型、发送样本图像或修改代码。官方页面会滚动更新；以下模型名、价格、限额和可用性均应在真正启动实验当日复查。此报告基于此日期页面可见的官方信息，不代表账户已获配额、地区或项目访问权限。

## 结论摘要

- **直接帧图像为主的公平对比：** 可先将三个当日旗舰候选设为 `gpt-6-astra`、`claude-opus-5-5`、`gemini-4-argon`。三者官方目录均确认可供 API 使用且接受视觉输入。若需要低价对照，优先看 OpenAI `gpt-6-luna`、Anthropic `claude-haiku-5-5`、Google `gemini-3.1-flash-lite`；这些低价模型不应冒充旗舰结果。
- 对 640×480 静帧，按官方公开算法，OpenAI Astra 高细节约 **360 image tokens/张**（low 约231）；Claude Opus 5.5 按28像素视觉 patch 公式为 **414/张**；Gemini 4 Argon 的模型专页和定价页未披露单张640×480图像对应的固定视觉token数。本报告将其视觉token数与逐图费用标记为**未知**，不把旧版通用切片公式外推到 Argon。
- 对公开图像token规则足够明确的 OpenAI Astra 与 Claude Opus 5.5，400张静帧的视觉输入估算分别约$0.92–$1.44、$0.66；80/40/20张按比例计算。Gemini 4 Argon 只确认模型单价与图片输入能力，单图视觉token计数未能从其专属官方文档核实，因此总图像成本标记为未知。
- 五道题若在一条请求里共享同一组帧，帧只传一次；逐题拆成5次会重复付5遍图片输入，除非后续请求命中可用缓存。建议主结果采用**共享图像输入、一次提交五题、要求逐题回答并引用时间/帧索引**；如担心问题相互提示或串扰，再对预先指定子集做逐题独立复核。
- 不建议把原序列直接编码成视频后依赖服务端默认抽帧：Gemini 视频默认抽1 FPS，官方明确指出快动作可能遗漏。杯子倾倒是瞬时状态转移，应先离线制作“完整时间覆盖”与“紧凑但保留关键变化”的帧视图，并审计选帧覆盖率。没有一家的视频功能能保证免费保留所有400个原始采样帧；视频也不会自动更便宜。

## 官方模型、能力与 API 路径

| 提供方 | 当日旗舰候选 / 精确 ID | 视觉/视频方式 | 合理低价对照 |
|---|---|---|---|
| OpenAI | GPT-6 Astra / `gpt-6-astra` | 官方文档确认支持图像输入，图像作为 `input_image` 块（可直接传图片、URL或 Files API file_id）。在本次查阅的该模型官方输入文档中没有原生视频输入说明；需按图片帧提交。 | GPT-6 Luna / `gpt-6-luna` |
| Anthropic | Claude Opus 5.5 / `claude-opus-5-5` | Claude Messages API 接受图片块；Claude官方关于视频的提示建议是把视频拆成帧分析。本次核查未找到原生视频流/视频文件作为模型输入的官方说明，稳妥做法是提交帧图片。 | Claude Haiku 5.5 / `claude-haiku-5-5` |
| Google | Gemini 4 Argon / `gemini-4-argon` | Gemini API 有原生视频输入。静态模式默认按1 FPS抽帧，也能设置采样FPS与裁剪区间。适合视频级粗看，但需防止默认采样漏掉倾倒等短事件。 | Gemini 3.1 Flash-Lite / `gemini-3.1-flash-lite` |

官方证据：OpenAI [模型目录](https://developers.openai.com/api/docs/models)列明 GPT-6 Astra 为旗舰及其模型ID；[视觉输入文档](https://developers.openai.com/api/docs/guides/images-vision)展示 Astra 通过 Responses API 接受 `input_image`，并给出图片输入要求。Anthropic [当前模型状态表](https://platform.claude.com/docs/en/about-claude/model-deprecations)把 Opus 5.5 与 Haiku 5.5 列为 Active；[视觉文档](https://platform.claude.com/docs/en/build-with-claude/vision)说明图像块和分帧限制。Google [模型目录](https://ai.google.dev/gemini-api/docs/models)列 Gemini 4 Argon 为稳定旗舰及 ID；[视频理解文档](https://ai.google.dev/gemini-api/docs/video-understanding)说明原生视频和抽帧方式。

“未找到原生视频输入说明”仅表示本次查阅到的这些官方API文档没有确立支持；不能据此证明厂商所有产品形态永远不支持视频。对于本实验，可据已明确支持的图像块接口搭建可复现路径。

## API 输入数量、大小与上下文

- **OpenAI Astra：** 官方视觉指南写明单请求最多1,500张图、总payload最多512 MB；单图应用patch上限30,000，但 Astra 还有更具体的细节级限制。640×480远低于这些尺寸限制。模型目录列出的上下文窗口为1.05M tokens。图像、提示文本与其他输入都占上下文；官方提醒粗略图像token估算不保证每个请求限额都满足。
- **Claude Opus 5.5：** 官方视觉指南写明API单请求最多600张图，针对200K上下文模型的请求上限为100张；超过20张图片时存在更严格的单图边长规则，文档建议每图尺寸不超过2,000px以兼容多平台。Claude API每张图base64编码后最多10 MB；文档在此处未给出一个适用于本用例的明确总请求字节数。Opus 5.5 属于非200K档，按通用说明可到600张；但具体上下文/产品访问仍以账户与当日模型说明为准。模型价格页概括上下文“up to 1M varies by model”，不应把“最高1M”直接当作本账户对该模型的已确认额度。
- **Gemini：** 图像理解文档列单请求最多3,600张图，因此400帧在数量上满足。该文档未给出可直接用于本估算的通用总图片字节上限。Gemini 4 Argon 模型目录称上下文1M；定价页注明思考token等也计费。对超过短上下文窗口后的长上下文加价/阈值须查该模型当日专页；这里没有假设长序列一定按基础价格计价。

**重要边界：** “张数限制足够”不等于“请求一定能成功”。总请求字节、模型/账户速率配额、单次输入上下文、服务端预处理及具体接口版本均要独立核实。400张PNG很可能明显大于压缩JPEG的传输体积，但官方图片字节限制只在 Claude 页面给出单图上限；不要仅凭像素数推断请求体必然通过。可在离线评估阶段计算图像字节总和（不上传）并保留日志。

## 图像 token 公式和逐序列费用

费用仅按**图像视觉输入token**估算，不含问题/指令文本、答案输出、模型思考token、重试、缓存读写、税费或网络/平台费用。模型公开的是规则，不是内部图像编码细节；提交后以响应的 usage 统计和实际账单校准。

### 公开算法

- **OpenAI Astra：** 32×32 patch 覆盖数 `ceil(W/32) × ceil(H/32)`，再乘官方模型倍率1.2并向上取整。640×480高细节/原图尺寸：`ceil(640/32) × ceil(480/32) × 1.2 = 20 × 15 × 1.2 = 360` tokens。`low` 会缩放到512×512以内，这个长宽比下约512×384：`16 × 12 × 1.2 = 230.4`，向上取整231。`auto`按 original 的尺寸规则处理。因此可核实范围为约 **231–360 tokens/帧**，对涉及液体状态、杯口和咖啡机操作的视觉判断，建议将 `high`/`original` 作为主预算方案。
- **Claude Opus 5.5：** `ceil(W/28) × ceil(H/28)`。640×480为 `23 × 18 = 414` tokens/帧。图像低于该模型的分辨率上限，按公式不触发缩小。
- **Gemini 4 Argon：** 官方模型页确认图像输入和单价，但未找到Argon专属的逐张视觉token公式。通用图像理解页列出的258-token切片法与`media_resolution`规则没有明确写明可用于Argon。本次将Argon单图token量和序列图像总成本标为**未知**，不将通用/旧模型公式乘以Argon价格。应以Argon对应模型计数接口或响应usage核实后再估算。

OpenAI公式与Astra倍率来自[视觉token计算说明](https://developers.openai.com/api/docs/guides/images-vision)；Claude公式和清晰度分档来自[Resolution and token cost](https://platform.claude.com/docs/en/build-with-claude/vision)；Gemini估算与`media_resolution`说明来自[图像理解文档](https://ai.google.dev/gemini-api/docs/image-understanding)。

### 单图输入价格和静帧总估价

| 提供方/旗舰 | 当前标准输入价 | 单帧图像token | 400张 | 80张 | 40张 | 20张 |
|---|---:|---:|---:|---:|---:|---:|
| OpenAI GPT-6 Astra | $10 / 1M tokens | 231–360 | $0.924–$1.440 | $0.185–$0.288 | $0.092–$0.144 | $0.046–$0.072 |
| Anthropic Claude Opus 5.5 | $4 / 1M tokens | 414 | $0.662 | $0.132 | $0.066 | $0.033 |
| Google Gemini 4 Argon | $2 / 1M tokens（至2026-11-30）；12月1日起$4 | **未知** | **未知** | **未知** | **未知** | **未知** |

公式统一为：`N × 每帧视觉token × 输入单价 ÷ 1,000,000`。金额保留三位小数便于预算展示；内部计算按完整小数。OpenAI单图范围按low/high两种公开处理估算，不代表视觉质量等同；Claude按官方patch规则；Gemini未核实专属单帧token公式，因此图像总费用保留未知，不能将旧版切片估算当作其预算。三家输入价格依据官方[OpenAI价格页](https://developers.openai.com/api/docs/pricing)、[Anthropic定价页](https://claude.com/pricing)、[Gemini API定价页](https://ai.google.dev/gemini-api/docs/pricing)；Gemini官网明确列出2026-12-01价格变更日期，因此若实验跨过该日期需更新预算。

### 低价对照价格（标准档参考）

| 提供方/低价模型 | 输入 / 输出每百万tokens | 说明 |
|---|---:|---|
| OpenAI GPT-6 Luna (`gpt-6-luna`) | $0.10 / $0.50（Short context；超过该价格档位门槛另计） | 输入视觉token公式是否与Astra一致，不能无依据照搬；官方图像指南的可核实patch倍率表未列 Luna，所以单帧tokens待实测/官方工具确认。 |
| Anthropic Haiku 5.5 (`claude-haiku-5-5`) | <=100K prompt：$0.10 / $0.50；>100K：$0.50 / $2.50 | 该模型官方分辨率/图像token tier需按模型表确认；Opus 5.5的高分辨率token数不能直接当作Haiku价格预算。 |
| Gemini 3.1 Flash-Lite (`gemini-3.1-flash-lite`) | $0.25 / $1.50；Batch为$0.125 / $0.75 | Google价格按text/image/video共用input token单价；通用图像token估算法适用边界仍以该模型的media-resolution和usage核验。 |

低价候选适合先做预算/可行性摸底，不能仅凭token价格推断其对隐蔽状态转移的能力与旗舰可比。

## 视频原生输入是否更便宜、抽帧会漏什么

- **Gemini 4 Argon官方模型页明确支持原生视频输入和Agentic video understanding，默认处理模式为static。** Gemini视频文档描述静态模式默认按1 FPS抽帧，也能设自定义`fps`或裁剪视频区间；并提醒快速动作可能遗漏。建议主比较用共同静帧，另把Argon视频模式作为单独条件，记录实际处理模式和返回usage。
- 视频token成本随抽帧/分辨率而变化，Google官方价格按文本/图像/视频 token 定价，并未证明“传视频一定比传帧便宜”。默认1 FPS的视频可能远少于400张帧，但如果水流倾倒只发生很短时间就会漏关键状态转移；主动加fps又会增加图像输入。若要比较视频API，需离线确认每个关键事件时间点确实被抽到。
- OpenAI当前图像文档与Anthropic视觉文档提供帧图像路径；Anthropic模型指南的公开视频处理做法是“break into frames”。在当前证据下，跨厂商主比较应使用可见的同一组静帧，另把Gemini原生视频作为独立输入模式对照，不能将两种输入的差异误当模型能力差异。

来源：[Gemini视频理解](https://ai.google.dev/gemini-api/docs/video-understanding)（1 FPS、可自定义、快速动作限制）、[Gemini定价](https://ai.google.dev/gemini-api/docs/pricing)（视频tokens收费方式）、[Anthropic视觉文档](https://platform.claude.com/docs/en/build-with-claude/vision)与[模型提示指引](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables)（视频拆帧建议）。

## 五个问题：同请求还是逐题

设每次调用的图像token数为 `V`，问题文本和格式约束为 `Q`，回答/思考token为`O`。

- **同请求：** 输入约 `V + Q1 + … + Q5`；一份输出包含五个答案。图像视觉输入只计一次。优点是视图复用、成本低、上下文一致；缺点是题目互相显式提示，模型可能从某题答案泄漏/推断另一题，回答也可能不均匀。
- **逐题5请求：** 没缓存时输入约 `5V + ΣQi`；视觉输入成本近似同请求的5倍，另产生五份固定提示/输出开销。优点是各题隔离，评分/失败模式更干净；缺点是延迟和成本增加，重新传帧时输入内容要完全一致才可能缓存。
- **建议：** 先以每个序列一次输入统一帧视图、一次回答5题做主比较，要求严格JSON包含每题结论、关键时间/帧索引、可见证据与“不确定”；指令不要把gold或人工事件标签给模型。为测串扰，再预注册抽一部分样本做5次独立问题，且沿用完全相同的帧列表、顺序、图像尺寸/detail与系统指令。不要只给某个模型更多或更精心挑的关键帧。

## 缓存和批处理

- **OpenAI：** 官方价格列有标准、Flex/Batch等速率档及缓存读写费用；GPT-6 Astra标准输入$10/MTok，缓存读$1、缓存写30分钟$12.50、12小时$25。缓存要求请求开头存在匹配前缀；提示缓存文档对GPT-6系列指出至少1,024个可见输入tokens的缓存前缀，重复相同帧内容/提示才有机会复用。首次缓存写入可能比标准输入贵；如果仅一个请求或不同题目被插入图像前缀中，不保证命中。Batch适合离线异步数据集处理，价格表列Flex/Batch的低价档，但应以当日模型价格表和Batch适用条件复核，不应为单个5问请求仅凭“批量”字样假设折扣。
- **Anthropic：** Batch API异步处理，每个请求按标准API价格50%计费，适合成批处理独立样本；不是一个请求里并列5题的特别折扣。Prompt caching可缓存跨请求相同前缀，图像可作为前缀内容，但首次写缓存另收费、匹配与TTL条件要遵循官方缓存文档；当前Opus 5.5价格页显示read $0.20/MTok、write $5/MTok，标准输入$4/MTok。
- **Google：** Gemini 4 Argon可用 Batch（输入/输出各约标准50%，截至2026-11-30标准价$2/$10与batch $1/$5），文档注明该型号仅隐式缓存，不支持显式创建缓存对象。隐式缓存需要相同前缀和达到该模型最低token门槛（官方缓存页列Gemini 4 Argon为4,096 tokens）；缓存不保证命中。若同一400帧前缀重复问5题，可能省成本，但确认实际响应中的cached token usage再计算。

官方来源：[OpenAI缓存指南](https://developers.openai.com/api/docs/guides/prompt-caching)、[OpenAI价格页](https://developers.openai.com/api/docs/pricing)、[Claude Batch处理](https://platform.claude.com/docs/en/build-with-claude/batch-processing)、[Claude价格](https://claude.com/pricing)、[Gemini优化与批处理](https://ai.google.dev/gemini-api/docs/optimization)、[Gemini缓存](https://ai.google.dev/gemini-api/docs/caching)、[Gemini价格](https://ai.google.dev/gemini-api/docs/pricing)。缓存/批处理折扣有前提，主成本表均按未命中的标准输入价。

## 选帧公平性与实验建议

1. **两个视图都由离线固定规则生成。** A. 完整视图按时间顺序均匀覆盖整段序列；B. 紧凑视图控制在80/40/20张预算内，但必须保留接水前/过程中/完成后、杯子倒水前/倾倒瞬间/倾倒后、杯子放入咖啡机前/后等状态变化，以及起始和最终状态。紧凑视图的抽样依据在所有模型之间相同。
2. **给每帧保留外部索引映射，但只向模型传图像与预注册的纯文本问题。** 所需的时间顺序可以由图像排列和统一的帧序号/时间戳提供；不要传入场景标签、动作日志、任务metadata、候选答案、audit标记或评测结果。可在事后用帧索引对齐输出与人工审计，避免把这些辅助信息变成模型泄漏。
3. **把两种模态实验分开。** 共同静帧比较三家，记录每家输入尺寸/detail、所选帧哈希与顺序。Gemini视频作为额外条件，记录视频时长、fps、裁剪、分辨率设置与响应usage；不能与共同静帧结果混成一个排行榜。Gemini 4 Argon 专属模型页现已明确列出Agentic video understanding支持，默认static；因此可以纳入视频模式单独评估，但仍需记录实际处理模式。
4. **做关键事件覆盖审计。** 在本地检查抽出的关键事件附近连续帧，确认至少一帧显示水流/杯子倾斜等过程证据，且前后状态能区分。若实际观测只能证明“杯子当前有水/无水”，不能当成过程事件被观察到。
5. **先以20帧和40帧视图估测真实usage与字节体积，再决定80/400张。** 文档成本只是视觉token下界式预算；文本提示、输出、推理token、视频帧量和平台请求体限制都可能增加实际支出。保留请求配置、模型ID、usage、模型版本/时间、每帧像素和选帧manifest，确保同一批样本可重跑。

## 资料来源与限制

此结论只基于下列供应商官方文档，没有用第三方价格汇总、benchmark博客或API调用进行交叉验证：

1. [OpenAI模型目录](https://developers.openai.com/api/docs/models)；[OpenAI视觉指南与输入限制](https://developers.openai.com/api/docs/guides/images-vision)；[OpenAI图片成本计算器](https://developers.openai.com/api/docs/guides/image-cost-calculator)；[OpenAI价格表](https://developers.openai.com/api/docs/pricing)；[提示缓存指南](https://developers.openai.com/api/docs/guides/prompt-caching)。
2. [Anthropic模型生命周期/状态表](https://platform.claude.com/docs/en/about-claude/model-deprecations)；[Opus 5.5 模型页](https://platform.claude.com/docs/en/models/opus-5-5/overview)；[Claude视觉指南](https://platform.claude.com/docs/en/build-with-claude/vision)；[Claude定价](https://claude.com/pricing)；[Message Batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing)；[Claude提示工程/视频拆帧建议](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables)。
3. [Gemini模型目录](https://ai.google.dev/gemini-api/docs/models)；[图像理解](https://ai.google.dev/gemini-api/docs/image-understanding)；[视频理解](https://ai.google.dev/gemini-api/docs/video-understanding)；[Gemini API价格](https://ai.google.dev/gemini-api/docs/pricing)；[缓存](https://ai.google.dev/gemini-api/docs/caching)；[推理优化/Batch](https://ai.google.dev/gemini-api/docs/optimization)。

**限制：** 官方资料会更新，网页中显示的预览、通用公式和价格阶梯不保证某账户即刻可调用；控制台项目额度、所在地区、速率限制、服务端自动缩放和长上下文价格可能改变实际结果。本文不确定的部分已标出，尤其是 Gemini Argon 对640×480的真实视觉token数（因此未计算图像费用）、各服务端总请求字节限制以及缓存命中率。正式跑模型之前，应在本地用20张/40张固定视图发一条合规的实验请求或使用厂商官方token计数/预览能力，再以usage和真实账单核对；本次委托要求不调用模型，因此尚未验证这些服务端行为。


## 2026-10-29 价格与模型 ID 证据复核附录

本附录针对“是否为公开API ID”“价格与输入限制是否有可审计依据”“Gemini是否把不适用公式外推”进行二次核验。下列是本轮实际 web 工具返回并打开的官方页面ID、标题和可定位段落。每一页仅记录位置与用途，不以首页链接代替证据。当前查证不运行 API。

### 公开 API 模型 ID 与价格

- **OpenAI：`gpt-6-astra` 是官方公开 API 模型。** 页面 `turn95view0`，标题 **Models | OpenAI API**，第948–975行：官方模型目录将 GPT-6 Astra 介绍为旗舰，列出“Model ID `gpt-6-astra`”及输入$10/MTok、输出$50/MTok；第952行说明最新模型支持文本与图像输入，并通过 Responses API 与SDK提供。补充 API 请求 schema：`turn94search6`，标题 **Create a model response | OpenAI API Reference**，搜索返回的 `model` 枚举明列 `gpt-6-astra`；这不是本地 Codex 选择器的ID推断。
- **Anthropic：`claude-opus-5-5` 是 Claude API 可用 ID。** 页面 `turn95view2`，标题 **Claude Opus 5.5 - Claude Platform Docs**，第85–89行列“Claude API”及`claude-opus-5-5`，第104–122行列$4输入、$20输出、缓存价和Batch API折扣；第127–128行确认为1M context。其官方模型目录另见 `turn94search4`，标题 **Models overview - Claude Platform Docs**，搜索返回段列 Claude API ID、1M context和价格。
- **Google：`gemini-4-argon` 是稳定Gemini API模型。** 页面 `turn95view6`，标题 **Gemini 4 Argon | Gemini API | Google AI for Developers**，第88–107行逐项列model code、支持输入(Text/Image/Video/Audio/PDF)、1,048,576 token窗口、Stable ID以及agentic video supported。页面第115行显示最后更新为2026-10-29 UTC。价格由`turn96view7`，标题 **Gemini Developer API pricing | Gemini API | Google AI for Developers**，第120–150行确认基础输入输出价、Batch价格、缓存只支持implicit；模型单页也可由`turn95view7`第98–100行和第391–398行定位价格。

### 视觉token规则和图像数量限制

- **OpenAI图像限制。** `turn96view0`，标题 **Images and vision | OpenAI API**，第3374–3382行：图像格式、每请求总payload512MB、最多1500张图，以及每图30,000 patches处理上限；不同模型/ detail仍有更低的patch预算。适用于这份API视觉指南，不应解释成所有OpenAI产品的通用上传限制。
- **OpenAI Astra图片token公式。** 同页`turn96view1`与`turn96view2`，第3433–3454行：文档说明32×32 patches、`ceil(width/32)×ceil(height/32)`覆盖计算，再乘模型倍率并向上取整；该表明确将`gpt-6-astra`列为1.2倍。`turn95view1`第3417–3418行列Astra detail尺寸处理规则。依此对于640×480且high/original不缩放：300 patches×1.2=360 tokens；low缩至512×384内则约192 patches×1.2上取整231。该数字是官方公开算法推导值，不是API响应usage。
- **Claude请求上限与单图bytes。** `turn96view3`，标题 **Vision - Claude Platform Docs**，第243–255行：200K上下文模型每请求100图，其他模型600图；单图上限8000×8000，Claude API每张base64后10MB，并有>20图的尺寸限制。Opus 5.5的1M上下文由`turn95view2`第127–128行确证，所以本例引用600张上限。注意原报告中600图、10MB、2000像素安全建议均来自这张视觉指南页面，未发现通用总请求bytes上限。
- **Claude图片token公式。** `turn95view4`，标题 **Vision - Claude Platform Docs**，第260–268行列28×28视觉patch及公式，并列high-resolution模型名单/上限；Opus 5.5属于Claude 4.7之后模型的high-resolution tier。640×480可按官方公式得`ceil(640/28)×ceil(480/28)=23×18=414` tokens。
- **Google图像数量限制。** `turn95view8`，标题 **Image understanding | Gemini API | Google AI for Developers**，第1354–1358行列Gemini模型单请求最多3600个图像文件。这个数作为Gemini API图像理解指南的上限引用；文件大小限制未在本页确认。
- **Google旧版/通用切片规则的适用边界。** `turn96view5`和`turn96view6`，标题 **Image understanding | Gemini API | Google AI for Developers**，第1359–1370行描述≤384px时258 tokens，较大图像按768×768切片，并提供rough tile公式；同处说明Gemini 3提供`media_resolution`。这段文档未指明该逐图公式对Gemini 4 Argon的可计费视觉token数具有约束力，也未证明640×480下某一固定token数。因此**撤销原报告的Argon约1,032 token/帧及其对应金额**，表格改为未知。该公式仅保留为可能的旧/通用估算参考，不用于生成Argon成本数字。

### 对先前报告的更正

1. 三个旗舰模型ID不是仅见于Codex本地模型菜单：OpenAI、Anthropic、Google各有官方模型/参考页明列API模型字符串；对应证据见上方页面ID与行号。API可用性不等同于每个用户账户已开通或有额度，账户配额仍未验证。
2. OpenAI的1500张和512MB确由官方API视觉指南明确列出；Anthropic的600张是Claude API对1M上下文型号的一般上限，Opus 5.5为1M上下文；Gemini图像指南列3600文件/请求。这些是不同厂商、不同API文档的限制，不能横向推断其总payload相同。
3. **Gemini Argon费用表应只保留官方输入单价，不提供帧数×单图token的金额。** 直到Google提供或调用官方token counting/usage并实测特定Argon请求配置前，Argon单图图像token量与图像输入总价都属待核实。
4. 原报告曾称Gemini 4 Argon官方Agentic video支持未能确认。现据`turn95view6`第103行和Google Argon官方模型页核实，Argon确实支持agentic video，默认static；视频比较仍应独立于共同静帧比较，记录设置和返回usage。
5. 先前曾将Google通用切片估算结果乘Argon单价；这是证据不足造成的过度具体化，已在正文改为未知，旧数字不应继续用作实验预算。



