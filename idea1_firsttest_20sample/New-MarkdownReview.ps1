[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $SourceRoot,
    [Parameter(Mandatory = $true)] [string] $OutputRoot,
    [ValidateSet('Auto', 'Mechanism', 'Dataset')] [string] $Mode = 'Auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Write-Utf8([string] $Path, [string] $Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function ConvertTo-JsonText($Value) {
    return ConvertTo-Json -InputObject $Value -Depth 100
}

function Get-Sha256([string] $Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    try { return [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::HashData($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose() }
}

function Get-SelectedFilesHash([string] $Root, [string[]] $Paths) {
    $sha = [System.Security.Cryptography.IncrementalHash]::CreateHash([System.Security.Cryptography.HashAlgorithmName]::SHA256)
    try {
        foreach ($path in ($Paths | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Sort-Object -Unique)) {
            $full = [System.IO.Path]::GetFullPath($path)
            $relative = $full.Substring($Root.Length).TrimStart('\','/').Replace('\','/')
            $info = Get-Item -LiteralPath $full
            $entry = "$relative`0$($info.Length)`0$(Get-Sha256 $full)`n"
            $sha.AppendData([System.Text.Encoding]::UTF8.GetBytes($entry))
        }
        return [System.BitConverter]::ToString($sha.GetHashAndReset()).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Read-Json([string] $Path) {
    return ,(Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable -NoEnumerate)
}

function Get-Value($Object, [string] $Key, $Default = $null) {
    if ($null -ne $Object -and $Object -is [System.Collections.IDictionary] -and $Object.Contains($Key)) { return $Object[$Key] }
    return $Default
}

function Escape-Md([object] $Value) {
    if ($null -eq $Value) { return '' }
    return ([string]$Value).Replace('|','\|').Replace("`r",' ').Replace("`n",' ')
}

function Format-JsonBlock($Value) {
    return "``````json`n$(ConvertTo-JsonText $Value)`n``````"
}

function Resolve-ContainedPath([string] $Root, [string] $Relative, [string] $Boundary) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or [System.IO.Path]::IsPathRooted($Relative)) { return $null }
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $Root $Relative))
    $boundaryFull = [System.IO.Path]::GetFullPath($Boundary).TrimEnd('\','/') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($boundaryFull, [System.StringComparison]::OrdinalIgnoreCase)) { return $null }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $null }
    return $candidate
}

function Copy-ImageDeduplicated([string] $ImagePath, [string] $AssetsPath, [hashtable] $ImageMap) {
    $hash = Get-Sha256 $ImagePath
    if (-not $ImageMap.ContainsKey($hash)) {
        $ext = [System.IO.Path]::GetExtension($ImagePath).ToLowerInvariant()
        if ($ext -notin @('.png','.jpg','.jpeg','.webp')) { $ext = '.bin' }
        $name = "$hash$ext"
        $target = Join-Path $AssetsPath $name
        [System.IO.File]::Copy($ImagePath, $target, $false)
        if ((Get-Sha256 $target) -ne $hash) { throw "Copied asset failed SHA-256 verification: $ImagePath" }
        $ImageMap[$hash] = "assets/$name"
    }
    return $ImageMap[$hash]
}

function Get-MechanismQuestion([string] $FactId, [string] $Family) {
    $questions = @{
        F1='触发动作的顺序是否改变结果？'; F2='事件的实际作用边界是什么，哪些对象或事实受影响？'
        F3='多个对象是否保持各自独立的状态变化？'; F4='温度与熟度是否被分开记录和推断？'
        F5='清洁状态与注液状态是否被分开记录和推断？'; F6='咖啡液体相关机制是否受其门控条件约束？'
        F7='当前承载关系是否决定对象随承载物变化？'; F8='旋钮操作是否只映射到对应炉头？'
        F9='时间推进的背景演化是否与事件直接效果区分？'; F10='按本项指定机制检查嵌套关系链如何起作用。'
        F11='两个可能的支撑来源是否构成替代关系？'
    }
    if ($questions.ContainsKey($FactId)) { return $questions[$FactId] }
    return "本项关注事实 $FactId（$Family）对应机制是否由当前诊断记录支持？"
}

function Render-MechanismItem($Attempt, [string] $ItemId, [string] $ItemDir, [string] $Source, [string] $Output, [hashtable] $ImageMap) {
    $resultPath = Join-Path $Attempt.FullName 'result.json'
    if (-not (Test-Path -LiteralPath $resultPath)) { return $null }
    $result = Read-Json $resultPath
    $capturePath = Join-Path $Attempt.FullName 'capture_index.json'
    $actionPath = Join-Path $Attempt.FullName 'actions_by_reset.json'
    $captures = @(); $actions = @(); $actionSegments = @()
    $script:SourceHashPaths.Add($resultPath)
    if (Test-Path -LiteralPath $capturePath) { $captures = Read-Json $capturePath; $script:SourceHashPaths.Add($capturePath) }
    if (Test-Path -LiteralPath $actionPath) { $actionSegments = Read-Json $actionPath; $script:SourceHashPaths.Add($actionPath) }
    $actionRows = [System.Collections.Generic.List[object]]::new()
    for ($si = 0; $si -lt $actionSegments.Count; $si++) {
        foreach ($entry in @($actionSegments[$si])) {
            if ($entry -isnot [System.Collections.IDictionary]) { throw "Malformed action segment: $actionPath segment $si" }
            $displayEntry = [ordered]@{}
            foreach ($key in $entry.Keys) { $displayEntry[$key] = $entry[$key] }
            $displayEntry['_review_segment'] = $si
            $actionRows.Add($displayEntry)
        }
    }
    $actions = $actionRows.ToArray()
    $relativeAttempt = $Attempt.FullName.Substring($Source.Length).TrimStart('\','/').Replace('\','/')
    $evidenceDir = Join-Path $ItemDir 'evidence'; [System.IO.Directory]::CreateDirectory($evidenceDir) | Out-Null
    $compact = [ordered]@{
        source_result_path = "$relativeAttempt/result.json"
        case_id = Get-Value $result 'case_id'; fact_id = Get-Value $result 'fact_id'; family = Get-Value $result 'family'; scene = Get-Value $result 'scene'
        status = Get-Value $result 'status'; error = Get-Value $result 'error'; capture_count = Get-Value $result 'capture_count'
        capture_errors = @(Get-Value $result 'capture_errors' @()); checks = @(Get-Value $result 'checks' @()); role_bindings = Get-Value $result 'role_bindings' @{}
    }
    Write-Utf8 (Join-Path $evidenceDir 'result_evidence.json') ((ConvertTo-JsonText $compact) + "`n")
    Write-Utf8 (Join-Path $evidenceDir 'actions_by_reset.json') ((ConvertTo-JsonText $actionSegments) + "`n")
    $fact = [string](Get-Value $result 'fact_id' 'unknown'); $family = [string](Get-Value $result 'family' 'unknown')
    $status = [string](Get-Value $result 'status' 'unknown'); $case = [string](Get-Value $result 'case_id' $Attempt.Parent.Name)
    $scene = [string](Get-Value $result 'scene' $Attempt.Name)
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("# $ItemId — $case / $scene"); $lines.Add('')
    $lines.Add('> 私有审计材料。result/status、检查与 simulator metadata 属于脚本原始诊断报告；下文不构成审核结论。')
    $lines.Add(''); $lines.Add('## 审核边界'); $lines.Add('')
    $lines.Add('- 模型调用：**无**。'); $lines.Add('- Model input：**无**。'); $lines.Add('- 正式 model_input / questions：**无**。')
    $lines.Add('- 下方 RGB 是本 attempt 的全部诊断截图，不代表模型曾看过这些图片。')
    $lines.Add('- case、fact、角色 ID、metadata 和原始动作记录属于私有审计资料，不是模型可见输入。')
    $lines.Add(''); $lines.Add('## 本项信息'); $lines.Add('')
    $lines.Add("- case: ``$case``"); $lines.Add("- scene: ``$scene``"); $lines.Add("- fact: ``$fact`` / family: ``$family``")
    $lines.Add("- 脚本原报告状态（非审核结论）: ``$status``")
    if ($null -ne $compact.error -and [string]$compact.error -ne '') { $lines.Add("- 原报告 error: $($compact.error)") }
    $lines.Add("- 审核者问题（依据 F1–F11 编写，非模型原题）: $(Get-MechanismQuestion $fact $family)")
    $lines.Add(''); $lines.Add('## 审核清单'); $lines.Add(''); $lines.Add('- [ ] 不通过'); $lines.Add('  - 原因：')
    $lines.Add(''); $lines.Add('## 角色绑定'); $lines.Add(''); $lines.Add((Format-JsonBlock $compact.role_bindings))
    $lines.Add(''); $lines.Add('## 检查摘要'); $lines.Add('')
    $lines.Add('| 检查项 | 脚本报告 passed |'); $lines.Add('|---|---:|')
    foreach($check in $compact.checks){$checkName=Escape-Md (Get-Value $check 'name' '(unnamed)');$passed=Get-Value $check 'passed' 'unknown';$lines.Add("| $checkName | $passed |")}
    $lines.Add(''); $lines.Add('完整结构化 checks（含原始 detail/metadata）保存在 [evidence/result_evidence.json](evidence/result_evidence.json)，供审核者按需查看。')
    $lines.Add(''); $lines.Add('## 有序动作台账'); $lines.Add('')
    $lines.Add("原生动作段：$($actionSegments.Count)；总动作记录数：$($actions.Count)。台账顺序列为 段:动作索引，与截图 action_segment/action_index 对应。Pass 与 Get 查询只在连续区段内合并显示次数；完整逐条动作及 kwargs 见 [evidence/actions_by_reset.json](evidence/actions_by_reset.json)。")
    $lines.Add(''); $lines.Add('| 顺序 | 原动作 / 查询 | 对象或目的容器 | 成功 | 失败消息 |'); $lines.Add('|---:|---|---|---:|---|')
    $ai=0
    while($ai -lt $actions.Count){
        $action=$actions[$ai];$actionName=[string](Get-Value $action 'action' 'unknown');$isFold=($actionName -eq 'Pass' -or $actionName -like 'Get*')
        if($isFold){$start=$ai;$names=[System.Collections.Generic.List[string]]::new();while($ai -lt $actions.Count){$candidate=[string](Get-Value $actions[$ai] 'action' 'unknown');if(-not ($candidate -eq 'Pass' -or $candidate -like 'Get*')){break};$names.Add($candidate);$ai++};$segment=@($actions[$start..($ai-1)]);$indices=@($segment|ForEach-Object{'{0}:{1}' -f (Get-Value $_ '_review_segment' '?'),(Get-Value $_ 'index' '?')}) -join ', ';$label=if(@($names|Sort-Object -Unique).Count -eq 1){"$($names[0]) × $($names.Count)"}else{($names|Group-Object|ForEach-Object{"$($_.Name) × $($_.Count)"}) -join ', '};$ok=if(@($segment|Where-Object{(Get-Value $_ 'lastActionSuccess' $true) -eq $false}).Count){'含失败'}else{'均成功'};$foldErrors=(@($segment|ForEach-Object{[string](Get-Value $_ 'errorMessage' '')}|Where-Object{$_})|Sort-Object -Unique)-join '; ';$lines.Add("| $indices | $(Escape-Md $label) | — | $ok | $(Escape-Md $foldErrors) |");continue}
        $kwargs=Get-Value $action 'kwargs' @{};$target=[string](Get-Value $kwargs 'objectId' (Get-Value $kwargs 'objectID' ''));$destination=[string](Get-Value $kwargs 'receptacleObjectId' (Get-Value $kwargs 'destination' ''));$who=if($target -and $destination){"$target → $destination"}elseif($target){$target}elseif($destination){$destination}else{'—'};$success=Get-Value $action 'lastActionSuccess' 'unknown';$err=Escape-Md (Get-Value $action 'errorMessage' '');$idx='{0}:{1}' -f (Get-Value $action '_review_segment' '?'),(Get-Value $action 'index' $ai);$lines.Add("| $idx | $(Escape-Md $actionName) | $(Escape-Md $who) | $success | $err |");$ai++
    }
    $lines.Add(''); $lines.Add('## 按原序排列的全部诊断截图'); $lines.Add('')
    $missing = 0; $imageRefs = 0
    foreach ($capture in ($captures | Sort-Object { [int](Get-Value $_ 'capture_index' 0) })) {
        $label = [string](Get-Value $capture 'label' 'unlabeled')
        $captureIndex = Get-Value $capture 'capture_index' '?'; $actionIndex = Get-Value $capture 'action_index' '?'; $segment = Get-Value $capture 'action_segment' '?'
        $path = [string](Get-Value $capture 'rgb_path' '')
        $image = Resolve-ContainedPath $Attempt.FullName $path $Attempt.FullName
        if ($null -eq $image) { $missing++; $lines.Add("- 🚩 缺失或越界截图：capture=$captureIndex, label=``$label``, path=``$path``"); continue }
        $script:SourceHashPaths.Add($image)
        $ref = Copy-ImageDeduplicated $image (Join-Path $Output 'assets') $ImageMap
        $imageRefs++
        $lines.Add("### $captureIndex — $label"); $lines.Add('')
        $lines.Add("action_index=$actionIndex; action_segment=$segment; relative_path=``$path``")
        $lines.Add(''); $lines.Add("![capture $captureIndex — $label](../../$ref)"); $lines.Add('')
    }
    if ($captures.Count -eq 0) { $missing++ ; $lines.Add('- 🚩 capture_index.json 缺失或没有截图条目。') }
    if ($null -ne $compact.capture_count -and [int]$compact.capture_count -ne $captures.Count) { $missing += [Math]::Abs([int]$compact.capture_count - $captures.Count); $lines.Add("- 🚩 result.capture_count=$($compact.capture_count)，capture_index 条目数=$($captures.Count)，两者不一致。") }
    $lines.Add("截图缺失/路径越界计数：**$missing**。完整性须由审核者确认。")
    $lines.Add(''); $lines.Add("来源溯源: ``$relativeAttempt/result.json``; capture_index.json 与 actions_by_reset.json 位于同目录。")
    Write-Utf8 (Join-Path $ItemDir 'review.md') (($lines -join "`n") + "`n")
    return [ordered]@{ item_id=$ItemId; item_path="items/$ItemId/review.md"; kind='mechanism_attempt'; case_id=$case; scene=$scene; fact_id=$fact; status=$status; question_count=0; image_ref_count=$captures.Count; copied_image_ref_count=$imageRefs; unique_image_count=@($captures | ForEach-Object { $p=Resolve-ContainedPath $Attempt.FullName ([string](Get-Value $_ 'rgb_path' '')) $Attempt.FullName; if ($p) { Get-Sha256 $p } } | Sort-Object -Unique).Count; missing_image_count=$missing }
}

function Build-PublicPayload($ModelInput) {
    $objects = @(); foreach ($obj in @(Get-Value $ModelInput 'objects' @())) { if ($obj -is [System.Collections.IDictionary]) { $objects += [ordered]@{ alias=[string](Get-Value $obj 'alias' ''); object_type=[string](Get-Value $obj 'object_type' '') } } }
    $history = @(); foreach ($episode in @(Get-Value $ModelInput 'history' @())) { if ($episode -is [System.Collections.IDictionary]) { $facts=@(); foreach ($fact in @(Get-Value $episode 'facts' @())) { if ($fact -is [System.Collections.IDictionary]) { $f=[ordered]@{}; foreach($k in @('subject','predicate','value')){ if($fact.Contains($k)){$f[$k]=$fact[$k]} }; $facts += $f } }; $history += [ordered]@{stage=[string](Get-Value $episode 'stage' '');facts=$facts} } }
    $event = Get-Value $ModelInput 'event' @{}; $safeEvent=[ordered]@{}; foreach($k in @('action','subject','destination','success','settle_steps')){ if($event -is [System.Collections.IDictionary] -and $event.Contains($k)){$safeEvent[$k]=$event[$k]} }
    $frames = @(); foreach($frame in @(Get-Value $ModelInput 'frames' @())) { if($frame -is [System.Collections.IDictionary]) { $frames += [ordered]@{index=($frames.Count+1);stage=[string](Get-Value $frame 'stage' '')} } }
    $questions=@(); $i=0; foreach($q in @(Get-Value $ModelInput 'questions' @())) { $i++; $questions += [ordered]@{id=('q{0:D3}' -f $i);subject=[string](Get-Value $q 'subject' '');predicate=[string](Get-Value $q 'predicate' '');question=[string](Get-Value $q 'question' '');answer_mode=[string](Get-Value $q 'answer_mode' 'current_value')} }
    return [ordered]@{protocol_note=[string](Get-Value $ModelInput 'protocol_note' '');objects=$objects;history=$history;rules=@(Get-Value $ModelInput 'rules' @());event=$safeEvent;frames=$frames;questions=$questions}
}

function Render-DatasetItem($File, [string] $ItemId, [string] $ItemDir, [string] $Source, [string] $Output, [hashtable] $ImageMap) {
    $record=Read-Json $File.FullName; $modelInput=Get-Value $record 'model_input' $null
    if ($null -eq $modelInput -or $modelInput -isnot [System.Collections.IDictionary]) { throw "Expected model_input object: $($File.FullName)" }
    $payload=Build-PublicPayload $modelInput; $sourceRel=$File.FullName.Substring($Source.Length).TrimStart('\','/').Replace('\','/')
    $publicCopy=Join-Path $ItemDir 'evidence'; [System.IO.Directory]::CreateDirectory($publicCopy) | Out-Null
    [System.IO.File]::Copy($File.FullName,(Join-Path $publicCopy 'public_input.json'),$false)
    $script:SourceHashPaths.Add($File.FullName)
    $lines=[System.Collections.Generic.List[string]]::new(); $lines.Add("# $ItemId — $(Escape-Md (Get-Value $record 'sample_id' $File.BaseName))"); $lines.Add('')
    $lines.Add('> 审核对象为公开输入。此文档不读取 hidden_gold 或预测答案，也不把模型回答写入审核视野。')
    $lines.Add(''); $lines.Add('## 可见输入边界'); $lines.Add('')
    $lines.Add('以下为 `data/input` 中实际保存的公开 model_input（protocol_note、objects、history、rules、event、frames、questions）。`fact_id` 和媒体路径会被当前 runner 白名单过滤，不作为模型可见内容。')
    $lines.Add(''); $lines.Add('## Runner 重建的请求文本'); $lines.Add('')
    $lines.Add('按当前 `offline_run_qwen.py:build_prompt` 的字段白名单重建；未保存历史请求原文或 processor chat-template 展开。以下是当前 runner 生成的文本内容重建，不是历史请求原文或 exact tokens。运行时还会将公开 frame 图片置于文本前，并由 processor 应用 chat template。')
    $promptHeader='Answer each question using the supplied public history, rules, event, and ordered images. Do not infer hidden simulator metadata. For insufficient evidence answer the string "unknown"; for an inapplicable property answer "not_applicable". For answer_mode change_status, use exactly "changed", "preserved", or "unknown". Return only one JSON object mapping every question id to its answer; arrays are allowed for relation lists. Do not add Markdown or explanations.'
    $lines.Add(''); $lines.Add('```text'); $lines.Add($promptHeader); $lines.Add(''); $lines.Add((ConvertTo-JsonText $payload)); $lines.Add('```'); $lines.Add('')
    $lines.Add('## 公开输入字段核对'); $lines.Add('')
    $lines.Add('原始公开字段供审核对照；不是全部逐字发送给模型。模型文本使用上方按 runner 白名单重建的 payload。原始公开 JSON 保存在 `evidence/public_input.json`，其中 `fact_id` 等字段不会因此成为模型可见内容。')
    foreach($section in @('protocol_note','objects','history','rules','event')) { $lines.Add("### $section"); $lines.Add(''); $lines.Add((Format-JsonBlock (Get-Value $modelInput $section @{}))); $lines.Add('') }
    $lines.Add('## Questions'); $lines.Add('')
    $questionList=@(Get-Value $modelInput 'questions' @()); $qi=0
    foreach($q in $questionList){ $qi++; $lines.Add("### q$('{0:D3}' -f $qi)"); $lines.Add(''); $lines.Add("- subject: ``$(Escape-Md (Get-Value $q 'subject' ''))``"); $lines.Add("- predicate: ``$(Escape-Md (Get-Value $q 'predicate' ''))``"); $lines.Add("- question: $(Escape-Md (Get-Value $q 'question' ''))"); $lines.Add("- answer_mode: ``$(Escape-Md (Get-Value $q 'answer_mode' 'current_value'))``"); $lines.Add('- [ ] 不通过'); $lines.Add('  - 原因：'); $lines.Add('') }
    $lines.Add('## 按 model_input.frames 顺序的全部公开图片'); $lines.Add('')
    $frameList=@(Get-Value $modelInput 'frames' @()); $missing=0; $imageRefs=0
    for($fi=0;$fi -lt $frameList.Count;$fi++){ $frame=$frameList[$fi]; $rel=[string](Get-Value $frame 'path' ''); $boundary=Join-Path $Source 'data\media'; $image=Resolve-ContainedPath $Source $rel $boundary; $stage=[string](Get-Value $frame 'stage' '')
        $lines.Add("### Frame $($fi+1) — $(Escape-Md $stage)"); $lines.Add('')
        if($null -eq $image){$missing++;$lines.Add("- 🚩 缺失或路径越界: ``$rel``");$lines.Add('');continue}
        $script:SourceHashPaths.Add($image)
        $ref=Copy-ImageDeduplicated $image (Join-Path $Output 'assets') $ImageMap; $imageRefs++; $lines.Add("source_path=``$rel``");$lines.Add('');$lines.Add("![frame $($fi+1) — $stage](../../$ref)");$lines.Add('')
    }
    $lines.Add("缺失/越界图片计数：**$missing**。来源公开 JSON：``$sourceRel``。")
    Write-Utf8 (Join-Path $ItemDir 'review.md') (($lines -join "`n")+"`n")
    return [ordered]@{item_id=$ItemId;item_path="items/$ItemId/review.md";kind='dataset_sample';sample_id=(Get-Value $record 'sample_id' $File.BaseName);source_path=$sourceRel;question_count=$questionList.Count;image_ref_count=$frameList.Count;copied_image_ref_count=$imageRefs;unique_image_count=@($frameList | ForEach-Object { $p=Resolve-ContainedPath $Source ([string](Get-Value $_ 'path' '')) (Join-Path $Source 'data\media'); if($p){Get-Sha256 $p} } | Sort-Object -Unique).Count;missing_image_count=$missing}
}

$sourceFull=[System.IO.Path]::GetFullPath($SourceRoot).TrimEnd('\','/')
if (-not (Test-Path -LiteralPath $sourceFull -PathType Container)) { throw "SourceRoot does not exist: $sourceFull" }
$outputFull=[System.IO.Path]::GetFullPath($OutputRoot).TrimEnd('\','/')
if ($outputFull.StartsWith($sourceFull + [System.IO.Path]::DirectorySeparatorChar,[System.StringComparison]::OrdinalIgnoreCase) -or $outputFull -eq $sourceFull) { throw 'OutputRoot must be outside SourceRoot.' }
if (Test-Path -LiteralPath $outputFull) { throw "OutputRoot already exists; refusing to overwrite: $outputFull" }
if ($Mode -eq 'Auto') { if (Test-Path -LiteralPath (Join-Path $sourceFull 'observations\attempts')) { $Mode='Mechanism' } elseif (Test-Path -LiteralPath (Join-Path $sourceFull 'data\input')) { $Mode='Dataset' } else { throw 'Auto mode could not identify a mechanism or dataset source.' } }
if ($Mode -eq 'Mechanism' -and -not (Test-Path -LiteralPath (Join-Path $sourceFull 'observations\attempts'))) { throw 'Mechanism mode requires observations/attempts.' }
if ($Mode -eq 'Dataset' -and -not (Test-Path -LiteralPath (Join-Path $sourceFull 'data\input'))) { throw 'Dataset mode requires data/input.' }

[System.IO.Directory]::CreateDirectory($outputFull) | Out-Null
$itemsDir=Join-Path $outputFull 'items'; $assetsDir=Join-Path $outputFull 'assets'
[System.IO.Directory]::CreateDirectory($itemsDir) | Out-Null; [System.IO.Directory]::CreateDirectory($assetsDir) | Out-Null
$imageMap=@{}; $items=[System.Collections.Generic.List[object]]::new(); $script:SourceHashPaths=[System.Collections.Generic.List[string]]::new()
if ($Mode -eq 'Mechanism') {
    $attempts=@(Get-ChildItem -LiteralPath (Join-Path $sourceFull 'observations\attempts') -Directory -Recurse | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'result.json') } | Sort-Object FullName)
    if ($attempts.Count -eq 0) { throw 'No mechanism result.json attempts were found.' }
    foreach($attempt in $attempts){$n=$items.Count+1;$id=('attempt-{0:D3}-{1}' -f $n,([System.IO.Path]::GetFileName($attempt.Parent.FullName)+'-'+$attempt.Name) -replace '[^A-Za-z0-9_-]','_'); $dir=Join-Path $itemsDir $id; [System.IO.Directory]::CreateDirectory($dir)|Out-Null; $items.Add((Render-MechanismItem $attempt $id $dir $sourceFull $outputFull $imageMap)) }
} else {
    $inputDir=Join-Path $sourceFull 'data\input'; $files=@(Get-ChildItem -LiteralPath $inputDir -File -Filter '*.json' | Sort-Object Name)
    if ($files.Count -eq 0) { throw "No public data/input/*.json files found: $inputDir" }
    foreach($file in $files){$n=$items.Count+1;$sample=[string]((Read-Json $file.FullName).sample_id);$slug=($sample -replace '[^A-Za-z0-9_-]','_');$id='sample-{0:D3}-{1}' -f $n,$slug;$dir=Join-Path $itemsDir $id;[System.IO.Directory]::CreateDirectory($dir)|Out-Null;$items.Add((Render-DatasetItem $file $id $dir $sourceFull $outputFull $imageMap))}
}

$sourceHash=Get-SelectedFilesHash $sourceFull @($script:SourceHashPaths)
$questionTotal=0; $imageTotal=0; $missingTotal=0
foreach($item in $items){$questionTotal += [int]$item['question_count'];$imageTotal += [int]$item['image_ref_count'];$missingTotal += [int]$item['missing_image_count']}
$manifest=[ordered]@{schema_version=1;created_utc=[DateTime]::UtcNow.ToString('o');source_root=$sourceFull;source_sha256=$sourceHash;source_hash_scope=if($Mode -eq 'Dataset'){'Only data/input JSON files and the exact referenced data/media files; hidden_gold and unrelated files are not read.'}else{'Only result.json, capture_index.json, actions_by_reset.json, and referenced RGB files for rendered attempts.'};mode=$Mode;item_count=$items.Count;question_count=$questionTotal;image_ref_count=$imageTotal;unique_image_count=$imageMap.Count;missing_image_count=$missingTotal;items=$items.ToArray()}
Write-Utf8 (Join-Path $outputFull 'manifest.json') ((ConvertTo-JsonText $manifest)+"`n")
$readme=[System.Collections.Generic.List[string]]::new();$readme.Add('# Markdown 审核材料');$readme.Add('');$readme.Add("- Mode: **$Mode**");$readme.Add("- Source SHA-256 (selected inputs): ``$sourceHash``");$readme.Add("- Items: $($items.Count); image references: $($manifest.image_ref_count); unique copied images: $($imageMap.Count); missing/out-of-bound images: $($manifest.missing_image_count)");$readme.Add('');$readme.Add('未勾选表示尚未拒绝，也不代表已批准。每个审核项只在对应 item 文件中维护唯一勾选状态；本索引不含重复复选框。');$readme.Add('');$readme.Add('## Items');$readme.Add('')
if ($Mode -eq 'Mechanism') {
    $readme.Insert(2, '> 本批次是机制探测，没有调用模型，也没有正式模型题。各页中的核验问题属于审核者提示，诊断截图不等于模型已经看到的输入。')
} else {
    $readme.Insert(2, '> 各页展示实际公开输入、图片及逐题勾选。请求文本按当前 runner 重建；未记录的历史请求或 processor 模板不被当作已恢复。')
}
foreach($item in $items){$label=if($item.kind -eq 'mechanism_attempt'){"$($item.case_id) / $($item.scene)"}else{$item.sample_id};$readme.Add("- [$label]($($item.item_path))")}
Write-Utf8 (Join-Path $outputFull 'README.md') (($readme -join "`n")+"`n")
Write-Output (Join-Path $outputFull 'README.md')
