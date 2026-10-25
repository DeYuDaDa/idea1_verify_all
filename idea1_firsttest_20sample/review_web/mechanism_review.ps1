# Read-only presentation adapter for the native-mechanism record schema.
# All generated text is an audit/draft layer, never a historical model request.
function RV-Get($Object,[string]$Key,$Default=$null) {
    if($null -ne $Object -and $Object -is [System.Collections.IDictionary] -and $Object.Contains($Key)){return $Object[$Key]}
    return $Default
}
function RV-Json($Object){return ConvertTo-Json -InputObject $Object -Depth 100 -Compress}
function RV-ViewName([string]$Purpose){
    $names=@{joint_relation='关系总览';device_detail='设备近景';contents_detail='内容物近景';fixture_detail='水槽与水源近景';device_contents_relation='设备与内容物';interior_contents_detail='内部物体近景';burners_pots_knob_relation='炉头与容器关系';control_detail='旋钮近景';burner_vessel_detail='炉头与器皿';carried_relation='承载关系';carried_item_detail='被承载物近景';nested_relation='嵌套关系';inner_contents_detail='内层容器与内容物';device_local='设备局部';contents_local='内容物局部';toaster_detail='烤面包机近景';bread_detail='面包片近景'}
    if($names.ContainsKey($Purpose)){return $names[$Purpose]};return $Purpose
}
function RV-LegacyMetadataOnlyReset([string]$SourceRoot){
    $file=Join-Path $SourceRoot 'source/nested_setup.py'
    if(-not(Test-Path -LiteralPath $file -PathType Leaf)){return $false}
    $text=Get-Content -LiteralPath $file -Raw -Encoding UTF8
    return $text.Contains('ctx.capture(f"nested_setup_trial_{trial:02d}_scene_reset", image=False)')
}
function RV-ExpandCaptureViews($Captures,[bool]$LegacyMetadataOnlyReset=$false){
    $expanded=[Collections.Generic.List[object]]::new()
    foreach($capture in @($Captures)){
        if($capture -isnot [Collections.IDictionary]){throw 'Unsupported capture_index entry: expected a JSON object.'}
        if($capture.Contains('image_requested') -and (RV-Get $capture 'image_requested') -eq $false){continue}
        if($LegacyMetadataOnlyReset -and -not $capture.Contains('image_requested') -and
           [string](RV-Get $capture 'label' '') -match '^nested_setup_trial_\d+_scene_reset$' -and
           -not (RV-Get $capture 'rgb_path') -and -not (RV-Get $capture 'view_frames') -and -not (RV-Get $capture 'capture_error')){continue}
        # Inspect the stored array directly. A helper return would enumerate a
        # single-element array into one dictionary in PowerShell.
        $rawViews=@();if($capture.Contains('view_frames')){$rawViews=$capture['view_frames']}
        if($null -ne $rawViews -and $rawViews -isnot [Array]){throw 'Unsupported view_frames schema: expected a JSON array.'}
        $views=@();if($null -ne $rawViews){$views=$rawViews}
        if(-not $views.Count){
            $single=[ordered]@{};foreach($key in $capture.Keys){$single[$key]=$capture[$key]}
            $single['capture_group_index']=RV-Get $capture 'capture_group_index' (RV-Get $capture 'capture_index' $expanded.Count)
            $single['capture_index']=$expanded.Count
            $expanded.Add($single);continue
        }
        $vi=0
        foreach($view in $views){
            if($view -isnot [Collections.IDictionary]){throw 'Unsupported view_frames entry: expected a JSON object.'}
            $row=[ordered]@{};foreach($key in $capture.Keys){if($key -ne 'view_frames'){$row[$key]=$capture[$key]}}
            $row['capture_group_index']=RV-Get $capture 'capture_index' 0
            $row['capture_index']=$expanded.Count
            $row['rgb_path']=RV-Get $view 'rgb_path' ''
            $row['view_purpose']=RV-Get $view 'purpose' ''
            $row['view_png_sha256']=RV-Get $view 'png_sha256' ''
            $row['view_number']=++$vi;$row['view_count']=$views.Count
            $expanded.Add($row)
        }
    }
    return ,$expanded.ToArray()
}
function RV-DesignLinks([string]$Source,[string]$Output,[string]$ExperimentRoot){
    $researchRoot=Split-Path (Split-Path $ExperimentRoot -Parent) -Parent
    $candidates=@(
        @{source=(Join-Path $researchRoot '明确难度定义&测试的模拟器事实.md');name='original_design.md';label='最初设计：复杂度定义、F1–F11 与 A–E 例组'},
        @{source=(Join-Path $Source 'source/困难组设计与机制依赖.md');name='executed_hard_group_design.md';label='执行时保存的困难组计划与机制依赖'},
        @{source=(Join-Path $Source 'source/hard_group_plan.json');name='executed_hard_group_plan.json';label='执行时保存的条件困难组结构化计划'}
    )
    $folder=Join-Path $Output 'raw/design';[IO.Directory]::CreateDirectory($folder)|Out-Null
    foreach($entry in $candidates){if(Test-Path -LiteralPath $entry.source -PathType Leaf){$target=Join-Path $folder $entry.name;if(-not(Test-Path -LiteralPath $target)){[IO.File]::Copy($entry.source,$target,$false)};@{label=$entry.label;path='raw/design/'+$entry.name}}}
}
function RV-FindChecks($Result,[string]$Pattern){foreach($check in @(RV-Get $Result 'checks' @())){if([string](RV-Get $check 'name' '') -match $Pattern){$check}}}
function RV-ObjectName($Object){
    $text=[string]$Object;if(-not $text){return '未绑定的对象'}
    $type=($text -split '[|_]')[0]
    $names=@{Apple='苹果';Bread='面包';BreadSliced='面包片';Potato='土豆';PotatoSliced='土豆片';Mug='带柄杯';Cup='杯子';Bowl='碗';Plate='盘子';Pot='锅';Kettle='水壶';Microwave='微波炉';Toaster='烤面包机';CoffeeMachine='咖啡机';Faucet='水龙头';SinkBasin='水槽盆';Sink='水槽';StoveKnob='炉灶旋钮';StoveBurner='炉头';CounterTop='台面';Fridge='冰箱';inner='内层容器';outer='外层容器';content='内层物品';child='被承载物';parent='承载容器';carrier='承载容器';surface='台面'}
    if($names.ContainsKey($type)){return $names[$type]};return $text
}
foreach($name in @('mechanism_f1_f4.ps1','mechanism_f5_f8.ps1','mechanism_f9_f11.ps1')){. (Join-Path $PSScriptRoot $name)}

