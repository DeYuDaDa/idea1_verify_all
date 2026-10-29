param(
    [Parameter(Mandatory=$true)][string[]]$SourceZip,
    [Parameter(Mandatory=$true)][string[]]$CaseIds,
    [Parameter(Mandatory=$true)][string]$Destination,
    [string[]]$HumanAcceptedCaseIds = @(),
    [switch]$CopyOriginalZip
)
# File management only. Never run Unity, models or change original inputs.
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$target=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $target){throw "Archive already exists: $target"}
if(@($CaseIds|Select-Object -Unique).Count -ne $CaseIds.Count){throw 'Duplicate requested case ID'}
foreach($id in $CaseIds){if($id -notmatch '^H0[1-5]-[1-4]$'){throw "Unsupported case ID: $id"}}
foreach($id in $HumanAcceptedCaseIds){if($id -notin $CaseIds){throw "Accepted ID outside selection: $id"}}
$project=Split-Path -Parent $PSScriptRoot
$policy=Get-Content -LiteralPath (Join-Path $project 'hard_accepted_cases.json') -Raw|ConvertFrom-Json -AsHashtable
$utf8=[Text.UTF8Encoding]::new($false)
$files=[Collections.Generic.List[object]]::new();$sources=[Collections.Generic.List[object]]::new();$found=@{}
[IO.Directory]::CreateDirectory($target)|Out-Null
function Save-Entry($entry,[string]$relative){
    if($entry.FullName.EndsWith('/')){return}
    $path=[IO.Path]::GetFullPath((Join-Path $target $relative))
    if(-not $path.StartsWith($target.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe archive entry'}
    if(Test-Path -LiteralPath $path){throw "Duplicate archive entry: $relative"}
    [IO.Directory]::CreateDirectory((Split-Path -Parent $path))|Out-Null
    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$path,$false)
    $files.Add([ordered]@{path=$relative;bytes=$entry.Length;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()})
}
function Read-Entry($zip,[string]$name){
    $entry=$zip.GetEntry($name);if(-not $entry){throw "Missing ZIP entry: $name"}
    $reader=[IO.StreamReader]::new($entry.Open());try{return ($reader.ReadToEnd()|ConvertFrom-Json -AsHashtable)}finally{$reader.Dispose()}
}
foreach($inputZip in $SourceZip){
    $path=(Resolve-Path -LiteralPath $inputZip).Path
    $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $zip=[IO.Compression.ZipFile]::OpenRead($path)
    try{
        $selected=@($CaseIds|Where-Object{$zip.GetEntry("dataset/data/input/${_}_V.json")})
        if(-not $selected.Count){throw "Source has no requested published case: $path"}
        $sourceIndex=$sources.Count
        $media=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach($id in $selected){
            if($found.ContainsKey($id)){throw "More than one source contains requested case $id; choose exact source ZIPs"}
            if($id -in $HumanAcceptedCaseIds){
                $approved=@($policy.accepted_sources|Where-Object{$id -in $_.case_ids -and $_.sha256 -eq $hash})
                if($approved.Count -ne 1){throw "Source digest not approved for $id"}
            }
            foreach($mode in @('V','S')){
                $public=Read-Entry $zip "dataset/data/input/${id}_${mode}.json"
                $request=Read-Entry $zip "dataset/prepared_requests/${id}_${mode}.json"
                $gold=Read-Entry $zip "dataset/hidden_gold/${id}_${mode}.json"
                if($public.sample_id -ne "${id}_${mode}" -or $gold.sample_id -ne $public.sample_id){throw 'Sample identity mismatch'}
                foreach($frame in $public.model_input.frames){
                    $rel=[string]$frame.path
                    if($rel -notmatch '^data/media/[a-zA-Z0-9_.-]+\.png$' -or -not $zip.GetEntry('dataset/'+$rel)){throw "Missing/unsafe media: $rel"}
                    $null=$media.Add($rel)
                }
                if($mode -eq 'V' -and -not $public.model_input.frames.Count){throw "Empty V input: $id"}
                if($mode -eq 'S' -and $public.model_input.frames.Count){throw "S unexpectedly contains frames: $id"}
                if($request.status -ne 'prepared_not_sent'){throw 'Unexpected request execution state'}
            }
            $found[$id]=[ordered]@{source_index=$sourceIndex;status=if($id -in $HumanAcceptedCaseIds){'human_visual_accepted'}else{'candidate_pending_human_review'}}
        }
        foreach($entry in $zip.Entries){
            $name=$entry.FullName
            if($name.StartsWith('source/')){Save-Entry $entry ("_provenance/source_$sourceIndex/"+$name);continue}
            foreach($id in $selected){
                if($name.StartsWith("dataset/audit_traces/$id/") -or
                   $name -match ('^dataset/(data/input|prepared_requests|hidden_gold)/'+[regex]::Escape($id)+'_[VS]\.json$')){
                    Save-Entry $entry $name.Substring(8);break
                }
            }
        }
        foreach($rel in $media){
            # Shared content-addressed media can be reused between independent cases.
            if(-not(Test-Path -LiteralPath (Join-Path $target $rel))){Save-Entry ($zip.GetEntry('dataset/'+$rel)) $rel}
        }
        foreach($name in @('generation_summary.json','run_manifest.json','inventory_survey.json')){
            $entry=$zip.GetEntry('dataset/'+$name);if($entry){Save-Entry $entry "_provenance/source_$sourceIndex/original_$name"}
        }
        $raw=$null
        if($CopyOriginalZip){
            $raw="_provenance/source_$sourceIndex/original.zip";$rawPath=Join-Path $target $raw
            [IO.Directory]::CreateDirectory((Split-Path -Parent $rawPath))|Out-Null
            Copy-Item -LiteralPath $path -Destination $rawPath
            if((Get-FileHash -LiteralPath $rawPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash){throw 'Original ZIP copy hash mismatch'}
        }
        $sources.Add([ordered]@{original_zip=$path;sha256=$hash;case_ids=$selected;raw_zip_copy=$raw})
    }finally{$zip.Dispose()}
}
$missing=@($CaseIds|Where-Object{-not $found.ContainsKey($_)})
if($missing.Count){throw "Missing published cases: $($missing -join ','). Partial files retained, no completed manifest written."}
foreach($id in $CaseIds){foreach($mode in @('V','S')){
    $request=Get-Content -LiteralPath (Join-Path $target "prepared_requests/${id}_${mode}.json") -Raw|ConvertFrom-Json -AsHashtable
    $inputHash=(Get-FileHash -LiteralPath (Join-Path $target "data/input/${id}_${mode}.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    if($inputHash -ne $request.model_input_sha256){throw "Prepared request/input hash mismatch: $id/$mode"}
}}
$receipt=[ordered]@{schema='hard-family-raw-archive/v1';case_ids=$CaseIds;cases=$found;sources=$sources.ToArray();
    original_input_bytes_unchanged=$true;model_evaluated=$false;all_cases_human_accepted=(@($CaseIds|Where-Object{$_ -notin $HumanAcceptedCaseIds}).Count -eq 0);
    files=$files.ToArray();note='Only explicitly accepted cases have human acceptance. Candidate archive does not assert benchmark readiness.'}
[IO.File]::WriteAllText((Join-Path $target 'acceptance_manifest.json'),($receipt|ConvertTo-Json -Depth 12),$utf8)
Write-Output "Archived exact originals: $target; cases=$($CaseIds -join ','); files=$($files.Count)"
