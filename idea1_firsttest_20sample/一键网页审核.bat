@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "WEB_REVIEW_LAUNCHER=%~f0"
where pwsh.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PowerShell 7 ^(pwsh.exe^) is required by the original scripts.
    echo Download: https://github.com/PowerShell/PowerShell/releases
    echo Then double-click this BAT again.
    echo.
    pause
    exit /b 1
)
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$content=[IO.File]::ReadAllText($env:WEB_REVIEW_LAUNCHER,[Text.Encoding]::UTF8); $scriptText=($content -split '(?m)^:: POWERSHELL_START\r?\n',2)[1]; & ([scriptblock]::Create($scriptText))"
set "RESULT=%errorlevel%"
echo.
if not "%RESULT%"=="0" echo [ERROR] Exit code: %RESULT%
pause
exit /b %RESULT%
:: POWERSHELL_START
$ErrorActionPreference = 'Stop'

function Read-Default([string] $Prompt, [string] $Default) {
    $answer = Read-Host "$Prompt [默认: $Default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Get-UniqueDirectory([string] $BasePath) {
    if (-not (Test-Path -LiteralPath $BasePath)) { return $BasePath }
    for ($i = 2; $i -le 9999; $i++) {
        $candidate = '{0}_{1:D2}' -f $BasePath, $i
        if (-not (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw "无法找到空闲目录：$BasePath"
}

function Find-SourceRoot([string] $Directory) {
    $folders = @($Directory) + @(
        Get-ChildItem -LiteralPath $Directory -Directory -Recurse -ErrorAction Stop |
        ForEach-Object { $_.FullName }
    )
    $matches = @(
        $folders | Where-Object {
            (Test-Path -LiteralPath (Join-Path $_ 'data/input') -PathType Container) -or
            (Test-Path -LiteralPath (Join-Path $_ 'observations/attempts') -PathType Container)
        } | Sort-Object -Property Length, { $_ }
    )
    if ($matches.Count -eq 0) {
        throw '未找到 data/input 或 observations/attempts；压缩包可能不是该网页审核脚本的输入数据。'
    }
    if ($matches.Count -gt 1) {
        Write-Host "检测到 $($matches.Count) 个候选数据根目录，请明确选择一个，避免混用不同批次：" -ForegroundColor Yellow
        for($i=0;$i -lt $matches.Count;$i++){Write-Host "  $($i+1)) $($matches[$i])"}
        $choice=0;$answer=Read-Host '输入数据根目录编号'
        if(-not [int]::TryParse($answer,[ref]$choice) -or $choice -lt 1 -or $choice -gt $matches.Count){throw '未选择有效数据根目录。请重新输入更具体的批次文件夹。'}
        return $matches[$choice-1]
    }
    return $matches[0]
}

try {
    $project = [IO.Path]::GetDirectoryName($env:WEB_REVIEW_LAUNCHER)
    $buildScript = Join-Path $project 'New-WebReview.ps1'
    $sceneScript = Join-Path $project 'Update-WebReviewScenes.ps1'
    $webDir = Join-Path $project 'review_web'
    foreach ($required in @($buildScript, $sceneScript,
        (Join-Path $webDir 'index.html'),
        (Join-Path $webDir 'review.css'),
        (Join-Path $webDir 'review.js'),
        (Join-Path $webDir 'mechanism_review.ps1'),
        (Join-Path $webDir 'capture_integrity.ps1'),
        (Join-Path $webDir 'mechanism_f1_f4.ps1'),
        (Join-Path $webDir 'mechanism_f5_f8.ps1'),
        (Join-Path $webDir 'mechanism_f9_f11.ps1'))) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "缺少必需文件：$required`n请将这个 BAT 放在 New-WebReview.ps1 同一目录，并保留 review_web 文件夹。"
        }
    }

    Write-Host ''
    Write-Host '========== 网页审核 · 一键生成 ==========' -ForegroundColor Cyan
    Write-Host '支持带双引号的 ZIP 路径，或已经解压的数据文件夹。'
    Write-Host '除第 1 项外，后续一路按 Enter 即采用默认值。'
    Write-Host ''

    $raw = Read-Host '1) 粘贴 Source 压缩包/文件夹的完整路径'
    $sourceInput = $raw.Trim().Trim([char[]]@('"', '“', '”', "'"))
    if (-not $sourceInput) { throw 'Source 路径不能为空。' }
    $sourceInput = [IO.Path]::GetFullPath($sourceInput)
    if (-not (Test-Path -LiteralPath $sourceInput)) { throw "路径不存在：$sourceInput" }
    $file = Get-Item -LiteralPath $sourceInput
    $stem = if ($file.PSIsContainer) { $file.Name } else { [IO.Path]::GetFileNameWithoutExtension($file.Name) }
    $stem = $stem.Trim()
    if ($stem.Length -gt 55) { $stem = $stem.Substring(0, 55) }
    $parent = if ($file.PSIsContainer) { $file.Parent.FullName } else { $file.DirectoryName }
    $defaultLabel = "网页审核 - $stem"
    $defaultOutput = Get-UniqueDirectory (Join-Path $parent "网页审核_$stem")

    $batchLabel = Read-Default '2) 审核批次显示名称' $defaultLabel
    $outText = Read-Default '3) 输出网页文件夹' $defaultOutput
    $output = [IO.Path]::GetFullPath($outText.Trim([char[]]@('"', '“', '”')))
    if (Test-Path -LiteralPath $output) {
        throw "输出目录已存在，原脚本禁止覆盖：$output。重新运行后按 Enter 可自动避开重名。"
    }
    $refChoice = Read-Default '4) 显示参考答案？输入 Y 开启；默认 N' 'N'
    $includeReferences = $refChoice -match '^(?i:y|yes|是)$'
    $openChoice = Read-Default '5) 完成后自动打开网页？输入 N 关闭；默认 Y' 'Y'
    $openBrowser = $openChoice -notmatch '^(?i:n|no|否)$'

    if ($file.PSIsContainer) {
        $scanDirectory = $sourceInput
    } else {
        $ext = $file.Extension.ToLowerInvariant()
        if ($ext -notin @('.zip', '.7z', '.rar')) {
            throw "暂不支持 $ext 压缩包。请改用 ZIP/7Z/RAR，或输入解压后的文件夹路径。"
        }
        $scanDirectory = Get-UniqueDirectory (Join-Path $parent "网页审核_解压_$stem")
        Write-Host "`n[1/3] 正在解压到：$scanDirectory" -ForegroundColor Cyan
        if ($ext -eq '.zip') {
            Expand-Archive -LiteralPath $sourceInput -DestinationPath $scanDirectory -ErrorAction Stop
        } else {
            $seven = Get-Command 7z.exe, 7zz.exe -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $seven) {
                $installed7z = Join-Path $env:ProgramFiles '7-Zip/7z.exe'
                if (Test-Path -LiteralPath $installed7z) { $seven = $installed7z }
            }
            if (-not $seven) { throw '解压 7Z/RAR 需要安装 7-Zip（7z.exe）；也可以先手动解压后输入文件夹路径。' }
            [IO.Directory]::CreateDirectory($scanDirectory) | Out-Null
            $sevenExe = if ($seven -is [string]) { $seven } else { $seven.Source }
            & $sevenExe x "-o$scanDirectory" '-y' $sourceInput | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "7-Zip 解压失败，退出代码：$LASTEXITCODE" }
        }
    }

    Write-Host '[2/3] 正在寻找数据根目录 ...' -ForegroundColor Cyan
    $sourceRoot = Find-SourceRoot $scanDirectory
    Write-Host "      SourceRoot = $sourceRoot"
    Write-Host "      OutputRoot = $output"
    Write-Host "      BatchName  = $batchLabel"
    Write-Host '      正在生成静态审核网页 ...'

    $buildParams = @{
        SourceRoot = @($sourceRoot)
        OutputRoot = $output
        BatchName = @($batchLabel)
    }
    if ($includeReferences) { $buildParams['IncludeReferenceAnswers'] = $true }
    & $buildScript @buildParams | Out-Null
    $indexFile = Join-Path $output 'index.html'
    $manifestFile = Join-Path $output 'site_manifest.json'
    if (-not (Test-Path -LiteralPath $indexFile -PathType Leaf)) { throw '网页生成脚本结束，但没有找到 index.html。' }
    if (-not (Test-Path -LiteralPath $manifestFile -PathType Leaf)) { throw '网页生成脚本结束，但没有找到 site_manifest.json。' }

    $manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $modes = @($manifest.batches | ForEach-Object { $_.mode })
    if ('Mechanism' -in $modes -and -not ($manifest.PSObject.Properties.Name -contains 'scene_presentation_version')) {
        Write-Host '[3/3] 正在执行机制场景增强 ...' -ForegroundColor Cyan
        try {
            & $sceneScript -WebRoot $output | Out-Null
            Write-Host '      场景增强已完成。' -ForegroundColor Green
        } catch {
            Write-Warning "场景增强失败，但第一步生成的网页仍保留。详细原因：$($_.Exception.Message)"
        }
    } else {
        Write-Host '[3/3] 场景说明已由导出器生成，正在检查源图片完整性。' -ForegroundColor Cyan
    }

    $incomplete=$manifest.PSObject.Properties.Name -contains 'source_media_status' -and $manifest.source_media_status -eq 'source_incomplete'
    if(-not $incomplete){$incomplete=@($manifest.batches|Where-Object{$_.missing_images -gt 0}).Count -gt 0}
    $invalidNative=0;foreach($batch in $manifest.batches){if($batch.PSObject.Properties.Name -contains 'invalid_native_measurements'){$invalidNative+=[int]$batch.invalid_native_measurements}}
    if($invalidNative){$incomplete=$true}
    Write-Host ''
    if($incomplete){
        Write-Host '========== 源图片或原生测量不合格：仅生成诊断网页 ==========' -ForegroundColor Red
        Write-Host '这批不是完整可用的视觉数据。重新运行导出器无法补出服务器未生成的图片。' -ForegroundColor Red
        if($invalidNative){Write-Host "原始运行记录判为无效的原生测量：$invalidNative 条。" -ForegroundColor Red}
        foreach($batch in $manifest.batches){
            if($batch.PSObject.Properties.Name -contains 'media_quality'){
                $q=$batch.media_quality
                Write-Host "可查看图片引用 $($q.available_image_refs)；生产失败 $($q.generation_failed_items)；未记路径 $($q.path_not_recorded_items)；有路径但缺文件 $($q.missing_files)；路径不兼容 $($q.invalid_paths)。" -ForegroundColor Yellow
            }
        }
    }else{Write-Host '========== 网页已生成，源图片文件齐全 ==========' -ForegroundColor Green;Write-Host '文件齐全不代表视角、题意或视觉证据已人工审核通过。'}
    Write-Host "网页入口：$indexFile"
    Write-Host "输出目录：$output"
    Write-Host "来源目录：$sourceRoot"
    Write-Host '注意：保留来源目录，后续增量场景更新仍可能需要它。'
    if ($openBrowser) {
        try { Start-Process -FilePath $indexFile }
        catch { Write-Warning "自动打开失败，请自行双击 index.html：$($_.Exception.Message)" }
    }
    if($incomplete){exit 2}else{exit 0}
} catch {
    Write-Host ''
    Write-Host '========== 执行失败 ==========' -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "发生位置：$($_.InvocationInfo.PositionMessage)" -ForegroundColor DarkGray
    exit 1
}