function RV-RefineScene($Context,$P) {
    $r=$Context.result;$case=$Context.case_id;$o=RV-Get $r 'observation' @{};$fact=[string](RV-Get $r 'fact_id' '')
    $status=[string](RV-Get $r 'status' '');$failed=$status -in @('setup_unavailable','probe_error')
    $qs=[Collections.Generic.List[object]]::new();$seen=[Collections.Generic.List[string]]::new()
    if($fact -eq 'F1'){
        $coffee=$case -match 'coffee';$micro=$case -match 'microwave';$firstIn=$case -match 'enter_then_activate'
        $device=if($coffee){'咖啡机'}elseif($micro){'微波炉'}else{'烤面包机'};$target=if($coffee){'带柄杯'}elseif($micro){'土豆'}else{'面包片'}
        $P.title=if($firstIn){"先放入$target，再开启$device"}else{"先开启$device，再放入$target"}
        $P.initial="使用同一台$device 和一个$target，从设备关闭、目标在设备外开始。$(if($coffee){'杯子先倒空。'}elseif($micro){'土豆先准备为未熟状态。'}else{'从场景原有面包切出一片，准备为未熟状态。'})"
        $P.steps=if($firstIn){@("把$target 放入关闭的$device。",$(if($micro){'关上炉门，然后启动微波炉。'}else{"开启$device。"}),'在动作后立即以及后续观察点分别保存图像与状态；重复截图不代表又发生了事件。')}else{@("先启动$device。",$(if($micro){'再尝试开门并放入土豆；是否成功以本条动作回执为准。'}else{"再把$target 放入这台已开启的设备。"}),'保存后续观察与末态；用来核对本条实际发生的结果。')}
        $ordered=@(RV-FindChecks $r '^ordered_native_actions_succeeded$');$orderedOk=$ordered.Count -gt 0 -and (RV-Get $ordered[0] 'passed' $false) -eq $true
        if($micro -and -not $firstIn -and -not $orderedOk){$seen.Add('本条有序动作检查未通过；请以本条动作回执和错误字段为准，不能沿用其他运行中的开门结论。')}
        $latest=RV-Get (RV-Get $o 'after' @{}) 'latest' @{};$role=if($coffee){'Mug'}elseif($micro){'Potato'}else{'Bread'};$state=RV-Get $latest $role @{}
        if($coffee){$filled=RV-Get $state 'isFilledWithLiquid';$liquid=RV-Get $state 'fillLiquid';$answer=if($null -eq $filled){'没有取得末态液体测量。'}elseif($filled){"杯子有液体，类型为$(if($liquid -eq 'coffee'){'咖啡'}elseif($liquid -eq 'water'){'水'}else{$liquid})。"}else{'杯子为空。'};$fillCheck=@(RV-FindChecks $r '^coffee_fill_observed$');$measured=$null -ne $filled -and $orderedOk -and $fillCheck.Count -gt 0 -and (RV-Get $fillCheck[0] 'passed' $false);$qs.Add(@{id='liquid';text='最后杯子是空的，还是有液体？如果有，是什么液体？';answer_text=$answer;answer_basis='本条最后一次杯子液体状态和咖啡机制检查。';answer_status=if($measured){'observed'}else{'undetermined'}})}
        else{$cooked=RV-Get $state 'isCooked';$answer=if($null -eq $cooked){'没有取得末态熟度测量。'}elseif($cooked){"$target 最后已熟。"}else{"$target 最后未熟。"};$measured=$null -ne $cooked -and $orderedOk;$qs.Add(@{id='cooked';text="最后$target 熟了没有？";answer_text=$answer;answer_basis='仅使用本条目标对象的末态熟度字段，并核对有序动作检查。';answer_status=if($measured){'observed'}else{'undetermined'}});if($null -eq $cooked){$seen.Add('本条没有目标熟度末态字段；不能把缺失值解释成未熟或未受热。')}}
        $seen.Add($answer);$P.purpose='确认这一设备在本条动作顺序下能否产生目标效果；另一种顺序是另一条独立记录。两种顺序都有效，不等于顺序造成了差异。'
        $P.draft_context=$P.initial+"`n实际操作："+($P.steps -join ' ')
    }elseif($fact -eq 'F2'){
        $sink=$case -match 'sink';$scan=$case -match 'scan';$outside=$case -match 'outside'
        $P.title=if($sink){'移动碗到水槽中心和边缘候选位置，寻找流水作用边界'}elseif($scan){'土豆放在微波炉中心和边缘，核对包含与受热边界'}elseif($outside){'土豆留在炉外，启动微波炉后是否保持原状态'}else{'土豆放进炉内，启动微波炉后是否受热'}
        $P.initial=if($sink){'计划使用同一只碗、水龙头和水槽盆，比较几个候选摆位下的真实关系与注水效果。'}else{'计划使用一颗未熟、室温的土豆和微波炉，比较炉内、炉外或边缘摆位的关系与受热效果。'}
        $P.steps=if($scan){@('按容器几何信息提出中心、边缘等候选位置。','逐点尝试摆放；只有摆放成功并核实关系后，才进入该位置的干预。','本次没有形成可用的位置—关系—效果对照，图像主要记录搭建场景与停止时点。')}else{@('先查看本条土豆初态与温度字段。','再按本条 placement、动作回执和相关检查判断微波炉干预是否发生。','没有取得干预后的温度或熟度时，保留为未测量，不把其它运行的字段问题带入本条。')}
        $qs.Add(@{id='effect';text=if($sink){'本条位置与水源条件下，碗最后装水了吗、变干净了吗？'}else{'本条摆位下启动微波炉，土豆最后受热或变熟了吗？'};answer_text='没有从本条找到可支持该答案的完整干预和末态测量。';answer_basis='本条实际 trial、动作、检查与末态字段；不能用设计预期或旧运行结论补写。';answer_status='undetermined'})
        $seen.Add('作用边界尚未测出；不支持也不反驳包含关系足够这一猜测。');$P.draft_context=$P.initial+"`n本次尝试："+($P.steps -join ' ')
        $measured=@(@(RV-Get $o 'trials' @())|Where-Object{[string](RV-Get $_ 'setup_status' '') -eq 'measured'})
        if($measured.Count){
            $P.steps=@('先尝试把土豆摆放到微波炉中心候选位置。','中心候选摆放成功，并实际执行了微波炉启动和状态观察。','边缘候选摆放失败，因此只有中心正例，未形成内部—边缘—外部对照。')
            $qs.Clear();foreach($trial in $measured){$end=RV-Get $trial 'after_event' @{};$cooked=RV-Get $end 'isCooked';$temp=RV-Get $end 'temperature';$qs.Add(@{id='center_effect';text='本条成功摆在微波炉中心的土豆，启动后变热、变熟了吗？';answer_text="温度记录为 $temp；$(if($cooked){'已熟'}else{'未熟'})。";answer_basis='中心候选的成功放置、炉内关系、启动动作和实测末态。';answer_status='observed'})}
            $seen.Clear();$seen.Add('中心候选得到真实的炉内关系与受热/变熟正例；边缘候选失败，所以不能据此决定包含关系是否足以预测边界。');$P.draft_context=$P.initial+"`n本次过程："+($P.steps -join ' ')
        }
    }elseif($fact -eq 'F3'){
        $many=$case -match 'multiple';$toast=$case -match 'toaster';$micro=$case -match 'microwave';$water=$case -match 'water'
        $device=if($toast){'烤面包机'}elseif($micro){'微波炉'}elseif($water){'流水区域'}else{'同一个已映射的炉头'}
        $thing=if($toast){'面包片'}elseif($micro){'土豆'}elseif($water){'碗'}elseif($case -match 'kettle$'){'水壶'}elseif($case -match 'pot$'){'锅'}else{'水壶和锅'}
        $number=if($many){'两件目标'}else{'一件目标'};$P.title="把$number 放到$device 的作用范围（$thing）"
        $P.initial="这是$(if($many){'多对象'}else{'单对象基线'})尝试，使用$device 和$thing。先核实每个目标实际在有效区域，再统一启动来源。"
        $P.steps=@("逐一把$number 摆到$device 的候选位置，检查真实包含或承载关系。",$(if($failed){'本次搭建阶段停止，尚未形成有效的共同作用试验。'}else{"布置通过后，启动一次$device 的作用事件。"}),'分别留存每个目标的后续状态，不把一个对象的结果推广给其他对象。')
        $outcomes=RV-Get $o 'outcomes' @{}
        if($outcomes -is [Collections.IDictionary]){foreach($alias in $outcomes.Keys){$v=$outcomes[$alias];$cooked=RV-Get $v 'isCooked_after';$temp=RV-Get $v 'temperature_after';$name=if($alias -match '^HeatObject'){RV-ObjectName (RV-Get (RV-Get $r 'role_bindings' @{}) $alias $alias)}else{RV-ObjectName $alias};if($alias -match '_(\d+)$'){$name+=' '+$Matches[1]}
            if($null -ne $cooked){$answer=if($cooked){'已熟'}else{'未熟'};$qs.Add(@{id=$alias; text="$name 最后熟了没有？";answer_text=$answer;answer_basis='逐对象的实际熟度记录。';answer_status='observed'});$seen.Add("$name：$(if(RV-Get $v 'isCooked_before' $false){'已熟'}else{'未熟'}) → $answer。")}
            elseif($null -ne $temp){$qs.Add(@{id=$alias;text="$name 最后是热的还是室温？";answer_text=[string]$temp;answer_basis='该对象的实测温度；RGB 是否足以推出温度需另审。';answer_status='observed'})}
            if($null -ne $temp){$seen.Add("$name 的温度从 $(RV-Get $v 'temperature_before' '未测得') 变为 $temp。")}
        }}
        if(-not $qs.Count){$qs.Add(@{id='effect';text="作用事件后，$thing 各自的状态是什么？";answer_text='搭建或干预未完成，尚无可计分标准答案。';answer_basis='本次没有取得目标末态。';answer_status='undetermined'});$seen.Add('本次未完成有效作用条件，不能作为机制正例或反例。')}
        if($many){$seen.Add('两件目标都变化，也只说明共同作用可发生；完整独立性仍需逐实例匹配的单对象对照。')}
        $P.draft_context=$P.initial+"`n本次过程："+($P.steps -join ' ')
    }elseif($fact -eq 'F4'){
        $uncooked=$case -match 'uncooked';$P.title=if($uncooked){'未熟土豆加热后撤离热源，检查温度回落与熟度'}else{'已熟土豆重新加热再冷却，检查熟度是否保留'}
        $P.initial="原计划使用一颗$(if($uncooked){'未熟'}else{'已熟'})、室温的土豆和一台微波炉，分开记录温度与熟度。"
        $tempChecks=@(RV-FindChecks $r 'temperature|cook|cool');$obsTemp=RV-Get $o 'final_temperature' $null
        $P.steps=@('按本条初态字段与检查记录核实准备情况。',$(if($tempChecks.Count -or $null -ne $obsTemp){'本条存在温度或熟度相关字段；按实际值与检查状态呈现。'}else{'本条没有温度/熟度测量，不能沿用其他运行的字段错误结论。'}),'只有记录显示加热、移出和等待步骤确已发生时，才将其解释为热—冷序列。')
        $seen.Add($(if($tempChecks.Count -or $null -ne $obsTemp){'本条保留温度/熟度证据，需核对相应检查。'}else{'没有取得温度/熟度测量，热—冷轨迹无法判定。'}));$qs.Add(@{id='cooling';text='本条记录中土豆温度和熟度如何变化？';answer_text=if($tempChecks.Count -or $null -ne $obsTemp){'有相关字段；请结合本条实际值和检查状态核对。'}else{'没有取得对应测量，尚无标准答案。'};answer_basis='本条 observation 与检查；不引用其他运行的字段错误结论。';answer_status='undetermined'});$P.draft_context=$P.initial+"`n本次记录："+($P.steps -join ' ')
    }elseif($fact -eq 'F5'){
        $cond=RV-Get $o 'condition' @{};$dirty=RV-Get $cond 'initially_dirty' ($case -match 'dirty');$filled=RV-Get $cond 'initially_filled_with_water' ($case -match 'filled');$on=RV-Get $cond 'water_source_on' ($case -match 'water_on$')
        $P.title="$(if($dirty){'脏'}else{'干净'})$(if($filled){'且已有水'}else{'且空'})的碗，放进水槽（水龙头$(if($on){'开启'}else{'关闭'})）"
        $P.initial="使用同一只碗、水槽盆和水龙头。计划把碗准备为$(if($dirty){'脏'}else{'干净'})、$(if($filled){'已有水'}else{'空'})，水龙头$(if($on){'开启'}else{'关闭'})。"
        $P.steps=@('在台面上准备碗的清洁和液体初态，并记录放入水槽前的状态。',"把水龙头设为$(if($on){'开启'}else{'关闭'})，然后用原生放置动作把碗放进水槽盆。",$(if($failed){'本次未完成所需初态，后续机制结果不可计分。'}else{'在放置后逐段观察碗的脏污、是否装水和液体类型。碗在水槽中，不等于已经证实水流接触了碗。'}))
        $check=@(RV-FindChecks $r '^dirty_and_liquid_match_water_source_condition$');$final=if($check.Count){RV-Get $check[0].detail 'final' @{}}else{@{}}
        $d=RV-Get $final 'isDirty';$f=RV-Get $final 'isFilledWithLiquid';$l=RV-Get $final 'fillLiquid';$measured=$null -ne $d -and -not $failed
        $qs.Add(@{id='clean';text='最后碗是脏的还是干净的？';answer_text=if($measured){if($d){'脏'}else{'干净'}}else{'所需条件未完成，尚无标准答案。'};answer_basis='本次末态清洁字段；不以期待值代替实际值。';answer_status=if($measured){'observed'}else{'undetermined'}})
        $qs.Add(@{id='liquid';text='最后碗是空的还是装有液体？如果有，是什么？';answer_text=if($null -ne $f -and -not $failed){if($f){"有液体，类型为 $l。"}else{'空碗。'}}else{'所需条件未完成，尚无标准答案。'};answer_basis='本次末态填充和液体类型记录。';answer_status=if($null -ne $f -and -not $failed){'observed'}else{'undetermined'}})
        $seen.Add('没有独立验证水流与碗的实际接触；不出现效果时，不能直接推翻真实接触下的清洁/填充规则。');$P.draft_context=$P.initial+"`n过程："+($P.steps -join ' ')
    }elseif($fact -eq 'F6'){
        $history=[string](RV-Get (RV-Get $o 'condition' @{}) 'history' '');$narration=switch($history){'empty'{'把杯子倒空，作为空杯基线。'}'water_filled'{'给杯子装水，作为已有水的基线。'}'fill_then_empty'{'先给杯子装水，然后把水倒空。'}'empty_then_fill'{'先把杯子倒空，然后给杯子装水。'}default{'按记录准备杯子的液体状态。'}}
        $P.title=$narration.TrimEnd('。')+'，再放进开启的咖啡机';$P.initial='使用同一只带柄杯、一台咖啡机和台面；本条只改变杯子的液体历史。'
        $P.steps=@($narration,'拿起同一只杯子，核对放入咖啡机那一刻的液体状态。','让咖啡机保持开启，把杯子放入其中。','立即以及后续几个观察点留存图像，检查最后杯中液体；末态不是由最早那次装水决定的。')
        $change=RV-Get $o 'field_changes' @{};$before=RV-Get (RV-Get $change 'fillLiquid' @{}) 'before';$after=RV-Get (RV-Get $change 'fillLiquid' @{}) 'after';$filled=RV-Get (RV-Get $change 'isFilledWithLiquid' @{}) 'after'
        $qs.Add(@{id='liquid';text='放进开启的咖啡机后，杯子最后是空的、水，还是咖啡？';answer_text=if($null -eq $filled){'未测得。'}elseif(-not $filled){'空杯。'}elseif($after -eq 'coffee'){'杯中是咖啡。'}elseif($after -eq 'water'){'杯中仍是水。'}else{[string]$after};answer_basis="放入前为$(if($null -eq $before){'空杯'}else{$before})，末态液体记录为 $after。";answer_status=if($null -ne $filled){'observed'}else{'undetermined'}})
        $seen.Add('四种历史在两场景均有记录；本条只使用自身的实际初态和末态，不外推到任意其它液体或设备。');$P.draft_context=$P.initial+"`n操作过程："+($P.steps[0..2] -join ' ')
    }elseif($fact -eq 'F7'){
        $condition=if($case -match 'removed$'){'removed'}elseif($case -match 'returned$'){'returned'}else{'retained'};$history=switch($condition){'removed'{'先把苹果从盘子取下，放到台面，留在盘子外。'}'returned'{'先把苹果从盘子取下，后来又放回盘子。'}default{'苹果始终留在盘子上。'}}
        $P.title=$history.TrimEnd('。')+'，再拿起盘子';$P.initial='使用同一只盘子和苹果，区分苹果曾在哪里与拿盘子时当前在哪里。'
        $P.steps=@($history,$(if($failed){'本次在摆放苹果/盘子时受阻，没有成功进入计划的拾取比较。'}else{'核对当前关系后拿起盘子，分别观察盘子和苹果的世界位置变化。'}),'拿起后关系字段缺失，不直接等于苹果脱离；是否随行用位置轨迹另行判断。')
        $checks=@(RV-FindChecks $r '^condition_specific_world_and_relative_motion$');$metrics=if($checks.Count){@(RV-Get $checks[0].detail 'metrics' @())}else{@()};$have=-not $failed -and $metrics.Count -gt 0
        $answer=if(-not $have){'构造未完成，尚无可计分答案。'}elseif([double](RV-Get $metrics[0] 'child_displacement_m' 0) -lt 0.02){'苹果没有随盘子移动，盘子本身移动了。'}else{'苹果随盘子移动。'}
        $qs.Add(@{id='motion';text='拿起盘子后，苹果是否也移动了？';answer_text=$answer;answer_basis=if($have){'来自苹果和盘子的实际世界位移轨迹；不把拾取后的父关系字段当作承载 Gold。'}else{'摆放条件未满足。'};answer_status=if($have){'observed'}else{'undetermined'}})
        $seen.Add($answer);$P.draft_context=$P.initial+"`n过程："+($P.steps[0..1] -join ' ')
    }elseif($fact -eq 'F8'){
        $swapped=$case -match 'swapped';$which=if($case -match 'control_A'){'A'}else{'B'}
        $P.title="开启旋钮 $which，观察两炉头和两容器$(if($swapped){'（容器位置已交换）'}else{'（原位置）'})"
        $P.initial='使用两个不同的炉灶旋钮、它们对应的两个炉头，以及水壶和锅。映射取自本条场景，不能凭旋钮外观或编号猜测。'
        $assignment=RV-Get $o 'container_assignment' @{};$kettleAt=[string](RV-Get $assignment 'a' '未核实');$potAt=[string](RV-Get $assignment 'b' '未核实')
        $P.initial+=" 本次水壶在炉头 $($kettleAt.Replace('burner_','').ToUpperInvariant())，锅在炉头 $($potAt.Replace('burner_','').ToUpperInvariant())；旋钮 A 对应炉头 A，旋钮 B 对应炉头 B。这些标签尚需在图片中提供可识别的对应。"
        $P.steps=@("本次在独立重置后，把水壶和锅按$(if($swapped){'交换后的'}else{'原始'})分配摆到两个炉头，并将它们准备为室温。","只开启旋钮 $which，记录两个炉头各自是否开启。",'继续观察两件容器的温度；然后关闭同一目标旋钮，核对两炉头状态。','另一种分配是另一条独立记录；不是这条里又交换一次并重做。')
        $on=RV-Get $o 'states_after_on' @{};$temps=RV-Get $o 'temperatures_after_on' @{};$onA=RV-Get $on 'burner_a';$onB=RV-Get $on 'burner_b'
        $qs.Add(@{id='switch';text='开启目标旋钮后，炉头 A 和炉头 B 各自开着还是关着？';answer_text=if($null -ne $onA -and $null -ne $onB){"炉头 A $(if($onA){'开启'}else{'关闭'})，炉头 B $(if($onB){'开启'}else{'关闭'})。"}else{'未取得两个炉头的开关记录。'};answer_basis='本条开启目标旋钮后的两个炉头实测状态。';answer_status=if($null -ne $onA){'observed'}else{'undetermined'}})
        $thermal=@(RV-FindChecks $r '^(object_on_target_burner_became_hot|other_container_remained_room_temp)$');$thermalText=@(foreach($c in $thermal){$d=$c.detail;$alias=RV-Get $d 'target_container' (RV-Get $d 'other_container' '');$object=RV-ObjectName (RV-Get (RV-Get $r 'role_bindings' @{}) $alias $alias);"$object（$(if($c.name -like 'object*'){'目标位置'}else{'另一位置'})）：$(RV-Get $d 'before' '未记录') → $(RV-Get $d 'after_72_pass' '未记录')。"})
        $qs.Add(@{id='temperature';text='等待后，两个位置上的容器各自变热了吗？';answer_text=if($thermalText.Count){$thermalText -join ' '}else{'未取得温度记录。'};answer_basis='分别读取两件容器的温度，不从目标开关推广另一容器结果。';answer_status=if($thermalText.Count){'observed'}else{'undetermined'}})
        $seen.Add('开关映射与物体受热局部性是两件事。若另一容器也热，应保留实测结果，并继续定位原因，不能仍将它标为保持室温。');$P.draft_context=$P.initial+"`n本次过程："+($P.steps[0..2] -join ' ')
    }
    if($fact -eq 'F10'){
        $carry=$case -match 'carry';$heat=$case -match 'heat'
        $plan=RV-Get $o 'construction_plan' $null
        if($null -eq $plan){foreach($c in @(RV-Get $r 'checks' @())){if([string](RV-Get $c 'name' '') -eq 'construction_plan'){$plan=RV-Get $c 'detail' $null;break}}}
        $selected=RV-Get $plan 'selected_roles' @{};$selectedCount=@($selected.Keys).Count;$displayRoles=$selected
        if($selectedCount -eq 0){$attemptsForDisplay=@(RV-Get $plan 'attempts' @());if($attemptsForDisplay.Count){$displayRoles=RV-Get $attemptsForDisplay[-1] 'roles' @{}}}
        $roleLabels=@{source='热源/水源';outer='外层容器';inner='内层容器';content='内容物';basin='水槽盆';support='台面'};$actual=@{}
        foreach($alias in @($displayRoles.Keys)){$entry=RV-Get $displayRoles $alias @{};$type=[string](RV-Get $entry 'objectType' '');if(-not $type){$type=([string](RV-Get $entry 'objectId' '') -split '[|_]')[0]};if($type){$actual[$alias]=RV-ObjectName $type}}
        $order=@(RV-Get $plan 'placement_order' @());$orderText=[Collections.Generic.List[string]]::new()
        foreach($edge in $order){$parts=([string]$edge -split '->',2);if($parts.Count -ne 2){continue};$child=$parts[0];$parent=$parts[1];$cn=if($actual.ContainsKey($child)){$actual[$child]}elseif($roleLabels.ContainsKey($child)){$roleLabels[$child]}else{$child};$pn=if($actual.ContainsKey($parent)){$actual[$parent]}elseif($roleLabels.ContainsKey($parent)){$roleLabels[$parent]}else{$parent};$verb=if($parent -in @('support','basin')){'放到'}else{'放进'};$orderText.Add("$cn$verb$pn")}
        $chain=@(RV-FindChecks $r '^nested_setup_\d+_full_chain_after_settle$')
        $stepsObserved=@(RV-Get $o 'steps' @());$eventLabel=if($carry){'pickup_outer'}elseif($heat){'microwave_on'}else{'faucet_on'};$eventDone=@($stepsObserved|Where-Object{[string](RV-Get $_ 'label' '') -eq $eventLabel}).Count -gt 0
        $chainVerified=$chain.Count -gt 0 -and @($chain|Where-Object{(RV-Get $_ 'passed' $false) -eq $true}).Count -gt 0
        $setupReady=if($selectedCount -gt 0){$chainVerified}elseif($null -ne $plan){$false}else{$eventDone}
        $objectText=if($selectedCount -gt 0){'实际对象：'+(@($actual.Values|Select-Object -Unique) -join '、')}elseif($null -ne $plan -and $actual.Count){'最后一次候选组合：'+(@($actual.Values|Select-Object -Unique) -join '、')+'；该组合未成功建成。'}elseif($null -ne $plan){'本轮 construction_plan 有候选搜索记录，但没有可显示的物型组合。'}else{'本条记录没有 construction_plan，物型沿用原始记录中可核实的字段。'}
        $orderSentence=if($orderText.Count){'实际外到内搭建顺序：'+($orderText -join '；')+'。'}else{'该记录没有可读取的搭建顺序。'}
        $P.initial += "`n本次结果记录的角色物型：$objectText。$orderSentence"
        $P.steps=@('读取本条保存的候选对象与实际类型。',$(if($orderText.Count){$orderSentence}else{'旧记录没有 construction_plan；仅按原始动作/错误说明布置尝试。'}),$(if($setupReady){'稳定后嵌套全链关系检查通过。'}else{'没有稳定后全链关系检查通过；查看本条失败原因。'}),$(if($eventDone){"记录到对应干预 $eventLabel；结果按本条检查与测量呈现。"}else{'没有记录到对应机制干预，不把未执行动作说成已完成。'}))
        $qText=if($carry){'外层容器移动时，内层容器和内容物各自是否随动？'}elseif($heat){'记录的嵌套内容物温度是否变化？'}else{'记录的嵌套内容物是否由脏变干净？'}
        $answer='构造或对应干预未完成，尚无该机制的标准答案。';$answerStatus='undetermined';$basis='本条 construction_plan、稳定后关系检查与实际干预步骤。'
        if($setupReady -and $eventDone){
            if($carry){$motion=@(RV-FindChecks $r '^nested_children_relative_motion_follows_outer$');if($motion.Count){$pass=(RV-Get $motion[0] 'passed' $false) -eq $true;$answer=if($pass){'本轮记录显示外层移动时，内层容器和内容物均满足随动位移判据。'}else{'本轮至少一项嵌套随动位移判据未通过；请结合各层位移检查解读。'};$answerStatus=if([string](RV-Get $r 'status' '') -in @('observed_supported','observed_counterexample')){'observed'}else{'undetermined'}}}
            elseif($heat){$temp=@(RV-FindChecks $r '^nested_content_temperature_changed$');if($temp.Count){$d=RV-Get $temp[0] 'detail' @{};$answer="内容物温度实测 $(RV-Get $d 'initial' '未记录') → $(RV-Get $d 'final' '未记录')；变化检查 passed=$(RV-Get $temp[0] 'passed' $false)。";$answerStatus='observed'}}
            else{$clean=@(RV-FindChecks $r '^nested_content_cleaned$');if($clean.Count){$d=RV-Get $clean[0] 'detail' @{};$answer="内容物清洁状态实测 $(RV-Get $d 'initial_isDirty' '未记录') → $(RV-Get $d 'final_isDirty' '未记录')；清洁检查 passed=$(RV-Get $clean[0] 'passed' $false)。";$answerStatus='observed'}}
        }
        if(@($P.questions).Count){$P.questions[0].text=$qText;$P.questions[0].answer_text=$answer;$P.questions[0].answer_basis=$basis;$P.questions[0].answer_status=$answerStatus}
        $P.draft_context=$P.initial+"`n过程："+($P.steps -join ' ')
        $P.visual_requirements=@('需要在干预前分别看清外层容器、内层容器与最内物品的两级关系，不能只拍到最外层。','干预后还需看清目标位置或属性的证据；本次未执行的动作不能靠当前截图补出来。')
    }
    if($fact -eq 'F11'){
        $setupChecks=@(RV-FindChecks $r '^dual_source|common|nested_setup');$setupPassed=@($setupChecks|Where-Object{(RV-Get $_ 'passed' $false) -eq $true}).Count -gt 0;$eventSteps=@(RV-Get $o 'steps' @());$hasRemoval=@($eventSteps|Where-Object{[string](RV-Get $_ 'label' '') -match 'off|remove|toggle'}).Count -gt 0
        $P.title=if($setupPassed){'核对共同热源布置与撤源后的水壶状态'}else{'尝试构建同一水壶的双热源条件'}
        $qs.Add(@{id='remaining_source';text='本条记录建立了哪些热源布置，执行了哪些撤源步骤？';answer_text=if($setupPassed -and $hasRemoval){'本条有共同布置及撤源记录；答案应以实际末态测量和检查为准。'}elseif(-not $setupPassed){'本条没有通过共同布置检查，无法回答撤源后的热状态。'}else{'本条未记录完整撤源步骤或测量，尚无标准答案。'};answer_basis='本条布置检查、动作步骤和实测字段。';answer_status='undetermined'})
        $P.visual_requirements=@('需要看清水壶与两个炉头的共同作用位置，并能区分哪个来源开启或关闭。','单源、双源和逐一撤源是不同对照分支；还要排除只是短期余热保留。当前图片没有替代这些未执行的干预。')
    }
    if($fact -eq 'F9'){
        $P.title='水壶预热后关火或保留热源，比较固定推进与普通等待'
        $P.initial='使用水壶及其实际所在的炉头。各分支分别重置并预热到热状态，再比较关火与继续开火。'
        $P.steps=@('独立准备两组相同的水壶受热初态，一组关闭热源，另一组保留热源。','两组各暂停自动物理推进，再执行 400 次、每次请求 0.01 秒的原生物理推进，并沿途保存图像。','另外独立重置，重复关火/保源比较，但改用普通 Pass 调用观察，不把调用次数当物理秒数。','各分支之间是独立对照，不是同一世界连续经历的四段历史。')
        $P.draft_context=$P.initial+"`n过程："+($P.steps -join ' ')
        $P.visual_requirements=@('每个分支都应能看清同一目标水壶、炉头及开关操作，而不是冰箱门或无关台面。','普通 RGB 未必能读出 Hot/RoomTemp。保留温度题需要模型可用的测温线索或明确给定的已验证机制。','各分支应明确区分重置前后，避免把不同实验的截图理解为连续过程。')
    }
    if($qs.Count){$P.questions=$qs.ToArray()};if($seen.Count){$P.observed=$seen.ToArray()};return $P
}

