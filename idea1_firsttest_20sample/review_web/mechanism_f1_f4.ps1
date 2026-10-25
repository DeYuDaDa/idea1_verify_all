function Get-ReviewF1F4($Context) {
    $case = [string]$Context.case_id
    $result = $Context.result
    $fact = [string](RV-Get $result 'fact_id' '')
    if ($fact -notin @('F1','F2','F3','F4')) { return $null }
    $scene = [string]$Context.scene
    $captures = @($Context.captures)
    $status = [string](RV-Get $result 'status' '')
    $checks = @(RV-FindChecks $result '.*')
    $performed = @()
    foreach ($seg in @($Context.segments)) {
        foreach ($a in @($seg)) {
            $act = [string](RV-Get $a 'action' (RV-Get $a 'name' ''))
            if ($act) { $performed += $act }
        }
    }
    $initial = ''
    $steps = @()
    $purpose = ''
    $observed = @()
    $questions = @()
    $visual = @()
    switch ($fact) {
        'F1' {
            $dev = if ($case -match 'toaster') {'烤面包机'} elseif ($case -match 'microwave') {'微波炉'} else {'咖啡机'}
            $item = if ($case -match 'microwave') {'土豆'} elseif ($case -match 'toaster') {'切片面包'} else {'杯子（Mug）'}
            $sequence = if ($case -match 'enter_then_activate') {'先把食物放入设备，再启动'} else {'先启动设备，再把食物放入'}
            $initial = "${scene}：一台${dev}与${item}构成测试对象；每个尝试从新场景重置开始。"
            $steps = @("按本尝试顺序执行：$sequence。",'记录放入动作之前/之后及启动前/后的状态；若轨迹采样存在，展示 Pass 0、1、4、12、36 的阶段截图。',"实际执行记录为：$(if($performed.Count){$performed -join ' → '}else{'未取得可读动作序列'})。未执行或失败的步骤不能视作已完成。")
            $purpose = '比较相同设备与食物的两种操作顺序，检查启动时机是否改变设备状态或食物后续变化；这是机制探针，不等于模型评测。'
            $observed = @("本次尝试状态：$status。")
            foreach($c in $checks){
                $n=[string](RV-Get $c 'name' '检查项'); $d=RV-Get $c 'detail' $null
                if($n -eq 'ordered_actions_produced_heating_or_cooking'){
                    $after=RV-Get $d 'after' $null
                    $cook=RV-Get $after 'isCooked' $null
                    $temp=RV-Get $after 'temperature' $null
                    if($null -ne $cook -or $null -ne $temp){$observed += "状态检查：完成的动作顺序为 $(RV-Get $d 'trigger_actions' '记录缺失')；末态 isCooked=$cook，temperature=$temp。"}
                } elseif($n -eq 'coffee_fill_observed') {
                    $observed += '状态检查：咖啡机/Mug 的注液效果检查通过；具体液体值以该检查的前后记录为准。'
                } else {
                    $pass=RV-Get $c 'passed' $null
                    $cn=$n -replace '_',' '
                    if($null -ne $pass){$observed += "检查「$cn」$(if($pass){'通过'}else{'未通过'})。"}
                }
            }
            if($status -in @('inconclusive','setup_unavailable','probe_error')){$observed += '本次没有可用的末态机制结论；计划的路径不能当作已观察到的答案。'}
            $measuredAnswer=if($status -eq 'observed_supported'){'结果检查确认该尝试的目标效果成立；不外推到其他顺序或设备。'}else{'unknown（本次未取得可判定的目标效果）'}
            $questions = @(@{id='q1';text="本次${dev}操作后，目标的被测状态是什么？";answer_text=$measuredAnswer;answer_basis='具名的末态机制检查；与RGB可读性分别记录。';answer_status=$(if($status -eq 'observed_supported'){'observed'}else{'undetermined'})},@{id='q2';text="${item}是在设备启动前还是启动后放入？";answer_text=if($status -eq 'observed_supported'){$sequence}else{'unknown（操作顺序未被确认成功）'};answer_basis='ordered_native_actions_succeeded 检查；只在通过时采用 case 的顺序。';answer_status=$(if($status -eq 'observed_supported'){'observed'}else{'undetermined'})})
            $visual = @('同一设备、目标食物和其相对位置的全景；物体存在不代表热/熟状态可见。','放入/启动关键步骤前后视图；避免把截图的物体框当作状态可读性证据。','若采样阶段存在，按实际阶段标注，不能称为已验证的物理时长。')
        }
        'F2' {
            if($case -match 'microwave_inside'){$initial="$scene：计划把土豆放入微波炉内，作为容器内部目标。";$flow='打开微波炉、放入土豆，再启动微波炉并检查受热结果。'}
            elseif($case -match 'microwave_outside'){$initial="$scene：土豆计划放在微波炉外，作为外部对照。";$flow='保持土豆在炉外并启动微波炉，检查土豆状态前后值。'}
            elseif($case -match 'microwave_position_scan'){$initial="$scene：围绕微波炉尝试中心和边缘候选摆位，目的是把位置、实际关系与受热结果对应。";$flow='逐个尝试中心/边缘候选位置；仅在放置成功并验证关系后才执行受热检查。'}
            else{$initial="$scene：围绕水槽/水源尝试候选摆位，目的是对照位置、实际关系与注水结果。";$flow='逐个尝试水槽附近候选位置；仅在放置成功并验证关系后才执行水作用检查。'}
            $steps = @($flow,'核对实际执行日志、事件前关系与目标状态的前后值；Pass采样仅用于过程观察。',"实际停止状态为 $status；动作记录：$(if($performed.Count){$performed -join ' → '}else{'没有可确认的干预动作'})。未成功摆位或执行的阶段保持未完成。")
            $purpose = '描出本次干预的经验作用范围，同时区分直接效果、可能的关系传播和保留事实；需由每项检查和对照支持。'
            $observed = @("本次尝试状态：$status。")
            foreach($c in $checks){$n=[string](RV-Get $c 'name' '检查項');$pass=RV-Get $c 'passed' $null;$d=RV-Get $c 'detail' $null
                if($n -eq 'position_scan_measured_real_relation_and_effect'){$observed += '位置扫描没有形成有效的「真实关系×事件效果」配对；候选点未能构成可判定的边界证据。'}
                elseif($null -ne $pass){$observed += "检查「$($n -replace '_',' ')」$(if($pass){'通过'}else{'未通过'})。"}
            }
            $err=[string](RV-Get $result 'error' '')
            if($err){$observed += "停止原因：$err"}
            if(-not $checks.Count){$observed += '关系/作用效果没有被本次检查测得；应回答 unknown，而不是把RGB不清楚当作元数据未知。'}
            $questions = @(@{id='q1';text='本次尝试实际测得的关系和目标状态是什么？';answer_text=if($checks.Count){$observed[1..($observed.Count-1)] -join ' '}else{'unknown（本次没有形成可判定的关系与效果测量）'};answer_basis='具名关系/事件/前后状态检查；摆位未成功则不回答预期金标。';answer_status=$(if($checks.Count){'observed'}else{'undetermined'})},@{id='q2';text='本次是否证明容器关系足以预测作用边界？';answer_text='unknown（需要有效的容器内、外和边缘位置对照；目前未形成有效配对）';answer_basis='原假设要求关系与作用结果的对照，不能从计划或截图推断。';answer_status='undetermined'})
            $visual = @('作用源、直接目标及计划中的保留对象同框或用相邻清晰视图呈现。','变化前和变化后成对；如果状态外观不清，应标注无法从图像判定。','间接关系若需判断，须拍到关系两端及承载物/接触区域。')
        }
        'F3' {
            $target = if($case -match 'toaster'){'切片面包'}elseif($case -match 'microwave'){'土豆'}elseif($case -match 'water'){'水作用目标'}else{'水壶或锅'}
            $count = if($case -match 'multiple'){'两个目标'}else{'一个目标'}
            $device = if($case -match 'toaster'){'烤面包机'}elseif($case -match 'microwave'){'微波炉'}elseif($case -match 'water'){'水槽/水源'}else{'炉头'}
            $initial = "$scene：计划将$count $target 放入${device}的作用范围；以setup和事件前关系检查确认实际摆位，不凭case名称认定成功。"
            $steps = @("启动一次${device}作用事件（热源为启动加热，水源为注水）。",'记录每个目标独立的前后温度/熟度/液体状态；single仅作基线，multiple才检验共同作用。',"本次状态：$status。$(if($status -eq 'setup_unavailable'){'设置阶段即停止，目标效果未测得。'}else{'核对成功事件和逐对象状态检查。'})")
            $purpose = '检验多个对象是否按个体分别更新，重点是身份绑定与未干预对象的保持。'
            $observed = @("本次尝试状态：$status。")
            foreach($c in $checks){$n=[string](RV-Get $c 'name' '检查项');$pass=RV-Get $c 'passed' $null;$d=RV-Get $c 'detail' $null
                $outcomes=RV-Get $d 'outcomes' $null
                if($outcomes){foreach($p in $outcomes.PSObject.Properties){$o=$p.Value;$cook=RV-Get $o 'isCooked_after' $null;$tb=RV-Get $o 'temperature_before' $null;$ta=RV-Get $o 'temperature_after' $null;$cb=RV-Get $o 'isCooked_before' $null
                    if($null -ne $cook -or $null -ne $ta){$observed += "$($p.Name)：temperature $tb→$ta；isCooked $cb→$cook。"}
                    elseif(RV-Get $o 'heated' $null){$observed += "$($p.Name)：temperature $(RV-Get $o 'temperature_before' '?')→$(RV-Get $o 'temperature_after' '?')；本检查记录为受热。"}
                }}
                elseif($null -ne $pass){$observed += "检查「$($n -replace '_',' ')」$(if($pass){'通过'}else{'未通过'})。"}
            }
            $err=[string](RV-Get $result 'error' ''); if($err){$observed += "停止原因：$err"}
            if(-not $checks.Count){$observed += '本尝试未完成可分析的加热/冷却轨迹；temperature 与 isCooked 均没有本次测量值，不能据此支持或反驳分离假设。'}
            $questions = @(@{id='q1';text='本次每个目标的被测属性前后值是什么？';answer_text=if($observed.Count -gt 1){$observed[1..($observed.Count-1)] -join ' '}else{'unknown（没有目标状态检查）'};answer_basis='每个目标的 before/after 结果检查；仅将实际记录为 measured 的值作答。';answer_status=$(if($checks.Count){'observed'}else{'undetermined'})},@{id='q2';text='未直接操作的对象是否保持不变？';answer_text='unknown（该模板没有配套的同场未操作对象保持检查）';answer_basis='本模板检查了目标受热/变熟，不足以回答更新选择性。';answer_status='undetermined'})
            $visual = @('同一视图中标出并能区分每个目标的身份。','事件前后分别呈现每个对象；视角变化时提供身份连续性线索。','尽量同时看到未干预对象，支持保持性核查。')
        }
        'F4' {
            $initialCooked = if($case -match 'uncooked'){'false（计划初态）'}else{'true（计划初态）'}
            $initial = "$scene：计划使用微波炉和土豆，初始 isCooked=$initialCooked；temperature 与 isCooked 分别跟踪。"
            $steps = @('原计划：微波加热，撤出热源后继续观察冷却。','在初态、加热后、冷却后分别读取 temperature 与 isCooked。',"实际停止状态：$status。没有成功的阶段不能当作已经发生。")
            $purpose = '区分温度属性与烹饪完成属性，检查某阶段温度变化是否足以推出熟度变化；二者必须分别取证。'
            $observed = @("执行状态：$status。")
            $err=[string](RV-Get $result 'error' ''); if($err){$observed += "停止原因：$err"}; if(-not $checks.Count){$observed += '本次无温度或熟度测量；加热/冷却机制不能评分。'}
            $questions = @(@{id='q1';text='这次实际记录到的 temperature 前后值是什么？';answer_text='unknown（本次没有成功轨迹或 temperature 检查）';answer_basis='未测量的机制真值；与图像状态是否可读是两回事。';answer_status='undetermined'},@{id='q2';text='这次实际记录到的 isCooked 初末值是什么？';answer_text='unknown（本次没有成功轨迹或 isCooked 检查）';answer_basis='未测量的机制真值；不以计划初态生成答案。';answer_status='undetermined'})
            $visual = @('目标与加热源/冷却源的相对关系清楚。','加热前、加热后及冷却后分别标记阶段；相同外观不表示状态相同。','温度和熟度需要机器元数据或明确公开规则，单靠普通 RGB 可能无法区分。')
        }
    }
    $stageNotes = @{}
    foreach($cap in $captures){
        $label = [string](RV-Get $cap 'label' (RV-Get $cap 'stage' ''))
        if(-not $label){$label='未命名截图'}
        $why = switch -Regex ($label) {
            'initial|scene_initial' {'重置后的基线，用于确认起始场景与对象布局。';break}
            'before|outside|pre' {'干预前/关键操作前的状态锚点；用于比较后续变化。';break}
            'activation|target_on|target_off' {'设备开关状态阶段；用于定位顺序或目标设备状态。';break}
            'pass' {'按实际 Pass 计数的演化采样点；展示过程，不自动代表等时长。';break}
            'final|attempt' {'本次尝试末态；用于与前态和检查项对照。';break}
            default {'本标签对应的采样截图；用途应按动作阶段解释，不据此宣称未见的属性。'}
        }
        $stageNotes[$label]=$why
    }
    return @{title="${fact} · $scene · $case 的具体过程与证据";initial=$initial;steps=$steps;purpose=$purpose;observed=$observed;draft_context=($initial + ' 已执行操作：' + $(if($performed.Count){$performed -join ' → '}else{'无可确认操作'}));questions=$questions;visual_requirements=$visual;stage_notes=$stageNotes}
}
