[CmdletBinding()]
param()

# Standalone mock-fixture contract checks for New-WebReview.ps1.
# Run with PowerShell 7 from any directory; this file is intentionally not
# executed by the Windows editing workflow.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:failed = $true
$script:tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('hard-web-review-' + [guid]::NewGuid().ToString('N'))
$script:sourceScript = Join-Path (Split-Path -Parent $PSScriptRoot) 'New-WebReview.ps1'
$script:utf8 = [Text.UTF8Encoding]::new($false)

function Assert([bool]$Condition,[string]$Message) {
    if(-not $Condition){throw "ASSERTION FAILED: $Message"}
}

function Write-Json([string]$Path,$Value) {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    [IO.File]::WriteAllText($Path,(ConvertTo-Json -InputObject $Value -Depth 100 -Compress),$script:utf8)
}

function Sha256-Bytes([byte[]]$Bytes) {
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}

function New-Fixture([string]$Name) {
    $root=Join-Path $script:tempRoot $Name
    $source=Join-Path $root 'source'
    [IO.Directory]::CreateDirectory((Join-Path $source 'data/input')) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $source 'data/media')) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $source 'prepared_requests')) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $source 'audit_traces/H01-1')) | Out-Null
    # Valid 1x1 transparent PNG. This is a deterministic fixture, not generated evidence.
    $png=[Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pQAAAABJRU5ErkJggg==')
    $mediaPath=Join-Path $source 'data/media/public.png'
    [IO.File]::WriteAllBytes($mediaPath,$png)
    [IO.File]::WriteAllBytes((Join-Path $source 'audit_traces/H01-1/private.png'),$png)
    $timeline=[ordered]@{
        sample_id='H01-1'
        title='受控嵌套移出场景'
        frames=@(@{path='private.png';stage='private-only-stage';run_length=2;duplicate_count=1;start_step=3;end_step=4;view_id='audit-view'})
        capture_groups=@(@{capture_group_index=3;global_step=3;reset_index=0;phase_id=2;phase_label='目标事件后';phase_public=$false;phase_kind='event';frame_status='captured';run_length=2;duplicate_count=1;start_step=3;end_step=4;step_numbers=@(3,4);views=@(@{view_id='agent';view_role='agent_first_person';purpose='model_evidence';path='private.png';pixel_sha256='fixture-agent'},@{view_id='overview';view_role='third_party';purpose='distant_room_overview';path='private.png';pixel_sha256='fixture-overview'})})
        boundaries=@(@{step_index=3;label='PRIVATE_BOUNDARY_LABEL';kind='target-event'})
        steps=@('PRIVATE_ACTION_TEXT')
    }
    Write-Json (Join-Path $source 'audit_traces/H01-1/review_timeline.json') $timeline

    $inputs=@(
        [ordered]@{sample_id='H01-1_V';protocol='hard-selective-V/v1';withPublicFrame=$true}
        [ordered]@{sample_id='H01-1_S';protocol='hard-selective-S/v1';withPublicFrame=$false}
    )
    foreach($spec in $inputs) {
        $mi=[ordered]@{
            protocol=$spec.protocol
            protocol_note='Frozen public protocol note.'
            objects=@(@{alias='A';object_type='Mug'})
            initial_state_declarations=@(@{subject='A';predicate='liquid';value='empty'})
            history=@(@{stage='public-history';facts=@(@{subject='A';predicate='liquid';value='water'})})
            rules=@('Public rule remains visible.')
            event=@{action='PutObject';subject='A';destination='Machine';success='must_be_observed';settle_steps=4}
            frames=@()
            questions=@(@{subject='A';predicate='liquid';question='What is A holding?';answer_mode='current_value'})
            unknown_future_field=[ordered]@{must_survive=$true;nested=@('alpha','beta')}
        }
        if($spec.withPublicFrame){$mi.frames=@(@{path='data/media/public.png';stage='public-initial';run_length=2;duplicate_count=1;start_step=0;end_step=1;capture_group_index=0;view_id='public-view';boundary_labels=@('public-boundary')})}
        $record=[ordered]@{sample_id=$spec.sample_id;model_input=$mi}
        $inputPath=Join-Path $source "data/input/$($spec.sample_id).json"
        Write-Json $inputPath $record
        $mediaHashes=@();if($spec.withPublicFrame){$mediaHashes=@((Sha256-Bytes $png))}
        $request=[ordered]@{
            schema='hard-request/v1'
            model_input_sha256=(Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash.ToLowerInvariant()
            request_text=(ConvertTo-Json -InputObject $mi -Depth 100)
            media_sha256=$mediaHashes
            status='prepared_not_sent'
            protocol=$spec.protocol
            model_input=$mi
            audit_timeline_path='audit_traces/H01-1/review_timeline.json'
        }
        Write-Json (Join-Path $source "prepared_requests/$($spec.sample_id).json") $request
    }
    return [ordered]@{root=$root;source=$source;output=(Join-Path $root 'review-output')}
}

function New-FailureOnlyFixture([string]$Name) {
    $fixture=New-Fixture $Name
    Get-ChildItem -LiteralPath (Join-Path $fixture.source 'data/input') -File | Remove-Item -Force
    Get-ChildItem -LiteralPath (Join-Path $fixture.source 'prepared_requests') -File | Remove-Item -Force
    $summary=[ordered]@{
        requested_cases=@(@{case_id='H01-1';scene='two-cup-history'})
        attempts=@(@{case_id='H01-1';scene='two-cup-history';status='failed';error='native construction failed';published_inputs=@()})
        published_case_count=0
    }
    Write-Json (Join-Path $fixture.source 'generation_summary.json') $summary
    return $fixture
}

function Invoke-Review($Fixture) {
    & $script:sourceScript -SourceRoot @($Fixture.source) -OutputRoot $Fixture.output | Out-Null
}

function Invoke-ReviewExpectFailure($Fixture,[string]$MessagePattern) {
    $failed=$false
    try { Invoke-Review $Fixture }
    catch { $failed=$true; Assert ($_.Exception.Message -match $MessagePattern) "Expected failure matching '$MessagePattern'; got: $($_.Exception.Message)" }
    Assert $failed "Expected New-WebReview.ps1 to refuse fixture '$($Fixture.source)'"
}

try {
    if(-not(Test-Path -LiteralPath $script:sourceScript -PathType Leaf)){throw "Cannot locate exporter: $script:sourceScript"}
    [IO.Directory]::CreateDirectory($script:tempRoot) | Out-Null

    $valid=New-Fixture 'valid'
    Invoke-Review $valid
    $batchScript=Get-Content -LiteralPath (Join-Path $valid.output 'batches.js') -Raw -Encoding UTF8
    $jsonText=$batchScript -replace '^window\.REVIEW_BATCHES\s*=\s*','' -replace ';\s*$',''
    $batch=@(ConvertFrom-Json -InputObject $jsonText -AsHashtable)[0]
    $v=@($batch.items|Where-Object{$_.label -eq 'H01-1_V'})[0]
    $s=@($batch.items|Where-Object{$_.label -eq 'H01-1_S'})[0]
    Assert ($v.request_origin -eq 'prepared' -and $v.request_run_status -eq 'prepared_not_sent') 'V request should be prepared and explicitly not sent'
    Assert ($v.protocol -eq 'hard-selective-V/v1' -and $v.frames.Count -eq 1) 'V protocol and ordered public image should be retained'
    Assert ($v.model_input.initial_state_declarations.Count -eq 1) 'initial_state_declarations must survive the web export'
    Assert ($v.model_input.history[0].stage -eq 'public-history' -and $v.model_input.rules[0] -eq 'Public rule remains visible.') 'history and rules must survive the web export'
    Assert ($v.model_input.event.action -eq 'PutObject' -and $v.model_input.event.settle_steps -eq 4) 'event fields must survive the web export'
    Assert ($v.model_input.unknown_future_field.nested.Count -eq 2) 'unknown future model_input fields must survive the web export'
    Assert ($v.request_text.Contains('unknown_future_field') -and $v.request_text.Contains('initial_state_declarations')) 'frozen request text must include the entire model_input payload'
    Assert (-not $v.request_text.Contains('PRIVATE_ACTION_TEXT') -and -not $v.request_text.Contains('PRIVATE_BOUNDARY_LABEL')) 'private audit labels must not leak into frozen model-visible request text'
    Assert ($v.frames[0].stage -eq 'public-initial' -and -not $v.frames[0].stage.Contains('private')) 'public model frame list must not be replaced with private audit frames'
    Assert ($s.protocol -eq 'hard-selective-S/v1' -and $s.frames.Count -eq 0) 'frozen S protocol should accept zero public frames'
    Assert ($s.media_quality.issue_items -eq 0) 'intentional no-image S input must not be called source_incomplete'
    Assert ($s.audit_timeline.frames[0].stage -eq 'private-only-stage' -and $s.audit_timeline.steps[0] -eq 'PRIVATE_ACTION_TEXT') 'private timeline and raw steps should be available in the collapsed audit payload'
    Assert ($s.audit_timeline.title -eq '受控嵌套移出场景' -and $s.audit_timeline.capture_groups[0].views.Count -eq 2) 'scene title and synchronized views must survive private timeline export as one group'
    Assert ($s.audit_timeline.capture_groups[0].global_step -eq 3 -and $s.audit_timeline.capture_groups[0].views[1].view_role -eq 'third_party') 'same-timestep group and view role metadata must be preserved'
    Assert ($s.model_input.history[0].stage -eq 'public-history') 'private timeline must not replace or remove the complete public model_input'
    $manifest=Get-Content -LiteralPath (Join-Path $valid.output 'site_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    Assert ($manifest.source_media_status -eq 'media_present_not_visually_approved') 'intentional S no-image status must not mark the batch incomplete'
    $html=Get-Content -LiteralPath (Join-Path $valid.output 'index.html') -Raw -Encoding UTF8
    $js=Get-Content -LiteralPath (Join-Path $valid.output 'review.js') -Raw -Encoding UTF8
    Assert (-not $html.Contains('PRIVATE_ACTION_TEXT') -and -not $html.Contains('PRIVATE_BOUNDARY_LABEL')) 'private audit labels must not be embedded in the default HTML'
    Assert ($js.Contains("el('details')") -and $js.Contains('私有同步时间线与全程采集（不属于模型输入）')) 'private timeline must be rendered separately from the model-visible input'
    Assert ($js.Contains('S 是有意设置的纯文本状态诊断') -and $js.Contains('capture-views') -and $js.Contains('V 视觉证据 · 主审候选')) 'reviewer must explain S text-only intent, V priority, and synchronized grouped views'

    $allFailed=New-FailureOnlyFixture 'all-failed-generation'
    Invoke-Review $allFailed
    $failedBatchText=Get-Content -LiteralPath (Join-Path $allFailed.output 'batches.js') -Raw -Encoding UTF8
    $failedBatchJson=$failedBatchText -replace '^window\.REVIEW_BATCHES\s*=\s*','' -replace ';\s*$',''
    $failedBatch=@(ConvertFrom-Json -InputObject $failedBatchJson -AsHashtable)[0]
    $failureItem=@($failedBatch.items|Where-Object{$_.kind -eq 'diagnostic'})[0]
    $failedManifest=Get-Content -LiteralPath (Join-Path $allFailed.output 'site_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    Assert ($failedBatch.items.Count -eq 1 -and $failedManifest.batches[0].records -eq 0 -and $failedManifest.batches[0].diagnostic_attempts -eq 1) 'all-failed batch should render a diagnostic while keeping formal record count at zero'
    Assert ($failedManifest.source_media_status -eq 'source_incomplete' -and $failureItem.timeline_status -eq 'available') 'unpublished cases must mark the batch incomplete while retaining available native frames'
    Assert ($failureItem.error -eq 'native construction failed' -and $failureItem.frames[0].src) 'diagnostic page should show the failure and its available sidecar frame'
    Assert ($failureItem.frames.Count -eq 1 -and $failureItem.frames[0].view_id -eq 'agent') 'failed-attempt image strip must contain only the agent view, while synchronized debug views stay grouped below'
    Assert ($failureItem.audit_timeline.capture_groups.Count -eq 1 -and $failureItem.audit_timeline.capture_groups[0].views.Count -eq 2) 'failed attempts must preserve same-timestep synchronized groups and all private views'
    Assert (-not $failureItem.Contains('model_input') -and -not $failureItem.Contains('request_text') -and -not $failureItem.Contains('references')) 'failed attempts must not become formal model questions, requests, or Gold rows'

    $missingFilm=New-FailureOnlyFixture 'all-failed-missing-film'
    Remove-Item -LiteralPath (Join-Path $missingFilm.source 'audit_traces/H01-1/review_timeline.json')
    Invoke-Review $missingFilm
    $missingFilmBatch=Get-Content -LiteralPath (Join-Path $missingFilm.output 'batches.js') -Raw -Encoding UTF8
    $missingFilmJson=$missingFilmBatch -replace '^window\.REVIEW_BATCHES\s*=\s*','' -replace ';\s*$',''
    $missingFilmData=@(ConvertFrom-Json -InputObject $missingFilmJson -AsHashtable)[0]
    Assert ($missingFilmData.items[0].timeline_status -eq 'missing' -and $missingFilmData.items[0].frames.Count -eq 0) 'missing native film should remain explicit in the failure diagnostic'
    $missingFilmManifest=Get-Content -LiteralPath (Join-Path $missingFilm.output 'site_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    Assert ($missingFilmManifest.source_media_status -eq 'source_incomplete') 'missing native film must mark the batch source incomplete'

    $noRequest=New-Fixture 's-without-frozen-request'
    Remove-Item -LiteralPath (Join-Path $noRequest.source 'prepared_requests/H01-1_S.json')
    Invoke-ReviewExpectFailure $noRequest 'Only a hash-matched frozen S request may intentionally have no public frames'

    $recordTamper=New-Fixture 'tampered-input'
    Add-Content -LiteralPath (Join-Path $recordTamper.source 'data/input/H01-1_V.json') -Value ' ' -Encoding UTF8
    Invoke-ReviewExpectFailure $recordTamper 'Prepared request input/image hashes mismatch'

    $pixelTamper=New-Fixture 'tampered-pixel'
    $pixelPath=Join-Path $pixelTamper.source 'data/media/public.png'
    $changed=[IO.File]::ReadAllBytes($pixelPath);$changed[$changed.Length-8]=[byte]($changed[$changed.Length-8] -bxor 1);[IO.File]::WriteAllBytes($pixelPath,$changed)
    Invoke-ReviewExpectFailure $pixelTamper 'Prepared request input/image hashes mismatch'

    $protocolTamper=New-Fixture 'protocol-mismatch'
    $protocolPath=Join-Path $protocolTamper.source 'prepared_requests/H01-1_V.json'
    $protocolRequest=Get-Content -LiteralPath $protocolPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    $protocolRequest.protocol='hard-selective-S/v1'
    Write-Json $protocolPath $protocolRequest
    Invoke-ReviewExpectFailure $protocolTamper 'Prepared request protocol does not match model_input.protocol'

    $payloadTamper=New-Fixture 'duplicated-payload-mismatch'
    $payloadPath=Join-Path $payloadTamper.source 'prepared_requests/H01-1_V.json'
    $payloadRequest=Get-Content -LiteralPath $payloadPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    $payloadRequest.model_input.unknown_future_field.must_survive=$false
    Write-Json $payloadPath $payloadRequest
    Invoke-ReviewExpectFailure $payloadTamper 'Prepared request model_input does not match public record'

    $missingAuditImage=New-Fixture 'missing-private-image'
    Remove-Item -LiteralPath (Join-Path $missingAuditImage.source 'audit_traces/H01-1/private.png')
    Invoke-Review $missingAuditImage
    $missingBatch=Get-Content -LiteralPath (Join-Path $missingAuditImage.output 'batches.js') -Raw -Encoding UTF8
    $missingJson=$missingBatch -replace '^window\.REVIEW_BATCHES\s*=\s*','' -replace ';\s*$',''
    $missingData=@(ConvertFrom-Json -InputObject $missingJson -AsHashtable)[0]
    $missingS=@($missingData.items|Where-Object{$_.label -eq 'H01-1_S'})[0]
    Assert ($null -eq $missingS.audit_timeline.frames[0].src) 'a confined but missing private frame should remain a missing-audit-image diagnostic'

    $escaped=New-Fixture 'escaped-private-frame'
    $timelinePath=Join-Path $escaped.source 'audit_traces/H01-1/review_timeline.json'
    $timeline=Get-Content -LiteralPath $timelinePath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    $timeline.frames[0].path='../outside.png'
    Write-Json $timelinePath $timeline
    Invoke-ReviewExpectFailure $escaped 'Audit frame path is missing or escapes the case sidecar directory'

    $script:failed=$false
    Write-Output 'PASS: hard web review contract fixtures passed.'
} finally {
    if($script:failed){Write-Warning "Fixture output kept for inspection: $script:tempRoot"}
    elseif(Test-Path -LiteralPath $script:tempRoot){
        $resolved=[IO.Path]::GetFullPath($script:tempRoot)
        $tempParent=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\','/')
        if([IO.Path]::GetDirectoryName($resolved).TrimEnd('\','/') -ne $tempParent -or
           -not [IO.Path]::GetFileName($resolved).StartsWith('hard-web-review-')){throw 'Refusing cleanup outside the exact fixture temp directory'}
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
