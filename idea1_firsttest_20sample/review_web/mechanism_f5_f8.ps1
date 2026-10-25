function Get-ReviewF5F8($Context) {
    $result = $Context.result
    $case = [string]$Context.case_id
    $scene = [string]$Context.scene
    $id = [string](RV-Get $result 'fact_id' '')
    if ($id -notin @('F5','F6','F7','F8')) { return $null }

    $captures = @($Context.captures)
    $labels = @($captures | ForEach-Object { [string](RV-Get $_ 'label' '') })
    $stageNotes = [ordered]@{}
    foreach ($label in $labels) {
        if (-not $label) { continue }
        $note = switch -Regex ($label) {
            '^scene_initial$' { '场景刚载入时的基线：核对对象身份、初始状态和初始位置；不能代替动作前的即时状态。'; break }
            '^pre_water_source_and_contact$' { '水源开启/关闭或放置操作前的基线；确认水碗最初的脏污、液体属性和位置。'; break }
            '^water_source_off_before_contact$' { '控制条件：水龙头关闭后才放碗，用来检查仅仅放进水槽是否造成变化。'; break }
            '^after_water_source_on_before_contact$' { '水源开启但尚未接触水槽前的检查点；区分「水源已开」与「容器已接触水」。'; break }
            '^history_after_empty$' { '倒空操作后的历史点；检查清空后是否仍保留此前注液/清洁的信息。'; break }
            '^history_after_fill$' { '注液操作后的历史点；与之后倒空状态对照，判断顺序是否改变结果。'; break }
            '^after_pickup_before_coffee_placement$' { '拿起容器后的瞬间；核对被拿起者与持有状态，之后的位置变化需结合此图比较。'; break }
            '^immediately_before_coffee_placement$' { '咖啡机放置前的即时状态；确认咖啡机开关/液体初态和容器位置关系。'; break }
            '^before_pickup_container$' { '拿容器前的基线，用来比较拿起前后容器及内部物体的位置。'; break }
            '^pickup_container$' { '拿起容器后的检查点；若父容器字段消失，需用后续世界坐标位移判断物体是否随行。'; break }
            '^target_on$' { '旋钮操作后目标炉头开启的检查点；核对本次开关对应的炉头。'; break }
            '^target_off$' { '另一旋钮操作后的检查点；用于核对目标炉头能否单独关闭以及无关炉头是否保持。'; break }
            '^trajectory_.*_pass_0$' { '动作后最早记录点；辨认即时变化。'; break }
            '^trajectory_.*_pass_1$' { '动作后短间隔记录点；与即时点比较变化是否已出现。'; break }
            '^trajectory_.*_pass_4$' { '动作后早期记录点；观察状态是否开始延续或变化。'; break }
            '^trajectory_.*_pass_12$' { '动作后中期记录点；与早期阶段比较持续效应。'; break }
            '^trajectory_.*_pass_36$' { '动作后较晚记录点；检查效应是否延续或回落。'; break }
            '^trajectory_.*_pass_72$' { '动作后更晚记录点；只用于对应长时段轨迹。'; break }
            '^trajectory_.*_pass_120$' { '动作后最长记录点；检查长时段状态，不代表等同物理时间的其它尝试。'; break }
            '^attempt_final$' { '本次尝试最终状态；与动作前及中间快照对照，不能单独确定变化发生机制。'; break }
            default { '该阶段快照：与前后阶段对照，确认本次尝试中对象状态或位置的变化时点。' }
        }
        $stageNotes[$label] = $note
    }

    $checks = @(RV-FindChecks $result '.*')
    $status = [string](RV-Get $result 'status' 'unknown')
    $answerStatus = if ($status -in @('observed_supported','observed_counterexample','inconclusive')) { 'observed' } else { 'undetermined' }
    $observed = @()
    foreach ($check in $checks) {
        $name = [string](RV-Get $check 'name' '检查')
        $passed = RV-Get $check 'passed' $null
        $detail = RV-Get $check 'detail' @{}
        $state = if ($null -eq $passed) { '未记录' } elseif ($passed) { '通过' } else { '未通过' }
        if ($id -eq 'F5' -and $name -eq 'dirty_and_liquid_match_water_source_condition') {
            $final = RV-Get $detail 'final' @{}
            $initialState = RV-Get $detail 'initial' @{}
            $finalLiquid = RV-Get $final 'fillLiquid' $null
            $finalLiquidText = if ($null -eq $finalLiquid) { 'null（无液体）' } else { [string]$finalLiquid }
            $observed += ("$state；放置前水源开启=$(RV-Get $detail 'water_on' '未记录')；碗状态 isDirty $(RV-Get $initialState 'isDirty' '未记录')→$(RV-Get $final 'isDirty' '未记录')，isFilledWithLiquid $(RV-Get $initialState 'isFilledWithLiquid' '未记录')→$(RV-Get $final 'isFilledWithLiquid' '未记录')，fillLiquid=$finalLiquidText。")
        } elseif ($id -eq 'F6' -and $name -eq 'empty_mug_filled_or_existing_liquid_preserved') {
            $changes = RV-Get (RV-Get $result 'observation' @{}) 'field_changes' @{}
            $filledChange = RV-Get $changes 'isFilledWithLiquid' @{}
            $liquidChange = RV-Get $changes 'fillLiquid' @{}
            $observed += ("$state；咖啡机放置前 isFilledWithLiquid=$(RV-Get $filledChange 'before' '未记录')、fillLiquid=$(RV-Get $liquidChange 'before' '未记录')；之后 isFilledWithLiquid=$(RV-Get $filledChange 'after' '未记录')、fillLiquid=$(RV-Get $liquidChange 'after' '未记录')。")
        } elseif ($id -eq 'F7' -and $name -eq 'condition_specific_world_and_relative_motion') {
            $cond = [string](RV-Get $detail 'condition' '未记录')
            $metrics = @(RV-Get $detail 'metrics' @())
            $first = if ($metrics.Count) { $metrics[0] } else { @{} }
            $beforeRelation = RV-Get $detail 'parent_relation_before_event' '未记录'
            $afterRelation = RV-Get $detail 'parent_relation_after_event' '未记录'
            $observed += ("$state；条件=$cond；事件前 parent relation=$beforeRelation、拿起后字段=$afterRelation；轨迹首个记录点容器位移=$(RV-Get $first 'container_displacement_m' '未记录') m，子物体位移=$(RV-Get $first 'child_displacement_m' '未记录') m，两者位移差=$(RV-Get $first 'child_vs_container_displacement_error_m' '未记录') m。")
        } elseif ($id -eq 'F8' -and $name -in @('object_on_target_burner_became_hot','other_container_remained_room_temp','native_mapping_target_burner_toggled','both_burners_off_after_target_off')) {
            if ($name -eq 'native_mapping_target_burner_toggled') {
                $mapping = @(RV-Get $detail 'metadata_mapping_candidate' @()) -join ' → '
                $states = RV-Get $detail 'burner_states_after_on' @{}
                $observed += ("$state；原生记录的旋钮→炉头映射候选为 $mapping；开启后 burner_a=$(RV-Get $states 'burner_a' '未记录')、burner_b=$(RV-Get $states 'burner_b' '未记录')。")
            } elseif ($name -eq 'both_burners_off_after_target_off') {
                $states = $detail
                $observed += ("$state；关闭操作后 burner_a=$(RV-Get $states 'burner_a' '未记录')、burner_b=$(RV-Get $states 'burner_b' '未记录')。")
            } else {
                $observed += ("$state；容器 $(RV-Get $detail 'target_container' (RV-Get $detail 'other_container' '未记录'))：$(RV-Get $detail 'before' '未记录')→$(RV-Get $detail 'after_72_pass' (RV-Get $detail 'after' '未记录'))。")
            }
        } else {
            $observed += ("$state：$name。")
        }
    }
    if ($checks.Count -eq 0) { $observed = @("本次状态为 $status；没有可用的机制检查项。不得从空检查表推断目标机制成立或失败。") }

    $initial = ''
    $steps = @()
    $purpose = ''
    $questions = @()
    $visual = @()
    $draft = ''
    switch ($id) {
        'F5' {
            $condition = RV-Get (RV-Get $result 'observation' @{}) 'condition' @{}
            $dirty = RV-Get $condition 'initially_dirty' '未记录'
            $filled = RV-Get $condition 'initially_filled_with_water' '未记录'
            $on = RV-Get $condition 'water_source_on' '未记录'
            $initial = "在 $scene 中，以碗为目标；探测记录的初态为 dirty=$dirty、filled_with_water=$filled，水源条件为 on=$on。"
            $steps = @("识别本次场景中的 Faucet 水龙头、SinkBasin 水槽盆和 Bowl 目标碗；起始格为$(if($dirty){'脏'}else{'净'})×$(if($filled){'有水'}else{'空'})，本次水源$(if($on){'开启'}else{'关闭'})。",'读取 scene_initial 与 pre_water_source_and_contact，确认初态和目标碗身份。','检查 after_water_source_on_before_contact 或 water_source_off_before_contact：这些图是在碗放入之前记录水源条件。','检查放置后的 bowl_in_sink_relation_after_native_put 是否建立碗→SinkBasin 的当前父关系；它证明位置/关系，不证明流水接触。','逐段对照 Pass 0、1、4、12、36 和 attempt_final 中 isDirty、isFilledWithLiquid、fillLiquid；和相同脏净/有水初态的水源关闭控制比较。','记住每张截图都需单独目视审核，不能从 metadata 推断图片看得清水龙头、液面或污渍。')
            $purpose = '检验水源条件与碗是否接触水的组合，是否改变「是否装水」和「是否变脏」两项状态；当前数据只支持各自记录的元数据检查。水源开启且碗进入水槽盆并不能单独证明发生了水接触。'
            $questions = @(
                @{id='q1';text='水龙头处于本次条件、碗被放进水槽后，碗最后是空的还是装着水？';answer_text=($observed | Where-Object {$_ -match 'fillLiquid='} | Select-Object -Last 1);answer_basis='使用本次 simulator 最终液体字段作事实参考；图像能否看见液面另行审核。';answer_status=$answerStatus},
                @{id='q2';text='碗在这次操作前后，清洁状态发生变化了吗？';answer_text=($observed | Where-Object {$_ -match 'isDirty'} | Select-Object -Last 1);answer_basis='使用本次 simulator 前后清洁字段作事实参考；不据此声称图片污渍可读。';answer_status=$answerStatus},
                @{id='q3';text='碗放在水槽盆中时，有没有证据显示流水确实碰到了碗？';answer_text='本次探测没有单独测量水流与碗的接触。';answer_basis='记录了水源开关和碗与 SinkBasin 的关系，但没有 contact observation。';answer_status='undetermined'}
            )
            $draft = "$initial`n过程记录：尝试按本次记录改变水源条件并将碗放入水槽区域，随后记录多个等待阶段。上述是供审阅者确认的输入草案，不是历史模型请求；不包含目标最终状态。"
            $visual = @('人工核实水龙头、目标碗与水槽盆的画面占比和遮挡；本次状态 metadata 可读，但不是图像可读性结论。','从碗口看水面、液体颜色和污渍标记；水反光或碗太远时标记不可判。','比较 before/after 中相同视角能否分辨真实视觉变化；不能把脚本的装水布尔值说成图中可见。')
        }
        'F6' {
            $condition = RV-Get (RV-Get $result 'observation' @{}) 'condition' @{}
            $history = [string](RV-Get $condition 'history' '未记录')
            $initial = "在 $scene 中，以同一个 Mug 杯和 CoffeeMachine 咖啡机检验事件时门控；本次实际历史条件为 $history。"
            $steps = @("识别 FloorPlan 场景中的 CoffeeMachine 咖啡机、Mug 杯及 CounterTop 台面；本次历史条件为 $history。",'按 history_after_empty、history_after_fill（若存在）逐个确认 EmptyLiquidFromObject/FillObjectWithLiquid 的动作成功及实际状态，不从 case 名称代替动作结果。','核对 immediately_before_coffee_placement 的杯子事实；以本次实际值回答杯内有水/为空。','将同一杯放入已开启的咖啡机；检查原生 PutObject 成功，并记录 before_put 与放置瞬间的状态。','对照 Pass 0、1、4、12、36 和 attempt_final，读取 isFilledWithLiquid 与 fillLiquid；分别回答空杯变咖啡、有水杯保留水与否。','检查截图是否实际看清咖啡机、杯子、液面和开关；state metadata 与图像可读性分开记录。')
            $purpose = '比较先注液再倒空、先倒空再注液、初始为空/已装水等条件下，后续咖啡机相关效果是否遵循所需门控。仅凭顺序或当前元数据不能推定咖啡机制已被触发。'
            $changesForGold = RV-Get (RV-Get $result 'observation' @{}) 'field_changes' @{}
            $goldFilled = RV-Get (RV-Get $changesForGold 'isFilledWithLiquid' @{}) 'after' $null
            $goldLiquid = RV-Get (RV-Get $changesForGold 'fillLiquid' @{}) 'after' $null
            $goldBefore = RV-Get (RV-Get $changesForGold 'fillLiquid' @{}) 'before' $null
            $goldBeforeText = if ($null -eq $goldBefore) { 'null（空杯）' } else { [string]$goldBefore }
            $goldLiquidText = if ($null -eq $goldLiquid) { 'null（无液体）' } else { [string]$goldLiquid }
            $historyNarration = switch ($history) { 'empty' {'杯子初始为空'} 'water_filled' {'杯子初始有水'} 'empty_then_fill' {'先清空杯子，再给杯子装水'} 'fill_then_empty' {'先给杯子装水，再将水倒空'} default {'杯子的历史顺序未记录'} }
            $liquidNarration = if ($goldLiquid -eq 'coffee') {'最后杯中是咖啡'} elseif ($goldLiquid -eq 'water') {'最后杯中仍是水'} elseif ($goldFilled -eq $false) {'最后杯子为空'} else {'最后液体状态未测得'}
            $goldF6 = "$historyNarration；放入已开启的咖啡机前 fillLiquid=$goldBeforeText；放入后 isFilledWithLiquid=$goldFilled、fillLiquid=$goldLiquidText，因此$liquidNarration。"
            $questions = @(
                @{id='q1';text='杯子经历本次过程后，放进开启的咖啡机之前里面有什么？取出后里面有什么？';answer_text=$goldF6;answer_basis='直接回答本次 simulator 记录的咖啡机放置前后液体状态。';answer_status=$answerStatus},
                @{id='q2';text='咖啡机最后把什么液体留在杯中？';answer_text=$goldF6;answer_basis='本题 reference 来自该尝试 observation.field_changes 的实际状态值。';answer_status=$answerStatus},
                @{id='q3';text='咖啡机放杯前，杯子是如何到达当时的液体状态的？';answer_text="$historyNarration。";answer_basis='按该次尝试记录的历史条件作答。';answer_status=$answerStatus}
            )
            $draft = "$initial`n过程记录：$historyNarration。接着检查本次日志中咖啡机开启后的放杯步骤；将空杯或已有水杯放入咖啡机，读取其后续状态。该草案是重建的审阅输入，不是历史原始模型输入，也不带最终液体答案。"
            $visual = @('人工确认图片是否确实看见 CoffeeMachine 和同一只 Mug；某些相机帧可能只拍到房间/炉灶。','确认杯口、液面颜色是否足以区分水、咖啡与空杯；记录中有 fillLiquid 不代表截图能看出咖啡。','判断 coffee-machine 开启标志和杯子是否在内部/有效位置；截图清晰度与 simulator 参考值分别给结论。')
        }
        'F7' {
            $initial = "在 $scene 中，检查拿起一只盘子时苹果是否按事件前的当前承载关系随盘移动。"
            $conditionF7 = [string](RV-Get (RV-Get $result 'observation' @{}) 'condition' '未记录')
            $historyF7 = switch ($conditionF7) { 'retained' {'苹果一直放在盘子上'} 'removed' {'苹果先从盘子取下并留在台面'} 'returned' {'苹果先从盘子取下，随后重新放回盘子'} default {'苹果的事件前承载历史未记录'} }
            $steps = @("识别本次 scene 中 Plate 盘子和 Apple 苹果（或本条 role binding 中的具体容器/内容物），先核对 before_pickup_container 时的世界位置与当前包含关系。",'根据 case 标记区别 retained、removed、returned；逐条检查动作台账中移出/重新放回/持续留在盘上的操作成功，不按 case 名称直接认定。','在 pickup_container 确认盘子确实被拿起，并记下盘子与苹果各自的初始位置。','比较 Pass 0、1、4、12、36 和 attempt_final 的 child/container 位移距离与相对位置变化；以两者是否共同位移回答随行。','parentReceptacles 在 held object 上消失属于 metadata 约定风险，不能单独当作脱离；若setup placement失败且无位置轨迹，答案为未测量。')
            $purpose = '检验当前承载关系和拿起容器后，内容物是否随容器一起移动；用相对轨迹判别，避免把 parentReceptacles 元数据缺失当成没有携带。'
            $questions = @(
                @{id='q1';text='拿起盘子时，苹果是否跟着盘子移动？';answer_text=($observed | Where-Object {$_ -match '容器位移='} | Select-Object -Last 1);answer_basis='用苹果和盘子的实际世界位移判断；setup/probe 失败则不提供答案。';answer_status=$answerStatus},
                @{id='q2';text='拿盘子前，苹果当时是在盘子上、已移走，还是后来放回？';answer_text=("$case；" + ($observed | Where-Object {$_ -match '条件='} | Select-Object -Last 1));answer_basis='依据事件前成立的关系与实际 setup 操作记录；case 标签本身不是证据。';answer_status=$answerStatus}
            )
            $draft = if ($answerStatus -eq 'undetermined') { "$initial`n本次 attempt 未能建立要求的摆放条件，无法把它写成已完成的场景过程。" } else { "$initial`n已知过程：$historyF7。随后拿起盘子，并观察盘子与苹果的位置变化。" }
            $visual = @('人工判断视图是否同时显示手持盘子、苹果及两者相对位置；检查实际图中手持盘子可见时苹果是否仍稳定可辨。','比较拿起前后苹果是否相对盘面滑动、掉落或被遮挡；RGB图像的可读性独立于世界坐标金标准。','本次抽查图 `F7_retained/FloorPlan2/trajectory_0003_pass_0` 中盘子和苹果均清楚可见，盘子处于手持状态；该帧不能代替事件前基线图。')
        }
        'F8' {
            $initial = "在 $scene 中，检查 Stove 炉灶的两个 burner 和各自的 StoveKnob；两个探测容器按本次记录的位置摆放。"
            $swapText = if ($case -match 'swapped') { '本次对调两个容器位置后复测。' } else { '本次使用原容器位置复测。' }
            $steps = @('识别 Stove 炉灶上的两个 burner、各自相邻的 StoveKnob，以及两个探测容器的当前摆位。','读取本次实际旋钮操作与 toggle 记录；检查开启后两炉头的开关值，再核对关闭后的两炉头状态。','分别记录两个容器在操作前及等待 72 pass 后的温度。',"$swapText 比较对调位置前后的目标映射和温度变化。",'若另一容器也升温，保留该实测结果并注明其原因未隔离；不可宣称温度作用已隔离。')
            $purpose = '验证旋钮操作是否只改变对应炉头，并通过交换/对照条件检查对象映射是否稳健。若另一容器（或其他炉头）也热，不能据此单独证明热量映射已被隔离。'
            $questions = @(
                @{id='q1';text='转动目标旋钮后，两个炉头各自是开着还是关着？';answer_text=($observed | Where-Object {$_ -match '映射候选'} | Select-Object -Last 1);answer_basis='按 native toggle 的目标旋钮 ID、目标炉头 ID 和两炉头实际状态作答。';answer_status=$answerStatus},
                @{id='q2';text='加热等待后，两个位置上的容器各自变热了吗？';answer_text=(($observed | Where-Object {$_ -match '容器 .*→'}) -join ' ');answer_basis='各容器 temperature 前后状态是 metadata reference；图片热度可读性不由此确定。';answer_status=$answerStatus}
            )
            $draft = "$initial`n请操作本次指定的 StoveKnob，观察它对哪一个炉头起作用；再把两个容器交换位置，重复操作并观察结果。"
            $visual = @('抽查帧 F8_control_A/FloorPlan1/target_on 显示的是冰箱门特写，没有炉头或旋钮；不能用于视觉识别映射。','要求审核帧能同时看见两旋钮、两炉头、两个容器的摆位；若各阶段只能局部看见，不能凭拼接臆造联合可见性。','RGB视觉能否判断 burner 开/关与容器变热另行记录；当前 metadata 温度不可读性不影响参考状态答案。')
        }
    }
    return @{
        title = switch ($id) { 'F5' {'水龙头条件下碗是否实际接触水'} 'F6' {'倒空与注液顺序对咖啡门控的影响'} 'F7' {'拿起容器后内部物体是否随行'} 'F8' {'旋钮与对应炉头的独立映射'} }
        initial = $initial
        steps = $steps
        purpose = $purpose
        observed = $observed
        draft_context = $draft
        questions = $questions
        visual_requirements = $visual
        stage_notes = $stageNotes
    }
}
