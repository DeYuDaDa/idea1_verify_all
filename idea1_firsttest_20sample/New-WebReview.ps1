[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string[]] $SourceRoot,
    [Parameter(Mandatory)] [string] $OutputRoot,
    [string[]] $BatchName = @(),
    [switch] $IncludeReferenceAnswers,
    [string] $PredictionsPath
)
# Existing local records -> static website. No Python, model, or simulator.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$encoding = [System.Text.UTF8Encoding]::new($false)
. (Join-Path $PSScriptRoot 'review_web/mechanism_review.ps1')
. (Join-Path $PSScriptRoot 'review_web/capture_integrity.ps1')
function Read-Json([string]$Path) { return ,(Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable -NoEnumerate) }
function Value($Object,[string]$Key,$Default=$null) { if($null -ne $Object -and $Object -is [System.Collections.IDictionary] -and $Object.Contains($Key)){return $Object[$Key]};return $Default }
function Canonical-Json($Object) {
    if($null -eq $Object){return 'null'}
    if($Object -is [System.Collections.IDictionary]){
        $parts=[System.Collections.Generic.List[string]]::new()
        foreach($key in @($Object.Keys|Sort-Object {[string]$_})){$keyJson=ConvertTo-Json -InputObject ([string]$key) -Compress;$parts.Add($keyJson+':'+(Canonical-Json $Object[$key]))}
        return '{'+($parts -join ',')+'}'
    }
    if($Object -is [Array]){$parts=[System.Collections.Generic.List[string]]::new();foreach($item in $Object){$parts.Add((Canonical-Json $item))};return '['+($parts -join ',')+']'}
    return ConvertTo-Json -InputObject $Object -Depth 100 -Compress
}
function Hash([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Bytes-Hash([byte[]]$Bytes) { return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant() }
function Write-Text([string]$Path,[string]$Text){[System.IO.File]::WriteAllText($Path,$Text,$encoding)}
function Safe-Path([string]$Root,[string]$Relative,[string]$Boundary) {
    if(-not $Relative -or [System.IO.Path]::IsPathRooted($Relative)){return $null}
    $path=[System.IO.Path]::GetFullPath((Join-Path $Root $Relative))
    $allowed=[System.IO.Path]::GetFullPath($Boundary).TrimEnd('\','/')+[System.IO.Path]::DirectorySeparatorChar
    if(-not $path.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)-or -not(Test-Path -LiteralPath $path -PathType Leaf)){return $null}
    return $path
}
function Export-ReviewAsset([string]$Path,$AssetMap,[string]$OutputRoot) {
    if(-not $Path){return [ordered]@{src=$null;sha256=$null}}
    $digest=Add-Source $Path
    if(-not $AssetMap.ContainsKey($digest)){
        $extension=[IO.Path]::GetExtension($Path).ToLowerInvariant();if($extension -notin @('.png','.jpg','.jpeg','.webp')){throw "Unsupported review image: $Path"}
        $relative="assets/$digest$extension";$target=Join-Path $OutputRoot $relative;[IO.File]::Copy($Path,$target,$false)
        if((Hash $target)-ne $digest){throw "Review image copy SHA mismatch: $Path"};$AssetMap[$digest]=$relative
    }
    return [ordered]@{src=$AssetMap[$digest];sha256=$digest}
}
function Export-CaptureGroups($Groups,[string]$TimelineRoot,[string]$TimelinePath,$AssetMap,[string]$OutputRoot) {
    $exported=[System.Collections.Generic.List[object]]::new()
    foreach($group in @($Groups)){
        $views=[System.Collections.Generic.List[object]]::new()
        foreach($view in @(Value $group 'views' @())){
            $relative=[string](Value $view 'path' '');$resolved=$null
            if($relative){
                if([IO.Path]::IsPathRooted($relative)){throw "Capture-group image path is rooted: $TimelinePath"}
                $candidate=[IO.Path]::GetFullPath((Join-Path $TimelineRoot $relative));$prefix=[IO.Path]::GetFullPath($TimelineRoot).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
                if(-not $candidate.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw "Capture-group image escapes the case sidecar directory: $TimelinePath"}
                if(Test-Path -LiteralPath $candidate -PathType Leaf){$resolved=$candidate}
            }
            $asset=Export-ReviewAsset $resolved $AssetMap $OutputRoot
            $webView=[ordered]@{view_id=Value $view 'view_id' '';view_role=Value $view 'view_role' '';purpose=Value $view 'purpose' '';status=Value $view 'status' '';src=$asset.src;sha256=$asset.sha256}
            $views.Add($webView)
        }
        $webGroup=[ordered]@{capture_group_index=Value $group 'capture_group_index' (Value $group 'global_step' $null);global_step=Value $group 'global_step' $null;reset_index=Value $group 'reset_index' $null;phase_id=Value $group 'phase_id' $null;phase_label=Value $group 'phase_label' '';phase_public=Value $group 'phase_public' $false;phase_kind=Value $group 'phase_kind' '';frame_status=Value $group 'frame_status' '';run_length=Value $group 'run_length' $null;duplicate_count=Value $group 'duplicate_count' $null;start_step=Value $group 'start_step' $null;end_step=Value $group 'end_step' $null;step_numbers=@(Value $group 'step_numbers' @());views=$views.ToArray()}
        if($group -is [Collections.IDictionary] -and $group.Contains('step_group_map')){$webGroup.step_group_map=$group.step_group_map}
        $exported.Add($webGroup)
    }
    return ,$exported.ToArray()
}
$output=[System.IO.Path]::GetFullPath($OutputRoot).TrimEnd('\','/')
if(Test-Path -LiteralPath $output){throw "Output exists; existing reviews will not be overwritten: $output"}
$sources=@($SourceRoot|ForEach-Object{[System.IO.Path]::GetFullPath($_).TrimEnd('\','/')})
foreach($source in $sources){if(-not(Test-Path -LiteralPath $source -PathType Container)){throw "Missing source: $source"};if($output -eq $source -or $output.StartsWith($source+[System.IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Output must be outside every source.'}}
$predictions=@{}
if($PredictionsPath){
    foreach($line in Get-Content -LiteralPath $PredictionsPath -Encoding UTF8){if(-not $line.Trim()){continue};$row=$line|ConvertFrom-Json -AsHashtable;$id=[string](Value $row 'sample_id' '');if($id){$predictions[$id]=$row}}
}
[System.IO.Directory]::CreateDirectory((Join-Path $output 'assets'))|Out-Null
foreach($name in @('index.html','review.css','review.js')){[System.IO.File]::Copy((Join-Path $PSScriptRoot "review_web/$name"),(Join-Path $output $name),$false)}
$assets=@{};$batches=[System.Collections.Generic.List[object]]::new();$reports=[System.Collections.Generic.List[object]]::new()
for($bi=0;$bi -lt $sources.Count;$bi++){
    $source=$sources[$bi];$items=[System.Collections.Generic.List[object]]::new();$hashes=[System.Collections.Generic.List[string]]::new();$missing=0;$imageCount=0;$generationIncomplete=$false;$diagnosticCount=0
    function Add-Source([string]$Path){$h=Hash $Path;$rel=$Path.Substring($source.Length).TrimStart('\','/').Replace('\','/');$hashes.Add("$rel`0$h");return $h}
    function Frame([string]$Path,[string]$Stage,$MediaInfo=$null){
        $script:imageCount++
        $row=[ordered]@{stage=$Stage;src=$null;sha256=$null}
        if($MediaInfo){foreach($k in @('source_path','source_status','source_error','source_message','observation_contaminated')){$row[$k]=$MediaInfo[$k]}}
        if(-not $Path){$script:missing++;return $row}
        $h=Add-Source $Path
        if(-not $assets.ContainsKey($h)){
            $ext=[System.IO.Path]::GetExtension($Path).ToLowerInvariant();if($ext -notin @('.png','.jpg','.jpeg','.webp')){throw "Unsupported image: $Path"}
            $relative="assets/$h$ext";$target=Join-Path $output $relative;[System.IO.File]::Copy($Path,$target,$false)
            if((Hash $target)-ne $h){throw "Image copy SHA mismatch: $Path"};$assets[$h]=$relative
        }
        $row.src=$assets[$h];$row.sha256=$h;return $row
    }
    if((Test-Path -LiteralPath (Join-Path $source 'data/input') -PathType Container) -or
       (Test-Path -LiteralPath (Join-Path $source 'generation_summary.json') -PathType Leaf)){
        # An all-failed generation need not create data/input at all. Its summary
        # and private timelines are valid diagnostic inputs, never formal QA.
        $mode='Dataset';$files=@()
        if(Test-Path -LiteralPath (Join-Path $source 'data/input') -PathType Container){
            $files=@(Get-ChildItem -LiteralPath (Join-Path $source 'data/input') -Filter '*.json' -File|Sort-Object Name)
        }
        foreach($file in $files){
            $r=Read-Json $file.FullName;$sourceHash=Add-Source $file.FullName;$mi=Value $r 'model_input';if(-not $mi){throw "No model_input: $file"}
            if($mi -isnot [Collections.IDictionary]){throw "Unsupported model_input schema: $file"}
            if(-not $mi.Contains('frames') -or $mi['frames'] -isnot [Array]){throw "Dataset requires model_input.frames JSON array: $file"}
            if(-not $mi.Contains('questions') -or $mi['questions'] -isnot [Array] -or -not $mi['questions'].Count){throw "Dataset requires a nonempty model_input.questions JSON array: $file"}
            $sample=[string](Value $r 'sample_id' $file.BaseName);$frames=[System.Collections.Generic.List[object]]::new()
            foreach($f in @(Value $mi 'frames' @())){
                $info=RV-MediaInfo $source ([string](Value $f 'path' '')) (Join-Path $source 'data/media')
                $webFrame=Frame $info.resolved_path ([string](Value $f 'stage' '')) $info
                foreach($key in @('run_length','duplicate_count','start_step','end_step','capture_group_index','view_id','boundary_labels')){
                    if($f -is [Collections.IDictionary] -and $f.Contains($key)){$webFrame[$key]=$f[$key]}
                }
                $frames.Add($webFrame)
            }
            $references=[System.Collections.Generic.List[object]]::new()
            if($IncludeReferenceAnswers){
                $goldPath=Safe-Path $source "hidden_gold/$($file.Name)" (Join-Path $source 'hidden_gold')
                if($goldPath){
                    $g=Read-Json $goldPath;$null=Add-Source $goldPath
                    if([string](Value $g 'sample_id' '') -ne $sample){throw "Gold sample_id mismatch: $goldPath"}
                    $targets=@(Value $g 'query_targets' @());$qs=@(Value $mi 'questions' @());for($qi=0;$qi -lt $qs.Count;$qi++){
                        $fact=[string](Value $qs[$qi] 'fact_id' '');$matches=@($targets|Where-Object{[string](Value $_ 'fact_id' '') -eq $fact})
                        if($fact -and $matches.Count -eq 1 -and $matches[0].Contains('expected_answer')){$references.Add([ordered]@{question_id=('q{0:D3}' -f ($qi+1));expected_answer=$matches[0]['expected_answer']})}
                    }
                }
            }
            $origin='reconstructed';$request=$null;$requestRunStatus=$null;$protocol='';$prepared=$null;$preparedPath=Join-Path (Join-Path $source 'prepared_requests') ($sample+'.json')
            if(Test-Path -LiteralPath $preparedPath -PathType Leaf){
                $prepared=Read-Json $preparedPath;$null=Add-Source $preparedPath
                $preparedSchema=[string](Value $prepared 'schema' '')
                if($preparedSchema -ne 'hard-request/v1'){throw "Unsupported prepared request schema: $preparedPath"}
                $expectedMedia=@($frames|ForEach-Object{$_.sha256});$savedMedia=@(Value $prepared 'media_sha256' @())
                if([string](Value $prepared 'model_input_sha256' '') -ne $sourceHash -or ($expectedMedia -join ',') -ne ($savedMedia -join ',')){throw "Prepared request input/image hashes mismatch: $sample"}
                $savedText=Value $prepared 'request_text' $null
                if($savedText -isnot [string] -or -not $savedText){throw "Prepared request has no request_text: $preparedPath"}
                $origin='prepared';$request=[string]$savedText;$requestRunStatus=[string](Value $prepared 'status' 'prepared_not_sent');$protocol=[string](Value $prepared 'protocol' '')
                if($requestRunStatus -ne 'prepared_not_sent'){throw "Hard request status must remain prepared_not_sent: $preparedPath"}
                if($protocol -notin @('hard-selective-V/v1','hard-selective-S/v1')){throw "Unsupported hard protocol: $preparedPath"}
                if($protocol -ne [string](Value $mi 'protocol' '')){throw "Prepared request protocol does not match model_input.protocol: $sample"}
                if($prepared.Contains('model_input')){$preparedInputJson=Canonical-Json $prepared['model_input'];$publicInputJson=Canonical-Json $mi;if($preparedInputJson -ne $publicInputJson){throw "Prepared request model_input does not match public record: $sample"}}
                if($protocol -eq 'hard-selective-V/v1' -and -not $frames.Count){throw "Visual hard request requires public model frames: $sample"}
                if($protocol -eq 'hard-selective-S/v1' -and $frames.Count){throw "Text-state hard request must have no public model frames: $sample"}
            }
            if(-not $frames.Count -and $protocol -ne 'hard-selective-S/v1'){throw "Only a hash-matched frozen S request may intentionally have no public frames: $sample"}
            if($predictions.ContainsKey($sample)){
                $p=$predictions[$sample];$text=Value $p 'request_text' $null
                if($text -and $origin -ne 'prepared'){
                    $expectedHashes=@($frames|ForEach-Object{$_.sha256});$actualHashes=@(Value $p 'media_sha256' @())
                    if([string](Value $p 'source_sha256' '') -ne $sourceHash -or ($expectedHashes -join ',') -ne ($actualHashes -join ',')){throw "Recorded request input/image hashes mismatch: $sample"}
                    $origin='recorded';$request=[string]$text;$requestRunStatus=[string](Value $p 'status' 'unknown')
                }
            }
            $auditTimeline=$null;$timelineRel=Value $prepared 'audit_timeline_path' $null
            if($origin -eq 'prepared' -and $timelineRel){
                $timelinePath=Safe-Path $source ([string]$timelineRel) $source
                if(-not $timelinePath){throw "Prepared audit_timeline_path is missing or escapes the dataset root: $sample"}
                $timelineRoot=Split-Path -Parent $timelinePath;$timeline=Read-Json $timelinePath;$null=Add-Source $timelinePath
                $baseSample=([regex]::Replace($sample,'_[VS]$',''))
                if([string](Value $timeline 'sample_id' '') -ne $baseSample){throw "Audit timeline sample_id mismatch: $timelinePath"}
                $auditFrames=[System.Collections.Generic.List[object]]::new()
                foreach($tf in @(Value $timeline 'frames' @())){
                    $privateRelative=[string](Value $tf 'path' '')
                    if(-not $privateRelative -or [IO.Path]::IsPathRooted($privateRelative)){throw "Audit frame path is missing or escapes the case sidecar directory: $timelinePath"}
                    $privateResolved=[IO.Path]::GetFullPath((Join-Path $timelineRoot $privateRelative));$timelinePrefix=[IO.Path]::GetFullPath($timelineRoot).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
                    if(-not $privateResolved.StartsWith($timelinePrefix,[StringComparison]::OrdinalIgnoreCase)){throw "Audit frame path is missing or escapes the case sidecar directory: $timelinePath"}
                    $privatePath=if(Test-Path -LiteralPath $privateResolved -PathType Leaf){$privateResolved}else{$null}
                    $privateFrame=[ordered]@{stage=[string](Value $tf 'stage' '');src=$null;sha256=$null}
                    foreach($key in @('run_length','duplicate_count','start_step','end_step','view_id')){$privateFrame[$key]=Value $tf $key $null}
                    if($privatePath){$privateHash=Add-Source $privatePath;if(-not $assets.ContainsKey($privateHash)){$ext=[IO.Path]::GetExtension($privatePath).ToLowerInvariant();if($ext -notin @('.png','.jpg','.jpeg','.webp')){throw "Unsupported audit image: $privatePath"};$relative="assets/$privateHash$ext";$target=Join-Path $output $relative;[IO.File]::Copy($privatePath,$target,$false);if((Hash $target)-ne $privateHash){throw "Audit image copy SHA mismatch: $privatePath"};$assets[$privateHash]=$relative};$privateFrame.src=$assets[$privateHash];$privateFrame.sha256=$privateHash}
                    $auditFrames.Add($privateFrame)
                }
                $auditGroups=Export-CaptureGroups @(Value $timeline 'capture_groups' @()) $timelineRoot $timelinePath $assets $output
                $auditTimeline=[ordered]@{title=[string](Value $timeline 'title' '');frames=$auditFrames.ToArray();capture_groups=$auditGroups.ToArray();boundaries=@(Value $timeline 'boundaries' @());steps=@(Value $timeline 'steps' @())}
            }
            $items.Add([ordered]@{id="data/input/$($file.Name)";label=$sample;kind='dataset';model_input=$mi;frames=$frames.ToArray();media_quality=(RV-SummarizeMedia $frames.ToArray());references=$references.ToArray();request_origin=$origin;request_text=$request;request_run_status=$requestRunStatus;protocol=$protocol;audit_timeline=$auditTimeline})
        }
        $summaryPath=Join-Path $source 'generation_summary.json'
        if(Test-Path -LiteralPath $summaryPath -PathType Leaf){
            $summary=Read-Json $summaryPath;$null=Add-Source $summaryPath
            $requestedCases=@(Value $summary 'requested_cases' @());$attempts=@(Value $summary 'attempts' @())
            if(-not $files.Count -and (-not $requestedCases.Count -or -not $attempts.Count)){
                throw "No formal inputs and no usable requested_cases/attempts in generation_summary.json: $source"
            }
            $publishedCaseCount=[int](Value $summary 'published_case_count' 0)
            if($requestedCases.Count -and $publishedCaseCount -lt $requestedCases.Count){$generationIncomplete=$true}
            for($ai=0;$ai -lt $attempts.Count;$ai++){
                $attempt=$attempts[$ai];$caseId=[string](Value $attempt 'case_id' "attempt-$($ai+1)");$scene=[string](Value $attempt 'scene' '');$status=[string](Value $attempt 'status' 'unknown');$attemptError=[string](Value $attempt 'error' '')
                $publishedInputs=@(Value $attempt 'published_inputs' @());$failedStatus=$status -match '(?i)fail|error|exception|blocked|stopped|invalid|unsupported|timeout|cancel';$failedAttempt=($publishedInputs.Count -eq 0 -or $failedStatus)
                if(-not $failedAttempt){continue}
                $diagnosticCount++;$generationIncomplete=$true
                $diagFrames=[System.Collections.Generic.List[object]]::new();$auditTimeline=$null;$auditGroups=@();$timelineState='missing';$timelineRel="audit_traces/$caseId/review_timeline.json"
                $timelinePath=Safe-Path $source $timelineRel (Join-Path $source 'audit_traces')
                if($timelinePath){
                    $timeline=Read-Json $timelinePath;$null=Add-Source $timelinePath;$timelineRoot=Split-Path -Parent $timelinePath
                    if([string](Value $timeline 'sample_id' '') -eq $caseId){
                        $timelineState='available';$captureGroups=@(Value $timeline 'capture_groups' @());$privateFrames=@(Value $timeline 'frames' @())
                        if($captureGroups.Count){
                            $auditGroups=Export-CaptureGroups $captureGroups $timelineRoot $timelinePath $assets $output
                            foreach($group in $captureGroups){foreach($view in @(Value $group 'views' @())){
                                if([string](Value $view 'view_id' '') -ne 'agent'){continue}
                                $relativeFrame=[string](Value $view 'path' '');$mediaStatus='invalid_path';$mediaMessage='agent 视角图像路径无效或越出本次尝试目录。';$resolvedFrame=$null
                                if($relativeFrame -and -not [IO.Path]::IsPathRooted($relativeFrame)){$candidate=[IO.Path]::GetFullPath((Join-Path $timelineRoot $relativeFrame));$prefix=[IO.Path]::GetFullPath($timelineRoot).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar;if($candidate.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){if(Test-Path -LiteralPath $candidate -PathType Leaf){$resolvedFrame=$candidate;$mediaStatus='available';$mediaMessage=''}else{$mediaStatus='file_missing';$mediaMessage='agent 视角图像文件缺失。';$generationIncomplete=$true}}}
                                $info=[ordered]@{source_path=$relativeFrame;source_status=$mediaStatus;source_error='';source_message=$mediaMessage;observation_contaminated=$false}
                                $frame=Frame $resolvedFrame ([string](Value $group 'phase_label' '')) $info
                                foreach($key in @('run_length','duplicate_count','start_step','end_step','capture_group_index')){$frame[$key]=Value $group $key $null};$frame.view_id='agent';$diagFrames.Add($frame)
                            }}
                            if(-not $diagFrames.Count){$generationIncomplete=$true;$timelineState='no_agent_frames'}
                        }else{
                          if(-not $privateFrames.Count){$generationIncomplete=$true;$timelineState='no_frames'}
                          foreach($tf in $privateFrames){
                            $relativeFrame=[string](Value $tf 'path' '');$mediaStatus='invalid_path';$mediaMessage='审计帧路径无效或越出本次尝试目录。';$resolvedFrame=$null
                            if($relativeFrame -and -not [IO.Path]::IsPathRooted($relativeFrame)){
                                $candidate=[IO.Path]::GetFullPath((Join-Path $timelineRoot $relativeFrame));$prefix=[IO.Path]::GetFullPath($timelineRoot).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
                                if($candidate.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){
                                    if(Test-Path -LiteralPath $candidate -PathType Leaf){$resolvedFrame=$candidate;$mediaStatus='available';$mediaMessage=''}else{$mediaStatus='file_missing';$mediaMessage='采集时间线引用的帧文件缺失。';$generationIncomplete=$true}
                                }
                            }
                            $info=[ordered]@{source_path=$relativeFrame;source_status=$mediaStatus;source_error='';source_message=$mediaMessage;observation_contaminated=$false}
                            $frame=Frame $resolvedFrame ([string](Value $tf 'stage' '')) $info
                            foreach($key in @('run_length','duplicate_count','start_step','end_step','view_id')){$frame[$key]=Value $tf $key $null}
                            $diagFrames.Add($frame)
                          }
                        }
                        $auditTimeline=[ordered]@{title=[string](Value $timeline 'title' '');frames=@();capture_groups=$auditGroups;boundaries=@(Value $timeline 'boundaries' @());steps=@(Value $timeline 'steps' @())}
                    }else{$timelineState='sample_id_mismatch';$generationIncomplete=$true}
                }else{$generationIncomplete=$true}
                if(-not $attemptError){$attemptError=if($status){"生成状态：$status；该尝试没有发布正式题目。"}else{'该尝试没有发布正式题目。'}}
                $items.Add([ordered]@{id="diagnostic/$caseId/$ai";label="$caseId / $scene / 未发布尝试 $($ai+1)";kind='diagnostic';case_id=$caseId;scene=$scene;status=$status;error=$attemptError;planned_next_steps=@(Value $attempt 'planned_next_steps' (Value $attempt 'planned_actions' @()));timeline_status=$timelineState;frames=$diagFrames.ToArray();audit_timeline=$auditTimeline;media_quality=(RV-SummarizeMedia $diagFrames.ToArray())})
            }
        }
    }elseif(Test-Path -LiteralPath (Join-Path $source 'observations/attempts')){
        $designLinks=@(RV-DesignLinks $source $output $PSScriptRoot)
        $mode='Mechanism';$files=@(Get-ChildItem -LiteralPath (Join-Path $source 'observations/attempts') -Filter result.json -File -Recurse|Sort-Object FullName)
        foreach($file in $files){
            $r=Read-Json $file.FullName;$null=Add-Source $file.FullName;$capturePath=Join-Path $file.DirectoryName 'capture_index.json'
            $captures=if(Test-Path -LiteralPath $capturePath){RV-ExpandCaptureViews (Read-Json $capturePath) (RV-LegacyMetadataOnlyReset $source)}else{@()};if(Test-Path -LiteralPath $capturePath){$null=Add-Source $capturePath}
            $frames=[System.Collections.Generic.List[object]]::new();foreach($c in $captures){$info=RV-MediaInfo $file.DirectoryName ([string](Value $c 'rgb_path' '')) $file.DirectoryName $c;$frames.Add((Frame $info.resolved_path ([string](Value $c 'label' '')) $info))}
            $relative=$file.FullName.Substring($source.Length).TrimStart('\','/').Replace('\','/')
            $checkSummary=@(foreach($check in @(Value $r 'checks' @())){[ordered]@{name=Value $check 'name' '';passed=Value $check 'passed'}})
            $actionsPath=Join-Path $file.DirectoryName 'actions_by_reset.json';$segments=if(Test-Path -LiteralPath $actionsPath){Read-Json $actionsPath}else{@()}
            if(Test-Path -LiteralPath $actionsPath){$null=Add-Source $actionsPath}
            $presentation=Get-MechanismReviewPresentation $r $captures $segments
            $rawFiles=[System.Collections.Generic.List[object]]::new();$rawFolder=Join-Path $output ('raw/'+$relative.Replace('/result.json',''));[IO.Directory]::CreateDirectory($rawFolder)|Out-Null
            foreach($rawName in @('result.json','capture_index.json','actions_by_reset.json')){$rawSource=Join-Path $file.DirectoryName $rawName;if(Test-Path -LiteralPath $rawSource){[IO.File]::Copy($rawSource,(Join-Path $rawFolder $rawName),$false);$rawFiles.Add(@{label=$rawName;path='raw/'+$relative.Replace('result.json',$rawName)})}}
            foreach($link in $designLinks){$rawFiles.Add($link)}
            $items.Add([ordered]@{id=$relative;label=([string](Value $r 'case_id' '')+' / '+[string](Value $r 'scene' ''));kind='mechanism';fact_id=Value $r 'fact_id' '';status=Value $r 'status' '';error=Value $r 'error' '';native_measurement_valid=Value $r 'native_measurement_valid';observation_invalid_reason=Value $r 'observation_invalid_reason';checks=$checkSummary;frames=$frames.ToArray();media_quality=(RV-SummarizeMedia $frames.ToArray());presentation=$presentation;raw_files=$rawFiles.ToArray()})
        }
    }else{throw "Unknown source format: $source"}
    if(-not $items.Count){throw "No records: $source"}
    # Include displayed request/reference content in the batch identity, preserving reviews only for identical data.
    $content=ConvertTo-Json -InputObject $items.ToArray() -Depth 100 -Compress
    $bytes=[Text.Encoding]::UTF8.GetBytes((($hashes.ToArray()|Sort-Object -Unique)-join "`n")+"`n"+$content)
    $batchId=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    $name=if($bi -lt $BatchName.Count -and $BatchName[$bi]){$BatchName[$bi]}else{[System.IO.Path]::GetFileName($source)}
    $batch=[ordered]@{schema='scene-review-batch/v1';id=$batchId;name=$name;items=$items.ToArray()};if($mode -eq 'Mechanism'){$batch['review_revision']='scene-v2'};$batches.Add($batch)
    $questions=0;if($mode -eq 'Dataset'){foreach($item in $items){if($item.kind -eq 'dataset'){$questions+=@(Value $item.model_input 'questions' @()).Count}}}
    $allFrames=@(foreach($item in $items){foreach($frame in $item.frames){$frame}});$quality=RV-SummarizeMedia $allFrames
    $batch['source_media_status']=if($generationIncomplete -or $quality.issue_items -gt 0){'source_incomplete'}else{'media_present_not_visually_approved'}
    $invalidNative=@($items|Where-Object{(Value $_ 'native_measurement_valid') -eq $false}).Count
    $preparedInBatch=@($items|Where-Object{[string](Value $_ 'request_origin' '') -eq 'prepared'}).Count;$formalRecords=@($items|Where-Object{[string](Value $_ 'kind' '') -ne 'diagnostic'}).Count
    $reports.Add([ordered]@{name=$name;mode=$mode;batch_id=$batchId;source_root=$source;records=$formalRecords;diagnostic_attempts=$diagnosticCount;generation_incomplete=$generationIncomplete;questions=$questions;prepared_requests=$preparedInBatch;image_references=$imageCount;missing_images=$missing;invalid_native_measurements=$invalidNative;media_quality=$quality})
}
$encoded=ConvertTo-Json -InputObject $batches.ToArray() -Depth 100 -Compress
Write-Text (Join-Path $output 'batches.js') ("window.REVIEW_BATCHES = $encoded;`n")
$sourceIncomplete=@($reports|Where-Object{$_.media_quality.issue_items -gt 0 -or $_.generation_incomplete}).Count -gt 0
$preparedCount=0;foreach($report in $reports){$preparedCount+=$report.prepared_requests}
$manifest=[ordered]@{schema='scene-review-site/v1';created_utc=[DateTime]::UtcNow.ToString('o');batches=$reports.ToArray();copied_unique_images=$assets.Count;source_media_status=if($sourceIncomplete){'source_incomplete'}else{'media_present_not_visually_approved'};scene_presentation_version='mechanism-scene-review/v2';reference_answers_included=[bool]$IncludeReferenceAnswers;predictions_displayed=$false;prepared_requests=$preparedCount;requests_note='Prepared requests are shown only when their complete model_input and ordered media hashes match; prepared_not_sent means no model call is claimed. Legacy requests are reconstructed; only matching saved run text is recorded.'}
Write-Text (Join-Path $output 'site_manifest.json') ((ConvertTo-Json -InputObject $manifest -Depth 30)+"`n")
Write-Text (Join-Path $output '打开方式.txt') "双击 index.html，用新版 Chrome 或 Edge 打开。全部资源在本目录，无需联网或启动服务器。`n审核结果存于当前浏览器；结束时点击“导出审核结果”保留 JSON。换浏览器或移动目录后可恢复审核。`n旧批次请求文本只能重建；机制探测没有模型输入或正式题目。`n请移动整个目录，不要只复制 index.html。`n"
Write-Output (Join-Path $output 'index.html')
if($sourceIncomplete){Write-Warning '源数据存在未完成的构造或图片异常：已保留诊断网页。请分别查看 generation_incomplete、diagnostic_attempts 和 media_quality；已有图片齐全不等于题目构造完成，重建网页不能补做原生动作。'}
