[CmdletBinding()]
param([Parameter(Mandatory)][string]$WebRoot,[Parameter(Mandatory)][string]$OutputPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($WebRoot);$out=[IO.Path]::GetFullPath($OutputPath)
if(Test-Path -LiteralPath $out){throw "Report exists, refusing overwrite: $out"}
$raw=Get-Content -LiteralPath (Join-Path $root 'batches.js') -Raw -Encoding UTF8
$batches=ConvertFrom-Json -InputObject ($raw.Substring('window.REVIEW_BATCHES = '.Length).Trim().TrimEnd(';')) -AsHashtable -NoEnumerate
$manifest=Get-Content -LiteralPath (Join-Path $root 'site_manifest.json') -Raw|ConvertFrom-Json -AsHashtable
$batch=@($batches|Where-Object{@($_.items|Where-Object{$_.kind -eq 'mechanism'}).Count -gt 0})[0]
$source=@($manifest.batches|Where-Object{$_.batch_id -eq $batch.id})[0].source_root
$items=@($batch.items|Where-Object{$_.kind -eq 'mechanism'});$cases=@($items|ForEach-Object{($_.id -split '/')[-3]}|Sort-Object -Unique)
if($cases.Count -ne 45 -or $items.Count -ne 90){throw 'This report contract expects the supplied 45-template/90-attempt run.'}
$judgements=@{
f1_toaster_enter_then_activate='局部支持：这一顺序产生熟度变化；温度空值是取字段问题，不作温度保持证据。'
f1_toaster_activate_then_enter='局部支持：先启动再放入也有熟度变化；两种顺序都有效，不表示存在顺序差异。'
f1_microwave_enter_then_activate='局部支持：成功放入、关门、启动后土豆受热并变熟。'
f1_microwave_activate_then_enter='模板被设备约束阻止：运行中开门被拒绝，放入被跳过。应改事件模板，不是证明后来放入不会加热。'
f1_coffee_enter_then_activate='局部支持：空杯先放入、后启动，可记录到咖啡注入。'
f1_coffee_activate_then_enter='局部支持：先启动、后放入空杯，也可记录到咖啡注入。'
f2_microwave_inside='未验证：探针读 ObjectTemperature 而原生字段为 temperature，初态核验便退出；不是物理摆放反例。'
f2_microwave_outside='未验证：同一温度别名问题阻断外部对照，不能评价炉外是否受影响。'
f2_microwave_position_scan='部分证据：FP1 中心候选真实成功，土豆 RoomTemp→Hot、未熟→已熟；边缘/另一场景候选失败，没有形成边界对照。'
f2_sink_position_scan='未验证：候选摆放未建成可比较的位置—关系—效果条件，不说明流水边界不存在。'
f3_toaster_single='单对象基线支持：一片面包可变熟；单对象不是多对象独立性的证据。'
f3_toaster_multiple='共同作用支持，独立性未验证：两片面包均变熟；记录自身明确标注仍待逐实例单对象对照。'
f3_microwave_single='单对象基线支持：土豆 RoomTemp→Hot、未熟→已熟。'
f3_microwave_multiple='未验证：多土豆条件没有成功建立，单土豆成功不能替代多对象试验。'
f3_water_single='未验证：碗的候选摆放/真实水槽关系未建立，水流作用未测成。'
f3_water_multiple='未验证：多对象水流条件未建立，不能评价共同作用或竞争。'
f3_stove_single_kettle='单对象基线支持：映射炉头上的水壶 RoomTemp→Hot。'
f3_stove_single_pot='单对象基线支持：映射炉头上的锅 RoomTemp→Hot。'
f3_stove_multiple='未验证：第二件对象摆放受阻，尚无多对象共同受热对照。'
f4_uncooked_then_heated_and_cooled='未验证：温度别名导致初态核验失败，未执行完整加热—撤源—冷却。'
f4_cooked_then_reheated_and_cooled='未验证：同一字段问题，不能用预期不可逆熟度代替本次实测。'
f5_dirty_empty_water_on='有差异、原因未隔离：FP1 碗仍脏且空，FP2 出现预期变化；实际流水接触未独立核实，不能直接反驳接触机制。'
f5_dirty_empty_water_off_control='局部保留控制支持：关水时保持脏且空。它本身不证明开水后必然清洁/注水。'
f5_dirty_water_filled_water_on='机制未验证：FP1 没有预期清洁，接触未知；FP2 事件前有水条件未保持。不能补成四格成功。'
f5_dirty_water_filled_water_off_control='部分控制：FP1 有保留记录，FP2 有水初态在准备/拿起时不满足。'
f5_clean_empty_water_on='有差异、原因未隔离：FP1 仍空，FP2 有预期注水；不能把水槽归属直接当水流接触。'
f5_clean_empty_water_off_control='局部保留控制支持：关水时保持干净且空。'
f5_clean_water_filled_water_on='部分保留观察：FP1 干净/已有水保留；此格本来就无需新变化，不能单独证明水流作用；FP2 初态失败。'
f5_clean_water_filled_water_off_control='部分控制：FP1 保持干净且有水，FP2 有水初态未保持。'
f6_initially_empty='局部机制支持：两个场景空杯放入开启咖啡机后均为空→咖啡。'
f6_initially_water_filled='局部机制支持：两个场景杯中已有水，放入开启咖啡机后仍为水。'
f6_fill_then_empty='历史版本支持：先装水后倒空，事件时为空，随后变为咖啡。'
f6_empty_then_fill='历史版本支持：先倒空后装水，事件时为水，随后保留水。'
F7_removed='部分支持：FP2 苹果不动、盘子移动约3.975m；FP1 构造失败。支持单层当前关系下的位置结果。'
F7_returned='部分支持：FP2 苹果放回后与盘子共同位移约3.975m；FP1 构造失败。'
F7_retained='局部支持：两场景一直在盘上的苹果均随行；拿起后 parent 字段缺失不能直接当作关系断开。'
F8_control_A='实际不符合简单保留预期：FP1 A开/B关，但两容器均 RoomTemp→Hot；FP2 仅目标容器热。温度范围原因尚未隔离。'
F8_control_A_swapped='同样的实际偏差：FP1 交换后另一容器仍变热；开关映射成立不保证热影响只到一件容器。'
F8_control_B='局部支持：两场景目标炉头开启、目标容器变热，另一容器保持室温；限于这些摆位与时间。'
F8_control_B_swapped='局部支持：交换摆位后两场景仍满足所测的目标热/另一容器室温对照。'
F9_matched_time='有限而真实的背景演化证据：两场景固定推进对照均关火→RoomTemp、保源→Hot；普通Pass臂均Hot，不外推属性时钟。'
F10_nested_carry='未验证：两场景均未建立完整嵌套初态，未进入有效外层拾取干预。'
F10_nested_heat='未验证：一场景放外层时内容物关系丢失，另一摆放受阻；未完成有效嵌套加热。'
F10_nested_wash='未验证：所需嵌套清洗初态未建立，不能由单层流水或搬运推定。'
F11_redundant_support='未验证：共同支持位置搜索/几何筛选未完成，A-only/B-only/双源/分别撤源未形成，不是机制不存在。'
}
$head=@'
# Step 31：45 种基础机制与原设计预期的核对

日期：2026-10-24。用途：把本轮实测结论反馈给最初设计对话，决定哪些机制可用于后续困难题，哪些需要改设计或补验证。

## 直接结论

**不是所有机制都已证实，也不能把未证实统一称为猜错。** 本次确认了一些局部机制，遇到了设备约束、测量代码错误和场景构造失败，并记录了一个需要认真处理的非目标升温现象。没有证据据此宣布整个研究主线成立或失败。

- **可以保留的事实基础：**咖啡机当前液体门控 F6；单层盘子/苹果的当前关系与随行 F7（完整三条件主要在 FloorPlan2）；烤面包机两种顺序下的熟度变化；微波炉成功放入后启动的受热/熟化；水壶与锅的单对象炉头加热；F9 的有限固定推进关火/保源对照。
- **明确需要改掉或收窄的设计表述：**运行中的微波炉不能直接开门完成「先启动再放入」；FloorPlan1 的部分炉头条件下，不能预设另一容器一定保持室温；两片面包同时变熟只能说明共同作用，不能写成完整多对象独立性已经验证。
- **还没测清：**F2 完整作用边界、F3 大部分多对象比较、F4 热—冷与熟度分离、F5 已验证流水接触下的四格条件、F10 嵌套组合、F11 双来源替代支持。

最初文档把 F1–F11 写作待验证问题，并未保证每项都为真。其中 F2 本来就在问「关系够不够，还是需要接触」，不是指定必须出现某种答案。因此反馈应包含「测到了什么、比较是否完成」，而不是强行给每一类打一个猜对/猜错标签。

## 这次到底审核了什么

原设计为 `主线1/明确难度定义&测试的模拟器事实.md` 中 F1–F11 表及 A–E 例组。证据以本批 `source/` 中实际执行的代码、90 个 `result.json`、`actions_by_reset.json`、`capture_index.json` 为准，不能拿后来修订的代码当成本次已经运行。

范围是 **45 个模板 × 两个场景 = 90 次尝试**。原始程序状态为 49 supported、12 inconclusive、22 setup_unavailable、3 counterexample、4 probe_error；它们是程序检查状态，**不是 49 个完整设计假设已通过**。本批未调用模型，也没有证明后续题目已达到预期难度。

并行复核覆盖 F1–F4、F5–F8、F9–F11，并另做一次独立交叉审计。全部 45 模板及 90 次结果均按记录核对；图片语义只抽查了下文明确列出的 11 张，**没有逐张验收全部 752 次截图引用**。

## 必须分开的五类结论

| 类别 | 本轮例子 | 能说什么 |
|---|---|---|
| 有效条件和操作下出现预期状态 | F6 空杯变咖啡、有水杯保留水 | 在本次设备、对象、场景与观察窗口内支持该事实 |
| 有状态结果，但比较或控制不完整 | F2 一个中心正例、F3 两片面包共同变熟 | 保留正例，不能升级成完整边界或独立性规则 |
| 测量代码阻断 | F2 固定内/外、F4 读取错误温度别名 | 修读取后重做；不是物理机制反例 |
| 设备约束或搭建失败 | 开着的微波炉不能开门；多对象摆位、嵌套布置失败 | 调整模板或构造，不能用预期补 Gold |
| 真实状态偏离预期，但原因未隔离 | F8 两容器均热；F5 开水格未出现目标变化但接触未知 | 保留异常；分别调查实际作用区域、控制、接触与背景演化 |

**照片不好与机制真假是两层结论。** 记录到原生状态从水变咖啡，即使照片没拍到杯子，仍是模拟器机制证据；但这样的照片不能因此成为可答的视觉题。反过来，照片很清楚也不能补出一次没有成功执行的干预。

## 对原 F1–F11 的判断

| 项目 | 本轮结果 | 反馈给设计对话的修改 |
|---|---|---|
| F1 触发顺序 | 烤面包机两种顺序均变熟；咖啡机两种顺序均可注液；微波炉先放后开成功，先开后放被开门规则阻止 | 按设备分别保留事件模板；不要假设所有设备都能执行相同两种顺序，更不要把两顺序均有效叫顺序造成差异 |
| F2 作用边界 | 内外固定对照被温度字段问题阻断；FP1 扫描中有一个成功中心正例，但无有效边缘/外部比较；水槽扫描摆放失败 | 边界仍未知。先修测量与候选摆位，不能直接写包含关系足够或不够 |
| F3 多对象独立性 | 两片面包共同变熟，其它主要多对象搭建失败；记录自身仍标待匹配单对象对照 | 仅保留共同作用证据。单对象加热成功不能替代同实例、多对象和无关对象保持比较 |
| F4 温度/熟度分离 | 四次均停在初态温度检查，热—冷序列没完成 | 暂不把再加热后冷却且熟度保持写成本批验证事实；修代码重测 |
| F5 清洁/注水分离 | FP1 三个开水格未达预期；FP2 空碗格有正例、有水格初态失败；接触未独立核实 | 不能称流水机制被推翻，也不能称四格完成。先校准实际水流作用和事件时初态，再谈属性交叉 |
| F6 咖啡门控 | 四种条件、两个场景，事件时为空者变咖啡，事件时有水者保留水 | 可保留当前液体门控及两个历史版本；不外推任意液体或所有设备，不自动称为高难 |
| F7 当前承载关系 | FP2 移出不随行、放回/保留随行；FP1 移出/放回摆位失败 | 保留单层世界位置结论。拾取后 parent 字段消失不能直接当关系断开 Gold；多层另测 |
| F8 控制局部性 | 原生开关映射有证据；FP1 A 与交换 A 中另一容器也热，FP2 对应条件无此偏差 | 将「旋钮只开对应炉头」和「只加热对应容器」拆成两条命题；前者不自动证明后者 |
| F9 背景演化 | 每场景固定推进两臂均关火后室温、保源仍热；Pass 臂两者仍热 | 有效但窄：只说明这次固定请求推进下的关火/保源温度对照，不证明属性时钟与所有设备的时间语义 |
| F10 嵌套组合 | 六次都没完成所需嵌套初态和有效后续干预 | 嵌套搬运/受热/清洗全部仍未知，不写入正式困难题前提 |
| F11 替代支持 | 未得到经验证的共同作用位置，三臂和逐一撤源未完成 | 两来源替代支持仍未知；几何候选失败不等于物理上不可能 |

## 四个最容易把结果解释错的细节

1. **温度别名是程序问题。** 本批原生快照使用 `temperature`，但固定 F2/F4 与部分 F1 读取 `ObjectTemperature`；旧 helper 没有对两种方向统一。这导致 F2/F4 在基线便停止，F1 烤面包机温度成为空值。熟度仍有独立正例。后续代码修复不等于旧数据自动产生了缺失结果。
2. **微波炉第二顺序失败有明确原因。** `ToggleObjectOn` 成功后，`OpenObject` 返回 `Target must be OFF to open!`，放入/再关门跳过。因此结果不是「成功放入后不加热」。
3. **F3 程序自己没有给独立性盖章。** 双面包记录的 `multi_object_independence_status` 是 `inconclusive_pending_paired_single_control`；`single_controls_missing=[]` 并不代表代码完成了逐实例匹配校验。
4. **F8 是真实的保留预期失败。** FP1 A/A-swapped 中仅目标炉头开，另一炉头关，但两容器从室温变热。不能删掉这个观测；也不能未经隔离就断言另一个炉头被旋钮错误打开。

## 45 个模板逐项核对

下面两场景单元格保留原程序状态及本次可读的实测结果。最后一列才是对原设计预期的审计判断。构造失败的条目不计作机制反例；参考答案只是模拟器实测参考，不等于图片足够回答。

| # | 模板及具体过程 | FloorPlan1 | FloorPlan2 | 原预期核对与原因 |
|---:|---|---|---|---|
'@
$lines=[Collections.Generic.List[string]]::new();$lines.Add($head)
$human=@{observed_supported='程序支持';inconclusive='程序无结论';setup_unavailable='初态未完成';observed_counterexample='程序标反例';probe_error='探针报错'}
$index=0;$structured=[Collections.Generic.List[object]]::new()
function Cell([string]$Text){return $Text.Replace('|','\|').Replace("`n",' ').Replace("`r",' ')}
foreach($case in $cases){
    $index++;if(-not $judgements.ContainsKey($case)){throw "Unreviewed template: $case"}
    $pair=@($items|Where-Object{($_.id -split '/')[-3] -eq $case});$cells=@();$sceneRecords=@()
    foreach($scene in @('FloorPlan1','FloorPlan2')){
        $entry=@($pair|Where-Object{($_.id -split '/')[-2] -eq $scene})[0]
        $answers=(@($entry.presentation.questions|ForEach-Object{$_.answer_text}) -join ' ')
        $label=$human[[string]$entry.status];$relative=[IO.Path]::GetRelativePath([IO.Path]::GetDirectoryName($out),(Join-Path $source $entry.id)).Replace('\','/')
        $cells+="[$label]($relative)：$(Cell $answers)"
        $sceneRecords+=@{scene=$scene;raw_status=$entry.status;record_path=Join-Path $source $entry.id;recorded_answers=@($entry.presentation.questions)}
    }
    $title=[string]$pair[0].presentation.title
    $lines.Add("| $index | ``$case``<br>$(Cell $title) | $($cells[0]) | $($cells[1]) | $(Cell $judgements[$case]) |")
    $structured.Add(@{case_id=$case;description=$title;design_audit=$judgements[$case];scenes=$sceneRecords})
}
$tail=@'

## 图片抽查和捕获工作流问题

主任务实际看了以下三张：

- `f3_toaster_multiple/FloorPlan2/rgb/0001_all_targets_inside_before_activation_rgb.png`：厨房远景，烤面包机及两片面包没有清晰可辨的证据。
- `F7_returned/FloorPlan2/rgb/0001_before_pickup_container_rgb.png`：同一厨房远景，不能独立辨认目标盘子上苹果的事件前关系。
- `f6_fill_then_empty/FloorPlan2/rgb/0001_history_after_fill_rgb.png`：杯子在远处，不能判断杯口液体或装水是否发生。

并行审阅者另抽查了八张，明确范围如下：

- `f5_clean_empty_water_on/FloorPlan1/rgb/0008_attempt_final_rgb.png`：水槽/目标碗不够清晰，不能确认液面、污渍或流水接触。
- `f6_initially_empty/FloorPlan1/rgb/0008_attempt_final_rgb.png`：画面没有清楚展示咖啡机与杯口液体。
- `F7_retained/FloorPlan2/rgb/0003_trajectory_0003_pass_0_rgb.png`：拿起后的盘子和绿色苹果较清楚；仅支持该时刻共现，不能替代事件前基线或完整位移对照。
- `F8_control_A/FloorPlan1/rgb/0013_target_on_rgb.png`：冰箱门/把手近景，不能确认炉头与旋钮操作。
- `F9_matched_time/FloorPlan1/rgb/0010_native_target_physics_400_steps_rgb.png`、`F10_nested_heat/FloorPlan1/rgb/0002_attempt_final_rgb.png`、`F10_nested_carry/FloorPlan1/rgb/0001_attempt_final_rgb.png`、`F11_redundant_support/FloorPlan1/rgb/0001_attempt_final_rgb.png`：审阅者记录为遮挡/冰箱门近景，不能据此证明各自目标属性。

上述路径均相对于 `observations/attempts/`。部分审阅图在不同机制/时刻画面相同，不能仅据重复就认定渲染缓存有错。执行源码的 `ProbeContext.capture` 保存当时的 `last_event`；它不按当前被测对象/属性自动选择证据视角。初始化、布置、原生交互与 Pass 后就直接截图，会产生有截图但目标在视野外的情况。

所以这批目前是**机制日志与候选取景素材**，不是全部通过视觉审核的正式题。当前网页已经添加每条具体过程、候选输入/问题、实测参考答案和每张截图用途，方便继续人工判断。温度等属性在普通 RGB 下可能本来就不可见；需要补公开且已验证的规则、读数或其它模型可用证据，不能只因为 metadata 有标签就要求模型回答。

## 后续困难组应该怎么处理

- **C：可以保留机制思路，重新做好模型可用证据。** 当前液体门控及两个历史版本有正例；杯口、液面和放入事件的取景仍需做好。它是单条件诊断基线，是否能难倒模型尚未测。
- **D：先用已成功的单层当前关系/世界位移，不加未经验证的嵌套。** FP2 三条件有清楚元数据对照；要让图像也能区分拿盘前后与苹果归属，避免依赖拾取后的缺失 parent 字段。
- **E：保留开关映射，热影响边界按场景继续校准。** 不能先给 FP1 A 条件另一容器保持室温的 Gold；先定位双容器升温的来源。
- **A：暂不照原三土豆复杂例直接生成。** 单土豆受热成立，但 F4 热—冷熟度历史、多对象容量和独立性、完整边界等前提没凑齐。
- **B：暂不把开水四格当已建立的稳定规则。** 先落实实际流水接触、事件时初态，再验证属性交叉；多对象版本还缺 F3。
- **F10/F11 扩展暂缓当作已知规则使用。** 两者是构造未成，不是已被反驳；只有得到有效干预后才讨论支持/否定。

本轮不需要重新安装环境，也不应为照片问题无差别重跑全部 45 模板。先区分修代码、改不合法的事件顺序、改摆放候选、补条件对照和规划视角这几种不同工作。它们不是一次相同操作能修复的事情。

## 可以直接带回设计对话的一段话

> Step 31 已完成45个基础探测模板在两个场景中的尝试，但并非45个机制均验证成功。咖啡机当前液体门控、单层承载随行、部分设备加热/熟化，以及有限固定推进关火对照有实测支持。完整作用边界、多对象独立性、热—冷熟度分离、流水四格、嵌套组合和双来源支持仍有缺口。需要改掉运行中微波炉可直接开门放物的事件假设；不能在FloorPlan1部分炉头条件下预设另一容器保持室温。温度字段别名错误、场景构造失败和图片证据不足分别处理，不当成机制反例。先保留C和单层D的机制基础；E收窄到已校准条件；A/B/F10/F11按缺失前提补验证后再设计困难题。机制元数据证据与视觉可答性分别验收，本批尚无模型难度结论。
'@
$lines.Add($tail);$lines.Add("`n原始运行根目录：``$source``。完整执行源码位于其 ``source/``，各场景结果链接已放在45行表中。报告不改写原始状态或来源数据。")
[IO.File]::WriteAllText($out,($lines -join "`n"),[Text.UTF8Encoding]::new($false))
$jsonPath=[IO.Path]::ChangeExtension($out,'.json');[IO.File]::WriteAllText($jsonPath,(ConvertTo-Json -InputObject @{templates=$structured.ToArray();template_count=$cases.Count;attempt_count=$items.Count;all_hypotheses_confirmed=$false;all_images_visually_reviewed=$false} -Depth 30),[Text.UTF8Encoding]::new($false))
Write-Output $out
