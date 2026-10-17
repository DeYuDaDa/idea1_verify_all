# AI2-THOR 20 组配对设计规范

本目录当前是 **design spec**，不是模拟器生成数据，也不是已经验证的金标准。`specs.json` 描述 20 个配对设计及 A/B 共 40 个候选场景。`expectedchecks` 记录构造时要验证的假设；它们不能直接用作模型预测的固定答案。运行后，所有标签和值必须从所选 AI2-THOR 版本的实际事件结果与对象 metadata 导出。`references` 暂留空，待逐项核对官方文档和版本行为后补入。

## `specs.json` 字段

每个 `pairs[]` 项至少包含以下设计字段：

| 字段 | 含义 |
|---|---|
| `pair_id` | 唯一 ID：M01–M04、S05–S07、W08–W12、C13–C15、T16–T18、B19、P20。 |
| `family` | 机制族。 |
| `contrast_key` | A/B 唯一预期差异的名称。 |
| `strict_minimal_pair` | 是否预期两版保持同一动作参与者/动作，仅改变关键前置条件。S07 和 C15 为 `false`，因为动作目标或目的地也改变。 |
| `event` | 计划执行的动作、目标、成功要求及两版共享事件。这里的计划不是事件成功证据。 |
| `mechanism` | 待核验的影响机制名称。 |
| `rules` | 初态、A/B 差异、候选变化事实、候选保留事实和配对翻转要求。均为设计假设。 |
| `observable_requirements` | 模型输入需要提供、或用于决定可知性的事件/历史证据。 |
| `expectedchecks` | 生成与模拟核验清单，不是模型的 gold 输出。 |
| `references` | 支持机制设计的来源。核实前为空数组，不应伪造来源。 |

`known_support_risks` 补充记录 API/场景/对象类型、物理接触、时序、metadata 字段或可观测性方面的待核验风险。某设计未通过核验时，应将其标为未填充/不适用，或重做场景；不能把设计假设强写成实际事实。

## 生成导出：公开输入与隐藏金标准分离

建议生成两个逻辑上分离的文件或数据表；公开模型输入不能包含隐藏标签、模拟器最终状态、候选机制的实际成败或仅用于评分的元数据。

**公开 `model_input`** 可包含：

- `sample_id`、`pair_id`、`variant`（A/B）、场景/回合标识和输入协议版本；
- 历史视觉观察及其顺序、模型可见的历史事实、对象身份映射；
- 新事件的视觉/动作证据，以及该实验条件明确允许提供的规则说明；
- 待判断的事实清单及作答格式。

仅在对应实验条件明确提供时，才可把规则、历史事实或人工确认的动作描述放入公开输入。不要把 `directness`、实际 `changed` 标签、`knowability`、隐藏的 A/B 设计目的、实际后态或 gold 理由泄露给模型。带完整后态图像的观察式对照实验应使用独立协议标识，避免与事件驱动输入混合。

**隐藏 `hidden_gold`** 至少保存：

- 执行环境及模拟器版本、场景、对象 ID/类型、随机种子（若适用）、准备动作序列、被评测动作及其参数；
- 每个动作的 `lastActionSuccess`、错误/失败信息、时间步和相关截图/metadata 快照；
- 原始对象 metadata 的 before/after 快照及其字段路径；
- 按事实计算的实际差异、证据来源、事实是否可由模型输入确定，以及最终核验状态；
- 配对核验结果和未满足条件的原因。

公开与隐藏记录使用不可混淆的文件名/路径或访问控制。对模型输入生成器做字段白名单，避免通过序列化、日志、文件名或图片侧信道泄漏 gold。

## 事实与 `actual_facts_diff`

事实的基本键为 `(subject, predicate, object/value)`；属性可用 `(entity, attribute)` 表示，关系可用 `(subject, relation, object)` 表示。对每一条待评事实，保存：

```json
{
  "fact_id": "Mug_1.temperature",
  "subject": "Mug_1",
  "predicate": "temperature",
  "object_or_value_type": "enum",
  "before": {"state": "value", "value": "RoomTemp"},
  "after": {"state": "value", "value": "Hot"},
  "changed": true,
  "directness": "indirect",
  "knowability": "knowable",
  "evidence": [{"source_type": "simulator_metadata", "record_id": "...", "field_path": "..."}],
  "verification_status": "simulator_verified"
}
```

该例只说明记录格式，不是任何一组的预设 gold。`before`/`after` 的 `state` 应区分 `value`、`unknown`、`not_applicable`、`not_recorded`。字段缺失不等于 `false`；不可填充对象不应强加 `isFilled=false`。对 W09、W10、T18 等初始已满足条件，若 after 值与 before 值相同，则 `changed=false`；规则适用或事实已经为真都不能替代实际变化。

`actual_facts_diff` 从同一对象、同一字段路径的实际 before/after metadata 推导。先规范化值类型和枚举，再比较；保留原始 metadata、规范化规则与差异日志，使差异可复算。不得从设计稿中的 `change_candidate_facts` 直接创建变化标签。对于新建/删除关系，分别记录关系事实的出现/消失；对于不可比较、未采集或未适用字段，不得伪造差异。

