[CmdletBinding()]
param([Parameter(Mandatory)][string]$WebRoot)
# Add concrete scene narratives to a previously generated local site. Source
# simulator files and browser review storage are never modified.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'review_web/mechanism_review.ps1')
$encoding=[Text.UTF8Encoding]::new($false)
function Read-SiteJson([string]$Path){return ,(Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable -NoEnumerate)}
function Write-SiteText([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,$encoding)}
function Confined-File([string]$Root,[string]$Relative){
    if([IO.Path]::IsPathRooted($Relative)){throw 'Absolute record path not allowed'}
    $path=[IO.Path]::GetFullPath((Join-Path $Root $Relative));$prefix=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
    if(-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw "Record path escapes source: $Relative"}
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Missing record: $path"};return $path
}
$root=[IO.Path]::GetFullPath($WebRoot).TrimEnd('\','/')
$manifest=Read-SiteJson (Join-Path $root 'site_manifest.json')
if($manifest.schema -ne 'scene-review-site/v1'){throw 'Not a supported generated review site'}
$dataPath=Join-Path $root 'batches.js';$raw=Get-Content -LiteralPath $dataPath -Raw -Encoding UTF8;$prefix='window.REVIEW_BATCHES = '
if(-not $raw.StartsWith($prefix)){throw 'Invalid batch script prefix'}
$batches=ConvertFrom-Json -InputObject ($raw.Substring($prefix.Length).Trim().TrimEnd(';')) -AsHashtable -NoEnumerate
$stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ');$backup=Join-Path $root "history/before_scene_review_$stamp"
[IO.Directory]::CreateDirectory($backup)|Out-Null
foreach($name in @('index.html','review.css','review.js','batches.js','site_manifest.json','validation.json')){$path=Join-Path $root $name;if(Test-Path -LiteralPath $path){[IO.File]::Copy($path,(Join-Path $backup $name),$false)}}
$count=0;$frameNotes=0;$questionCount=0;$undetermined=0;$issues=[System.Collections.Generic.List[string]]::new();$presentations=[ordered]@{}
foreach($batch in $batches){
    $mode=@($manifest.batches|Where-Object{$_.batch_id -eq $batch.id})
    if($mode.Count -ne 1){throw "No unique source mapping: $($batch.id)"}
    if($mode[0].mode -ne 'Mechanism'){continue}
    $source=[IO.Path]::GetFullPath([string]$mode[0].source_root).TrimEnd('\','/')
    $designLinks=@(RV-DesignLinks $source $root $PSScriptRoot)
    foreach($item in $batch.items){
        $path=Confined-File $source $item.id;$dir=[IO.Path]::GetDirectoryName($path)
        $result=Read-SiteJson $path;$captures=RV-ExpandCaptureViews (Read-SiteJson (Join-Path $dir 'capture_index.json')) (RV-LegacyMetadataOnlyReset $source);$segments=Read-SiteJson (Join-Path $dir 'actions_by_reset.json')
        if(@($captures).Count -ne @($item.frames).Count){throw "Screenshot count drift: $($item.id)"}
        $presentation=Get-MechanismReviewPresentation $result $captures $segments
        if(@($presentation.frame_notes).Count -ne @($captures).Count){throw "Frame explanation count mismatch: $($item.id)"}
        $item['presentation']=$presentation
        $links=[System.Collections.Generic.List[object]]::new()
        $relativeFolder=$item.id.Substring(0,$item.id.Length-'result.json'.Length)
        $outDir=Join-Path $root ('raw/'+$relativeFolder);[IO.Directory]::CreateDirectory($outDir)|Out-Null
        foreach($name in @('result.json','capture_index.json','actions_by_reset.json')){
            $original=Join-Path $dir $name;$dest=Join-Path $outDir $name
            if(Test-Path -LiteralPath $dest){if((Get-FileHash -LiteralPath $dest).Hash -ne (Get-FileHash -LiteralPath $original).Hash){throw "Refusing to replace different raw evidence: $dest"}}else{[IO.File]::Copy($original,$dest,$false)}
            $links.Add(@{label=$name;path='raw/'+$relativeFolder+$name})
        }
        foreach($link in $designLinks){$links.Add($link)}
        $item['raw_files']=$links.ToArray();$count++;$frameNotes+=@($presentation.frame_notes).Count
        foreach($q in @($presentation.questions)){$questionCount++;if($q.answer_status -ne 'observed'){$undetermined++};if(-not $q.text){$issues.Add('Empty question: '+$item.id)}}
        $presentations[$item.id]=$presentation
    }
    # The expanded scope gets its own storage namespace; preserve old screenshot-only decisions.
    $batch['review_revision']='scene-v2'
}
if($count -eq 0){throw 'This site contains no mechanism records'}
$text=ConvertTo-Json -InputObject $batches -Depth 100 -Compress
Write-SiteText $dataPath ("window.REVIEW_BATCHES = $text;`n")
foreach($name in @('index.html','review.css','review.js')){[IO.File]::Copy((Join-Path $PSScriptRoot "review_web/$name"),(Join-Path $root $name),$true)}
$manifest['scene_presentation_version']='mechanism-scene-review/v2';$manifest['scene_update_utc']=[DateTime]::UtcNow.ToString('o');$manifest['old_screenshot_review_storage_preserved']=$true
Write-SiteText (Join-Path $root 'site_manifest.json') ((ConvertTo-Json -InputObject $manifest -Depth 40)+"`n")
Write-SiteText (Join-Path $root 'review_presentation.json') ((ConvertTo-Json -InputObject @{schema='mechanism-scene-review/v2';items=$presentations} -Depth 100)+"`n")
$report=[ordered]@{created_utc=[DateTime]::UtcNow.ToString('o');narrated_attempts=$count;explained_frame_references=$frameNotes;draft_questions=$questionCount;undetermined_questions=$undetermined;empty_question_errors=$issues.ToArray();original_records_modified=$false;browser_reviews_modified=$false;browser_interactions_verified=$false;python_or_simulator_run=$false;backup=$backup}
Write-SiteText (Join-Path $root 'scene_validation.json') ((ConvertTo-Json -InputObject $report -Depth 20)+"`n")
$report|ConvertTo-Json -Depth 20
