function Get-ReviewF9F11($Context) {
    $result = RV-Get $Context 'result' @{}
    $fact = [string](RV-Get $result 'fact_id' '')
    if ($fact -notin @('F9','F10','F11')) { return $null }

    $case = [string](RV-Get $result 'case_id' (RV-Get $Context 'case_id' ''))
    $scene = [string](RV-Get $result 'scene' (RV-Get $Context 'scene' '未知场景'))
    $status = [string](RV-Get $result 'status' 'unknown')
    $checks = @(RV-Get $result 'checks' @())
    $observation = RV-Get $result 'observation' @{}
    $captures = @(RV-Get $Context 'captures' @())
    $stageNotes = @{}
    foreach ($capture in $captures) {
        $label = [string](RV-Get $capture 'label' '')
        if (-not $label) { continue }
        $purpose = switch -Regex ($label) {
            '^scene_initial$' { '场景重置后的基线画面：核对本轮房间与初始布置。'; break }
            '^attempt_final$' { '本轮最后留存画面：展示实际停止时的场景状态；不能单独证明未完成的机制目标。'; break }
            '^microwave_open_for_nested_setup$' { '微波炉打开后的嵌套布置中间画面：核查容器是否可放入及其可见位置。'; break }
            '^native_target_heat_source_on$' { '目标组加热源开启后：确认实验对象进入热源预处理阶段。'; break }
            '^native_target_precondition_' { '目标组预热期间采样：确定开始等时观察前对象是否已达到 Hot。'; break }
            '^native_target_pause_auto_sim$' { '目标组关闭自动推进后的画面：为固定物理步数观察建立边界。'; break }
            '^native_target_target_source_off$' { '目标组关闭热源后的画面：记录撤去来源后的状态起点。'; break }
            '^native_target_physics_' { '目标组固定物理步数采样：记录关闭来源后按指定物理步数观察到的状态。'; break }
            '^native_target_unpause_auto_sim$' { '目标组恢复自动推进后的画面：显示固定步数观察结束后的状态。'; break }
            '^native_control_heat_source_on$' { '对照组加热源开启后：与目标组建立相同的预热流程。'; break }
            '^native_control_precondition_' { '对照组预热期间采样：核实撤去来源前的热状态。'; break }
            '^native_control_pause_auto_sim$' { '对照组暂停自动推进：使其后固定物理步数观察有明确起点。'; break }
            '^native_control_physics_' { '对照组固定物理步数采样：比较来源仍保留时对象状态。'; break }
            '^native_control_unpause_auto_sim$' { '对照组恢复自动推进：记录该臂固定步数观察的收尾状态。'; break }
            '^wall_target_heat_source_on$' { '按 Pass 轮数实验的目标组加热源开启画面。'; break }
            '^wall_target_precondition_' { '目标组预热采样：核实 Pass 计数比较开始前的热状态。'; break }
            '^wall_target_target_source_off$' { '目标组关闭热源：记录按 Pass 轮数比较的撤源起点。'; break }
            '^wall_target_wallcount_' { '目标组 Pass 轮数采样：用于记录经过的调用轮数和对象温度，不代表等量物理时间。'; break }
            '^wall_control_heat_source_on$' { '按 Pass 轮数实验的对照组开启加热源。'; break }
            '^wall_control_precondition_' { '对照组预热采样：核实 Pass 轮数比较前的对象状态。'; break }
            '^wall_control_wallcount_' { '对照组 Pass 轮数采样：显示经过的调用轮数与状态；该量不等同于物理时间。'; break }
            default { '该步骤留存的场景画面；请结合本轮操作记录核对其发生时点。' }
        }
        $stageNotes[$label] = $purpose
    }

    $common = @{
        stage_notes = $stageNotes
        visual_requirements = @('保留每个实际 capture 的时间顺序和原始标签；不要把不同 reset 的画面拼成单条连续轨迹。','画面用于核对可见场景及拍摄时点；物体属性结论须同时依据记录的元数据检查。')
    }

    if ($fact -eq 'F9') {
        # The runner stores per-arm check evidence in result.checks, while the
        # compact paired contrasts and epistemic boundary live in observation.
        $nativeCheck = $null
        foreach ($check in $checks) {
            if ([string](RV-Get $check 'name' '') -eq 'native_physics_time_control_completed') { $nativeCheck = $check; break }
        }
        $observation = RV-Get $result 'observation' @{}
        $contrast = RV-Get $observation 'native_fixed_time_contrast' $null
        $wall = RV-Get $observation 'wallcount_contrast' $null
        $clockUnverified = [bool](RV-Get (RV-Get $observation 'interpretation' @{}) 'attribute_clock_unverified' $true)
        $supported = ($status -eq 'observed_supported' -and $null -ne $nativeCheck -and $null -ne $contrast)
        $observed = if ($supported) {
            @("$scene：固定物理步数臂中，目标组撤去热源后 Kettle 温度为 $(RV-Get $contrast 'target_final' '未记录')；保留来源的对照组为 $(RV-Get $contrast 'control_final' '未记录')。记录的每臂请求时长为 $(RV-Get $contrast 'requested_simulated_seconds_each' '未记录') 秒。",
              "另一个 Pass 轮数比较中目标组为 $(RV-Get $wall 'target_final' '未记录')、对照组为 $(RV-Get $wall 'control_final' '未记录')；Pass 数分别为 $(RV-Get $wall 'target_passes' '未记录') 与 $(RV-Get $wall 'control_passes' '未记录')。这部分是调用轮数/墙钟流程对照，不是物理时间等价证据。",
              "结果记录明确标记 attribute_clock_unverified=$clockUnverified；本轮只支持记录到的对象温度对照，不证明属性时钟单位或普遍冷却规律。")
        } else {
            @("$scene：没有通过 native_physics_time_control_completed 检查；本轮状态为 $status。不能把留存画面当成成功完成的固定时间对照。")
        }
        $steps = @('重置到该场景，选择可由 StoveKnob 控制的 StoveBurner，并将 Kettle 放置到该燃烧器上。','按记录流程给目标组与对照组分别预热；目标组关闭热源，对照组保持来源条件。','在暂停自动推进后，各组按记录的固定物理步数采样对象温度；再恢复自动推进。','单独进行 Pass 轮数臂，记录每轮调用及最后温度；该臂用于比较调用/墙钟推进，不解释为物理时间。')
        return (@{
            title = 'F9｜固定物理步数下的热源撤除对照'
            initial = "$scene 场景内有可操作炉灶旋钮、炉灶加热圈与水壶。每个场景尝试都从独立重置开始；检查目标是比较撤去来源与保留来源时记录到的水壶温度。"
            steps = $steps
            purpose = '区分固定物理步数条件下的来源撤除对照，与按 Pass 调用轮数推进的对照，并审查能否据此谈属性时钟。'
            observed = $observed
            draft_context = "在 $scene 场景中，记录了 StoveKnob 控制 StoveBurner、Kettle 位于该 burner 的实验。可见/已执行流程包括目标组预热、撤去热源后的固定物理步数采样，以及保留来源对照；另有独立的 Pass 轮数采样。Pass 计数不等于物理时间。当前记录没有验证 ObjectTemperature 属性时钟的单位。"
            questions = @(@{id='f9_q1';text='在这次场景记录里，撤去热源与继续保留热源后，水壶温度分别怎样变化？Pass 轮数比较是否呈现相同差异？';answer_text=if($supported){"固定物理步数（每组 400 步 × 0.01 秒）比较：撤源目标组 $(RV-Get $contrast 'target_final' '未记录')，来源保留对照组 $(RV-Get $contrast 'control_final' '未记录')。独立 Pass 轮数比较：目标组 $(RV-Get $wall 'target_final' '未记录')、对照组 $(RV-Get $wall 'control_final' '未记录')。"}else{'未完成可解释的固定物理步数比较，不能据此作答。'};answer_basis='observation.native_fixed_time_contrast and observation.wallcount_contrast';answer_status=if($supported){'observed'}else{'undetermined'}})
        } + $common)
    }

    if ($fact -eq 'F10') {
        $kind = if ($case -match 'carry') {'搬运'} elseif ($case -match 'heat') {'加热'} else {'清洗'}
        $error = [string](RV-Get $result 'error' '')
        if (-not $error) { $error = [string](RV-Get $observation 'setup_error' '') }
        $plan = RV-Get $observation 'construction_plan' $null
        if ($null -eq $plan) {
            foreach ($check in $checks) {
                if ([string](RV-Get $check 'name' '') -eq 'construction_plan') { $plan = RV-Get $check 'detail' $null; break }
            }
        }
        $selected = RV-Get $plan 'selected_roles' @{}
        $selectedCount = @($selected.Keys).Count
        $displayRoles = $selected
        if ($selectedCount -eq 0) {
            $attemptsForDisplay = @(RV-Get $plan 'attempts' @())
            if ($attemptsForDisplay.Count) { $displayRoles = RV-Get $attemptsForDisplay[-1] 'roles' @{} }
        }
        $roleNames = @{source='热源/水源';outer='外层容器';inner='内层容器';content='内容物';basin='水槽盆';support='台面'}
        $actualRoles = @{}
        foreach ($alias in @($displayRoles.Keys)) {
            $entry = RV-Get $displayRoles $alias @{}
            $type = [string](RV-Get $entry 'objectType' '')
            if (-not $type) { $type = ([string](RV-Get $entry 'objectId' '') -split '[|_]')[0] }
            if ($type) { $actualRoles[$alias] = RV-ObjectName $type }
        }
        $objects = if ($actualRoles.Count) { (@($actualRoles.Values | Select-Object -Unique) -join '、') } elseif ($kind -eq '加热') {'微波炉、碗、马铃薯'} elseif ($kind -eq '清洗') {'水龙头、水槽盆、碗、盘子'} else {'盘子、碗、苹果'}
        $order = @(RV-Get $plan 'placement_order' @())
        $orderText = [System.Collections.Generic.List[string]]::new()
        foreach ($edge in $order) {
            $parts = ([string]$edge -split '->', 2)
            if ($parts.Count -ne 2) { continue }
            $child, $parent = $parts[0], $parts[1]
            $childName = if ($actualRoles.ContainsKey($child)) { $actualRoles[$child] } elseif ($roleNames.ContainsKey($child)) { $roleNames[$child] } else { $child }
            $parentName = if ($actualRoles.ContainsKey($parent)) { $actualRoles[$parent] } elseif ($roleNames.ContainsKey($parent)) { $roleNames[$parent] } else { $parent }
            $verb = if ($parent -in @('support','basin')) {'放到'} else {'放进'}
            $orderText.Add("将$childName$verb$parentName")
        }
        $attemptNotes = [System.Collections.Generic.List[string]]::new()
        foreach ($attempt in @(RV-Get $plan 'attempts' @())) {
            $trial = [string](RV-Get $attempt 'trial' '?')
            $why = [string](RV-Get $attempt 'failure' '')
            foreach ($placement in @(RV-Get $attempt 'placements' @())) {
                foreach ($path in @(RV-Get $placement 'paths' @())) {
                    if ((RV-Get $path 'status' '') -eq 'failed') { $why += "；$(RV-Get $path 'method' '原生摆放')失败：$(RV-Get $path 'error' '')" }
                }
                $fallback = RV-Get $placement 'fallback' $null
                if ($null -ne $fallback -and (RV-Get $fallback 'status' '') -in @('failed','unavailable')) { $why += "；Pick/Put fallback $(RV-Get $fallback 'status' '')：$(RV-Get $fallback 'error' (RV-Get $fallback 'reason' ''))" }
            }
            if ($why) { $attemptNotes.Add("候选组合 $trial：$why") }
        }
        $fullChainChecks = @(foreach ($check in $checks) { if ([string](RV-Get $check 'name' '') -match '^nested_setup_\d+_full_chain_after_settle$') { $check } })
        $chainVerified = ($fullChainChecks.Count -gt 0 -and @($fullChainChecks | Where-Object { (RV-Get $_ 'passed' $false) -eq $true }).Count -gt 0)
        $hasPlanRecord = ($null -ne $plan)
        $hasPlan = ($null -ne $plan -and $selectedCount -gt 0)
        $stepsObserved = @(RV-Get $observation 'steps' @())
        $eventLabel = if ($kind -eq '搬运') {'pickup_outer'} elseif ($kind -eq '加热') {'microwave_on'} else {'faucet_on'}
        $eventDone = @($stepsObserved | Where-Object { [string](RV-Get $_ 'label' '') -eq $eventLabel }).Count -gt 0
        $setupReady = if ($hasPlan) { $chainVerified } elseif ($hasPlanRecord) { $false } else { $eventDone }
        $baseDetail = if ($orderText.Count) { '实际构造顺序：' + ($orderText -join '；') + '。' } else { '' }
        $failedText = if ($attemptNotes.Count) { $attemptNotes -join '；' } elseif ($error) { $error } else { '没有可用的构造计划或明确失败原因。' }
        $stopping = if (-not $setupReady) { "本轮嵌套链未通过稳定后关系核验，状态为 $status。$failedText" } elseif (-not $eventDone) { "嵌套构造已通过稳定后关系核验，但对应干预（$eventLabel）没有出现在记录步骤中；不把它描述成已完成。$failedText" } else { "嵌套构造通过稳定后关系核验，且记录到对应干预 $eventLabel。最终机制结论仍按本轮实际测量与状态 $status 解释。" }
        $detail = if ($kind -eq '加热') {'搭建时打开微波炉；关门并核验包含关系后才开始加热。'} elseif ($kind -eq '清洗') {'先核验水槽盆与内层容器关系，再检查实际清洁状态变化；盆内关系本身不证明水流接触。'} else {'先将外层物放到最终支撑面，再建立内层与内容物关系，最后拾取外层物检查各层随动。'}
        $checksText = if ($chainVerified) {'稳定后的全部嵌套层级关系核验通过。'} else {'没有可确认的稳定后全链通过记录。'}
        $eventEvidence = if ($kind -eq '搬运') { $motion = @(RV-FindChecks $result '^nested_children_relative_motion_follows_outer$'); if ($motion.Count) { "外层拾取随动检查 passed=$(RV-Get $motion[0] 'passed' $false)。" } else { '未找到外层拾取随动检查。' } } elseif ($kind -eq '加热') { $temp = @(RV-FindChecks $result '^nested_content_temperature_changed$'); if ($temp.Count) { $d = RV-Get $temp[0] 'detail' @{}; "内容物温度记录：$(RV-Get $d 'initial' '未记录') → $(RV-Get $d 'final' '未记录')；变化检查 passed=$(RV-Get $temp[0] 'passed' $false)。" } else { '未找到嵌套内容物温度变化检查。' } } else { $clean = @(RV-FindChecks $result '^nested_content_cleaned$'); if ($clean.Count) { $d = RV-Get $clean[0] 'detail' @{}; "内容物清洁状态记录：$(RV-Get $d 'initial_isDirty' '未记录') → $(RV-Get $d 'final_isDirty' '未记录')；清洁检查 passed=$(RV-Get $clean[0] 'passed' $false)。" } else { '未找到嵌套内容物清洁检查。' } }
        $answer = if (-not $setupReady -or -not $eventDone) { '构造或对应干预未完成，尚无该机制的标准答案。' } elseif ($kind -eq '搬运' -and $status -eq 'observed_supported') { '记录显示外层移动时，内层与内容物均满足本轮随动位移判据。' } elseif ($kind -eq '搬运' -and $status -eq 'observed_counterexample') { '本轮外层确实移动，但至少一项嵌套随动位移判据未通过；查看检查详情中的各层位移。' } elseif ($kind -eq '加热' -or $kind -eq '清洗') { $eventEvidence } else { "本轮状态为 $status；该状态不足以作出机制结论。$eventEvidence" }
        $answerStatus = if ($setupReady -and $eventDone -and $status -in @('observed_supported','observed_counterexample')) {'observed'} else {'undetermined'}
        $titleSuffix = if (-not $setupReady) {'（嵌套构造未通过）'} elseif (-not $eventDone) {'（干预未执行）'} else {"（$status）"}
        $planText = if ($hasPlan) { "实际对象：$objects。$baseDetail $checksText" } elseif ($hasPlanRecord) { "construction_plan 已记录候选尝试；以下物型来自最后一个尝试组合，不能当作已建成状态。$objects。$failedText" } else { "本条记录没有 construction_plan；保留原始状态和错误：$status。$failedText" }
        return (@{
            title = "F10｜嵌套容器的${kind}关系传播$titleSuffix"
            initial = "$scene 场景重置后，以$objects 尝试构造${kind}所需的嵌套场景。$detail $planText"
            steps = @('重置场景，按本条实际候选计划使用现有物体构造嵌套关系。',$baseDetail,$checksText,$stopping,$eventEvidence)
            purpose = '检查多层容器关系能否在受控构造后支持跨层状态传播；先确认布置本身成立，才有资格解释后续干预。'
            observed = @("状态：$status。$stopping",$eventEvidence,$(if($attemptNotes.Count){$attemptNotes -join '；'}else{'没有候选组合失败记录。'}))
            draft_context = "$scene 的 F10 ${kind}场景实际选用$objects。$baseDetail $checksText $stopping $eventEvidence"
            questions = @(@{id='f10_q1';text=if($kind -eq '搬运'){'外层容器移动时，内层容器和内容物各自是否随动？'}elseif($kind -eq '加热'){'记录的嵌套内容物温度是否变化？'}else{'记录的嵌套内容物是否由脏变干净？'};answer_text=$answer;answer_basis='observation fields and native relation/effect checks for this attempt';answer_status=$answerStatus})
        } + $common)
    }

    $search = RV-Get $observation 'search_failure' @{}
    $condition = [string](RV-Get $search 'condition' '未记录')
    $why = [string](RV-Get $search 'error' '')
    if (-not $why) { $why = "未找到并验证同一对象在 A-only、B-only、A+B 三种条件下均受同一属性影响的位置。" }
    return (@{
        title = 'F11｜冗余热源支持的共同影响位置搜索未完成'
        initial = "$scene 场景重置后，尝试寻找一个对象位置，使两个不同旋钮/燃烧器来源能够分别单独和同时影响同一对象温度；若找到，才撤去各来源分别检查。"
        steps = @('枚举并映射场景中的 StoveKnob 与其控制的 StoveBurner，寻找共同物理影响位置。',"此次搜索停在条件「$condition」：$why",'没有执行完成 A-only、B-only、A+B 三臂状态验证，也没有逐一撤去来源的后续干预。')
        purpose = '为「两个来源冗余支持同一属性」构造可检验的三臂条件，并通过分别撤源测量单个来源是否足以维持属性。'
        observed = @("状态为 $status；本轮未得到经验证的共同影响位置。$why",'FloorPlan2 的距离和包围盒仅作为位置诊断，不能证明存在或不存在热影响。两场景尝试均不能支持冗余机制的肯定或否定结论。')
        draft_context = "$scene 场景的 F11 尝试仅搜索共同影响位置。搜索条件为「$condition」；$why 本次没有完成 A-only、B-only、A+B 状态验证或逐一撤源，因此没有可回答的机制结论。"
        questions = @(@{id='f11_q1';text='在同一对象位置，A-only、B-only 和 A+B 三种条件是否都已验证为同一热属性的有效支持条件？';answer_text='未验证；位置搜索没有完成三臂条件。';answer_basis='observation.search_failure and epistemic_boundary';answer_status='undetermined'})
    } + $common)
}
