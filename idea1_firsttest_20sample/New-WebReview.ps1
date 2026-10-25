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
function Read-Json([string]$Path) { return ,(Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable -NoEnumerate) }
function Value($Object,[string]$Key,$Default=$null) { if($null -ne $Object -and $Object -is [System.Collections.IDictionary] -and $Object.Contains($Key)){return $Object[$Key]};return $Default }
function Hash([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Write-Text([string]$Path,[string]$Text){[System.IO.File]::WriteAllText($Path,$Text,$encoding)}
function Safe-Path([string]$Root,[string]$Relative,[string]$Boundary) {
    if(-not $Relative -or [System.IO.Path]::IsPathRooted($Relative)){return $null}
    $path=[System.IO.Path]::GetFullPath((Join-Path $Root $Relative))
    $allowed=[System.IO.Path]::GetFullPath($Boundary).TrimEnd('\','/')+[System.IO.Path]::DirectorySeparatorChar
    if(-not $path.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)-or -not(Test-Path -LiteralPath $path -PathType Leaf)){return $null}
    return $path
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
    $source=$sources[$bi];$items=[System.Collections.Generic.List[object]]::new();$hashes=[System.Collections.Generic.List[string]]::new();$missing=0;$imageCount=0
    function Add-Source([string]$Path){$h=Hash $Path;$rel=$Path.Substring($source.Length).TrimStart('\','/').Replace('\','/');$hashes.Add("$rel`0$h");return $h}
    function Frame([string]$Path,[string]$Stage){
        $script:imageCount++
        if(-not $Path){$script:missing++;return [ordered]@{stage=$Stage;src=$null;sha256=$null}}
        $h=Add-Source $Path
        if(-not $assets.ContainsKey($h)){
            $ext=[System.IO.Path]::GetExtension($Path).ToLowerInvariant();if($ext -notin @('.png','.jpg','.jpeg','.webp')){throw "Unsupported image: $Path"}
            $relative="assets/$h$ext";$target=Join-Path $output $relative;[System.IO.File]::Copy($Path,$target,$false)
            if((Hash $target)-ne $h){throw "Image copy SHA mismatch: $Path"};$assets[$h]=$relative
        }
        return [ordered]@{stage=$Stage;src=$assets[$h];sha256=$h}
    }
    if(Test-Path -LiteralPath (Join-Path $source 'data/input')){
        $mode='Dataset';$files=@(Get-ChildItem -LiteralPath (Join-Path $source 'data/input') -Filter '*.json' -File|Sort-Object Name)
        foreach($file in $files){
            $r=Read-Json $file.FullName;$sourceHash=Add-Source $file.FullName;$mi=Value $r 'model_input';if(-not $mi){throw "No model_input: $file"}
            $sample=[string](Value $r 'sample_id' $file.BaseName);$frames=[System.Collections.Generic.List[object]]::new()
            foreach($f in @(Value $mi 'frames' @())){$path=Safe-Path $source ([string](Value $f 'path' '')) (Join-Path $source 'data/media');$frames.Add((Frame $path ([string](Value $f 'stage' ''))))}
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
            $origin='reconstructed';$request=$null;$requestRunStatus=$null
            if($predictions.ContainsKey($sample)){
                $p=$predictions[$sample];$text=Value $p 'request_text' $null
                if($text){
                    $expectedHashes=@($frames|ForEach-Object{$_.sha256});$actualHashes=@(Value $p 'media_sha256' @())
                    if([string](Value $p 'source_sha256' '') -ne $sourceHash -or ($expectedHashes -join ',') -ne ($actualHashes -join ',')){throw "Recorded request input/image hashes mismatch: $sample"}
                    $origin='recorded';$request=[string]$text;$requestRunStatus=[string](Value $p 'status' 'unknown')
                }
            }
            $items.Add([ordered]@{id="data/input/$($file.Name)";label=$sample;kind='dataset';model_input=$mi;frames=$frames.ToArray();references=$references.ToArray();request_origin=$origin;request_text=$request;request_run_status=$requestRunStatus})
        }
    }elseif(Test-Path -LiteralPath (Join-Path $source 'observations/attempts')){
        $designLinks=@(RV-DesignLinks $source $output $PSScriptRoot)
        $mode='Mechanism';$files=@(Get-ChildItem -LiteralPath (Join-Path $source 'observations/attempts') -Filter result.json -File -Recurse|Sort-Object FullName)
        foreach($file in $files){
            $r=Read-Json $file.FullName;$null=Add-Source $file.FullName;$capturePath=Join-Path $file.DirectoryName 'capture_index.json'
            $captures=if(Test-Path -LiteralPath $capturePath){RV-ExpandCaptureViews (Read-Json $capturePath)}else{@()};if(Test-Path -LiteralPath $capturePath){$null=Add-Source $capturePath}
            $frames=[System.Collections.Generic.List[object]]::new();foreach($c in $captures){$path=Safe-Path $file.DirectoryName ([string](Value $c 'rgb_path' '')) $file.DirectoryName;$frames.Add((Frame $path ([string](Value $c 'label' ''))))}
            $relative=$file.FullName.Substring($source.Length).TrimStart('\','/').Replace('\','/')
            $checkSummary=@(foreach($check in @(Value $r 'checks' @())){[ordered]@{name=Value $check 'name' '';passed=Value $check 'passed'}})
            $actionsPath=Join-Path $file.DirectoryName 'actions_by_reset.json';$segments=if(Test-Path -LiteralPath $actionsPath){Read-Json $actionsPath}else{@()}
            if(Test-Path -LiteralPath $actionsPath){$null=Add-Source $actionsPath}
            $presentation=Get-MechanismReviewPresentation $r $captures $segments
            $rawFiles=[System.Collections.Generic.List[object]]::new();$rawFolder=Join-Path $output ('raw/'+$relative.Replace('/result.json',''));[IO.Directory]::CreateDirectory($rawFolder)|Out-Null
            foreach($rawName in @('result.json','capture_index.json','actions_by_reset.json')){$rawSource=Join-Path $file.DirectoryName $rawName;if(Test-Path -LiteralPath $rawSource){[IO.File]::Copy($rawSource,(Join-Path $rawFolder $rawName),$false);$rawFiles.Add(@{label=$rawName;path='raw/'+$relative.Replace('result.json',$rawName)})}}
            foreach($link in $designLinks){$rawFiles.Add($link)}
            $items.Add([ordered]@{id=$relative;label=([string](Value $r 'case_id' '')+' / '+[string](Value $r 'scene' ''));kind='mechanism';fact_id=Value $r 'fact_id' '';status=Value $r 'status' '';error=Value $r 'error' '';checks=$checkSummary;frames=$frames.ToArray();presentation=$presentation;raw_files=$rawFiles.ToArray()})
        }
    }else{throw "Unknown source format: $source"}
    if(-not $items.Count){throw "No records: $source"}
    # Include displayed request/reference content in the batch identity, preserving reviews only for identical data.
    $content=ConvertTo-Json -InputObject $items.ToArray() -Depth 100 -Compress
    $bytes=[Text.Encoding]::UTF8.GetBytes((($hashes.ToArray()|Sort-Object -Unique)-join "`n")+"`n"+$content)
    $batchId=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    $name=if($bi -lt $BatchName.Count -and $BatchName[$bi]){$BatchName[$bi]}else{[System.IO.Path]::GetFileName($source)}
    $batch=[ordered]@{schema='scene-review-batch/v1';id=$batchId;name=$name;items=$items.ToArray()};if($mode -eq 'Mechanism'){$batch['review_revision']='scene-v2'};$batches.Add($batch)
    $questions=0;if($mode -eq 'Dataset'){foreach($item in $items){$questions+=@(Value $item.model_input 'questions' @()).Count}}
    $reports.Add([ordered]@{name=$name;mode=$mode;batch_id=$batchId;source_root=$source;records=$items.Count;questions=$questions;image_references=$imageCount;missing_images=$missing})
}
$encoded=ConvertTo-Json -InputObject $batches.ToArray() -Depth 100 -Compress
Write-Text (Join-Path $output 'batches.js') ("window.REVIEW_BATCHES = $encoded;`n")
$manifest=[ordered]@{schema='scene-review-site/v1';created_utc=[DateTime]::UtcNow.ToString('o');batches=$reports.ToArray();copied_unique_images=$assets.Count;reference_answers_included=[bool]$IncludeReferenceAnswers;predictions_displayed=$false;requests_note='Old batches reconstruct the current runner text; only hash-matched saved request_text is marked recorded.'}
Write-Text (Join-Path $output 'site_manifest.json') ((ConvertTo-Json -InputObject $manifest -Depth 30)+"`n")
Write-Text (Join-Path $output '打开方式.txt') "双击 index.html，用新版 Chrome 或 Edge 打开。全部资源在本目录，无需联网或启动服务器。`n审核结果存于当前浏览器；结束时点击“导出审核结果”保留 JSON。换浏览器或移动目录后可恢复审核。`n旧批次请求文本只能重建；机制探测没有模型输入或正式题目。`n请移动整个目录，不要只复制 index.html。`n"
Write-Output (Join-Path $output 'index.html')