function RV-ActionText($Action) {
    $name=[string](RV-Get $Action 'action' '');$args=RV-Get $Action 'kwargs' @{}
    $target=RV-ObjectName (RV-Get $args 'objectId' (RV-Get $args 'objectID' ''))
    $text=switch($name){
        'Initialize' {'初始化场景'} 'Reset' {'重置场景，开始独立对照分支'}
        'ToggleObjectOn' {"开启$target"} 'ToggleObjectOff' {"关闭$target"}
        'PickupObject' {"拿起$target"} 'PutObject' {"把手持物体放入/放到$target"}
        'PlaceObjectAtPoint' {"摆放$target（搭建场景）"} 'TeleportObject' {"调整$target 的摆放位置"}
        'OpenObject' {"打开$target"} 'CloseObject' {"关上$target"}
        'FillObjectWithLiquid' {"给$target 装入$(RV-Get $args 'fillLiquid' '液体')"} 'EmptyLiquidFromObject' {"倒空$target"}
        'DirtyObject' {"把$target 设为脏"} 'CleanObject' {"把$target 设为干净"}
        'CookObject' {"设置$target 的已熟初态"} 'SetObjectTemperature' {"设置$target 的温度初态"}
        'PausePhysicsAutoSim' {'暂停物理自动推进'} 'UnpausePhysicsAutoSim' {'恢复物理自动推进'}
        'AdvancePhysicsStep' {'按请求推进物理步'} 'Pass' {'继续观察 / 推进调用'}
        'TeleportFull' {'调整观察位置'} 'Teleport' {'调整观察位置'} 'LookDown' {'调整观察俯角'} 'LookUp' {'调整观察仰角'}
        default {if($name -like 'Get*'){return $null}else{$name}}
    }
    if((RV-Get $Action 'lastActionSuccess' $true) -eq $false){$text+='（动作失败）'}
    return $text
}
function RV-CaptureNotes($Context,$Presentation) {
    $frames=[System.Collections.Generic.List[object]]::new();$previous=$null
    foreach($capture in @($Context.captures)){
        $stage=[string](RV-Get $capture 'label' '');$index=[int](RV-Get $capture 'capture_index' $frames.Count)
        $segment=[int](RV-Get $capture 'action_segment' 0);$actionIndex=[int](RV-Get $capture 'action_index' -1)
        $purpose=[string](RV-Get $Presentation.stage_notes $stage '')
        if(-not $purpose){
            $purpose=if($stage -eq 'scene_initial'){'刚初始化的房间基线，还没有完成本题需要的物品布置。'}elseif($stage -eq 'attempt_final'){'本次尝试实际停止时的画面；用于对照最后观测，也可能是在构造失败后留存。'}elseif($stage -match 'trajectory_\d+_pass_(\d+)'){"这一观察段累计执行 $($Matches[1]) 次 Pass 后的画面，用于检查状态是否继续变化；这不是已经核实的物理秒数。"}elseif($stage -match 'before'){'关键操作前的状态锚点，用来与操作后配对检查。'}else{'该操作阶段的留存画面，具体发生时点见下面的过程说明。'}
        }
        $viewPurpose=[string](RV-Get $capture 'view_purpose' '')
        if($viewPurpose){$purpose="同一观测时点 $(RV-Get $capture 'capture_group_index' '?')，视角 $(RV-Get $capture 'view_number' 1)/$(RV-Get $capture 'view_count' 1)：$(RV-ViewName $viewPurpose)。"+$purpose}
        $actions=@();if($segment -lt @($Context.segments).Count){$actions=@($Context.segments[$segment])}
        $start=if($null -ne $previous -and $previous.segment -eq $segment){$previous.action_index}else{-1}
        $interval=@($actions|Where-Object{[int](RV-Get $_ 'index' -1) -gt $start -and [int](RV-Get $_ 'index' -1) -le $actionIndex})
        $significant=[System.Collections.Generic.List[string]]::new();$passCount=0;$physicsCount=0
        $failedCount=0
        foreach($action in $interval){if((RV-Get $action 'observation_only' $false) -eq $true){continue};$name=[string](RV-Get $action 'action' '');if($name -eq 'Pass'){$passCount++;continue};if($name -eq 'AdvancePhysicsStep'){$physicsCount++;continue};if((RV-Get $action 'lastActionSuccess' $true) -eq $false){$failedCount++;continue};$t=RV-ActionText $action;if($t){$significant.Add($t)}}
        $text=if($null -ne $previous -and $previous.segment -eq $segment -and $previous.action_index -eq $actionIndex){'与上一张之间没有新动作，是同一时点的再次留存。'}elseif($significant.Count){'关键操作：'+(@($significant.ToArray()|Select-Object -Last 4) -join ' → ')}elseif($failedCount){'这段候选操作未成功，具体停止点见上方过程说明。'}else{'没有新的物体交互；继续留存该阶段。'}
        if($passCount){$text+="；期间有 $passCount 次 Pass 调用"};if($physicsCount){$text+="；期间有 $physicsCount 次原生物理推进请求"}
        if($viewPurpose -and $null -ne $previous -and $previous.segment -eq $segment -and $previous.action_index -eq $actionIndex){$text='同一观测时点的互补视角，没有新的物体事件。'}
        if($null -ne $previous -and $previous.segment -ne $segment){$text='这里已重置到新的独立对照分支，不接续上一张的世界状态。'+$text}
        $frames.Add([ordered]@{title="第 $($index+1) 张";purpose=$purpose;process=$text;segment=$segment;action_index=$actionIndex;source_label=$stage})
        $previous=@{segment=$segment;action_index=$actionIndex}
    }
    return ,$frames.ToArray()
}
function Get-MechanismReviewPresentation($Result,$Captures,$Segments) {
    $context=@{result=$Result;captures=$Captures;segments=$Segments;case_id=[string](RV-Get $Result 'case_id' '');scene=[string](RV-Get $Result 'scene' '')}
    $fact=[string](RV-Get $Result 'fact_id' '')
    $presentation=if($fact -in @('F1','F2','F3','F4')){Get-ReviewF1F4 $context}elseif($fact -in @('F5','F6','F7','F8')){Get-ReviewF5F8 $context}elseif($fact -in @('F9','F10','F11')){Get-ReviewF9F11 $context}else{$null}
    if($null -eq $presentation){throw "No scene-description adapter: $($context.case_id)"}
    $presentation=RV-RefineScene $context $presentation
    if((RV-Get $Result 'native_measurement_valid' $true) -eq $false){
        foreach($q in @($presentation.questions)){$q.answer_status='undetermined';$q.answer_text='取景过程改变了原生状态或未恢复物理推进；本轮测量不可作为机制标准答案。'}
        $presentation.observed=@('本轮观察干预影响了测量，机制结论无效。')+@($presentation.observed)
    }
    $presentation.visual_requirements=@($presentation.visual_requirements|Where-Object{[string]$_ -notmatch '抽查'})
    foreach($key in @('title','initial','steps','purpose','observed','draft_context','questions','visual_requirements','stage_notes')){if(-not $presentation.ContainsKey($key)){throw "Missing presentation.$key in $($context.case_id)"}}
    $presentation['version']='mechanism-scene-review/v2'
    $presentation['frame_notes']=RV-CaptureNotes $context $presentation
    $someObserved=@($presentation.questions|Where-Object{[string](RV-Get $_ 'answer_status' '') -eq 'observed'}).Count -gt 0
    $presentation['run_completed']=([string](RV-Get $Result 'status' '') -notin @('probe_error','setup_unavailable') -and $someObserved)
    $presentation['prompt_origin']='new_draft_from_recorded_attempt_not_historical_request'
    $questionLines=[System.Collections.Generic.List[string]]::new();$n=0
    foreach($q in @($presentation.questions)){$n++;$questionLines.Add("$n. $([string](RV-Get $q 'text' ''))")}
    $presentation['draft_prompt']="你将看到同一探测记录按顺序保存的 $(@($Captures).Count) 张图片。不同独立重置分支不是同一世界的连续历史。`n`n以下初始条件与操作过程是随题提供的信息，不要求你从 RGB 中猜测未声明的模拟器属性。`n$($presentation.draft_context)`n`n请结合文字与图片回答下面的问题；若给定证据不足，回答「无法确定」，不要假设尚未验证的物理规则。`n$($questionLines.ToArray() -join "`n")"
    if(-not $presentation.run_completed){$presentation['draft_warning']='本次构造未完成。以下是帮助审核的题意草案，尚不能作为完整、可计分的模型样本。'}else{$presentation['draft_warning']='这是根据本次过程新整理的候选输入，不是旧运行保存的 prompt；参考答案另列，未混入这段输入。'}
    $captureErrors=@($Captures|Where-Object{[string](RV-Get $_ 'capture_error' '') -or [string](RV-Get (RV-Get $_ 'camera_audit' @{}) 'error' '')})
    if($captureErrors.Count){$presentation['draft_warning']+=' 图像采集不完整：部分预期视角失败或未提供图像；当前原生状态字段不能替代视觉可答性证据。'}
    return $presentation
}
