param(
    [Parameter(Mandatory=$true)][string]$SourceZip,
    [Parameter(Mandatory=$true)][string]$Destination
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$project = Split-Path -Parent $PSScriptRoot
$policy = Get-Content -LiteralPath (Join-Path $project 'hard_accepted_cases.json') -Raw | ConvertFrom-Json
$source = (Resolve-Path -LiteralPath $SourceZip).Path
$digest = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
if ($digest -ne $policy.source_archive_sha256) { throw 'Source ZIP does not match the human-reviewed batch. No extraction performed.' }
$target = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $target) { throw "Refusing to overwrite an existing acceptance archive: $target" }
$null = New-Item -ItemType Directory -Path $target
$zip = [IO.Compression.ZipFile]::OpenRead($source)
$copied = [Collections.Generic.List[object]]::new()
try {
    # This batch published only the two accepted cases. Their content-addressed
    # media are shared; take the complete media directory to preserve all links.
    $selected = @($zip.Entries | Where-Object {
        $_.FullName -match '^dataset/audit_traces/H04-[23]/' -or
        $_.FullName -match '^dataset/(data/input|prepared_requests|hidden_gold)/H04-[23]_[VS]\.json$' -or
        $_.FullName -match '^dataset/data/media/' -or
        $_.FullName -match '^source/'
    })
    if (-not $zip.GetEntry('dataset/data/input/H04-2_V.json') -or
        -not $zip.GetEntry('dataset/data/input/H04-3_V.json')) { throw 'Accepted public input is absent.' }
    foreach ($entry in $selected) {
        if ($entry.FullName.EndsWith('/')) { continue }
        $relative = if ($entry.FullName.StartsWith('dataset/')) { $entry.FullName.Substring(8) } else { '_provenance/' + $entry.FullName }
        $output = [IO.Path]::GetFullPath((Join-Path $target $relative))
        if (-not $output.StartsWith($target.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe ZIP entry path.' }
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $output, $false)
        $copied.Add([pscustomobject]@{path=$relative; bytes=$entry.Length; sha256=(Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()})
    }
    foreach ($name in @('generation_summary.json','run_manifest.json','inventory_survey.json')) {
        $entry = $zip.GetEntry('dataset/' + $name)
        if ($entry) {
            $output = Join-Path $target ('_provenance/original_' + $name)
            $null = New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $output, $false)
            $copied.Add([pscustomobject]@{path=('_provenance/original_' + $name);bytes=$entry.Length;sha256=(Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()})
        }
    }
} finally { $zip.Dispose() }
$receipt = [ordered]@{schema='hard-accepted-raw-copy/v1'; case_ids=@($policy.case_ids); human_acceptance_date=$policy.accepted_on;
    original_zip=$source; original_zip_sha256=$digest; original_bytes_unchanged=$true;
    model_evaluated=$false; copied_file_count=$copied.Count; files=@($copied.ToArray())}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $target 'acceptance_manifest.json') -Encoding utf8
Copy-Item -LiteralPath (Join-Path $project 'hard_accepted_cases.json') -Destination (Join-Path $target 'hard_accepted_cases.json')
Write-Output "Saved accepted originals: $target ($($copied.Count) files). Original ZIP remains unchanged; no model or simulator was run."