## `directness` 分类

`directness` 描述实际事实变化相对被评测事件的机制位置，与事实是否可知、是否变化分别记录：

- `direct`：事件动作直接作用于该事实（例如成功开关操作改变目标设备的 toggle 状态；成功拾取直接改变被拾取物的位置/持有状态）。
- `indirect`：事件通过经核实的机制、关系或前置条件导致该事实变化（例如已开启设备对其内部适用物体的作用）。
- `unaffected`：事实在有效观测窗口内经核实保持相同。若 `changed=false`，可以另存 `change_status=preserved`；`unaffected` 不是“没有采集到”。
- `unresolved`：机制归属或差异无法可靠确定，应留待裁决；不能猜测为 direct/indirect。
- `not_applicable`：该事实/机制对该对象不适用，例如非容器对象的填充属性。

直接/间接分类依据记录的动作目标和已验证机制，不能仅根据“同一个对象”或“相邻对象”推定。B19 的 `isBroken` 与 `isToggled` 是同对象上两个独立事实；前者可为直接变化，后者若因损坏联动而变化则为间接变化。

## `knowability`、来源和证据

`knowability` 表示仅根据该样本的 **公开模型输入**，目标事实是否可被确定，不表示模拟器是否能读出它。建议枚举：

- `knowable`：公开输入中的观察、明确提供的历史事实/规则和成功事件证据足以确定该值。
- `unknown`：事实存在，但公开证据不足或遮挡/不确定使值不可确定。
- `not_applicable`：字段或机制不适用于该对象。
- `not_assessed`：尚未完成可知性审查。

每条事实保存一个或多个 `evidence` 项，至少说明 `source_type`、`record_id`，以及适用时的 metadata 字段路径、帧号/时间戳、动作记录或规则来源。来源类型可包括 `simulator_metadata`、`event_action_log`、`history_observation`、`event_observation`、`provided_rule`、`human_adjudication`。注明证据是公开还是隐藏，例如 `visibility: model_input|hidden_gold`。隐藏 metadata 可以证明实际状态，但不能单独使模型输入中的事实变为 `knowable`。视觉不可见的温度等属性，若公开输入没有足以推出它的历史/事件证据，应标 `unknown`。

## 配对核验

每组生成后保存 `pair_validation`，至少核验：

1. 两个变体是否均成功构造，准备动作和评测事件是否分开记录；
2. 事件是否按设计成功，涉及对象身份、动作参与者、目标、位置、关系是否与记录一致；
3. A/B 在 `contrast_key` 上是否确实不同，其他预定匹配事实是否相同；
4. 实际 metadata 差异是否产生预期的目标事实翻转，并且保留事实确实保持；
5. 观察和模型可见事实是否支持每个待评问题的 `knowability`；
6. 所用字段/机制在选定模拟器版本中是否适用，并记录来源及核验结果。

`strict_minimal_pair=true` 时，除指定对比条件外，事件、参与者/目标、场景、对象身份及其他受控初态应匹配；不匹配则不能继续标严格最小配对。S07 改变旋钮目标，C15 改变放置目的地，固定为非严格配对并单独报告。M03 改变 Bowl 的脏/净初值，测试属性保留值，不是同一目标属性上的变化/不变化翻转。W09、W10、T18 的已为真/已满足状态不应被表述成新变化。所有 A/B 标签最终取实际 metadata 差异，不从配对设计名称继承。

若关键动作失败、条件没有翻转实际目标事实、初态无法实现或关键 metadata 不可观测，则 `pair_validation.status` 应为 `failed`、`unfillable` 或 `needs_review`，并保存原因；不能为了保留 20 组数量而强填预期标签。

## 离线核验与交互核验边界

设计稿解析、JSON/schema 校验、字段完整性、ID 连续性、A/B 所需字段对照、候选模型输入/隐藏 gold 字段泄漏检查、以及在已保存的 metadata 快照上重算 `actual_facts_diff`，均可离线执行。实际动作是否成功、接触/包含/支撑关系、热/脏/填充/烹饪状态变化、对象可操作性、温度和延迟效果，必须由目标 AI2-THOR 版本的执行结果与 metadata 核验；若需要确认可视证据，则还需要检查对应帧。代码层 schema 合法不等于机制已被模拟器支持。

## 最小数据组织建议

```text
AI2THOR_20组/
  specs.json                  # 本设计稿，非生成数据
  schema.md
  generated/                  # 仅在实际生成后创建
    model_input.jsonl         # 可供模型读取
    hidden_gold.jsonl         # 模拟器状态、事实差异、证据和配对核验
    manifest.json             # 版本、场景、协议和文件哈希
```

模型评分时按事实行比较预测，不按对象整体赋单一 Changed/Unchanged 标签。至少分别统计 direct update、indirect update、preservation、unknown 处理，以及严格配对的联合正确率；非严格配对单独分层报告。
