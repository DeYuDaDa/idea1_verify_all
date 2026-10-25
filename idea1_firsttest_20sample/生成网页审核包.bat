@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ======================================================
echo          网页审核数据包生成工具 (静态站点构建)
echo ======================================================
echo.

:: 1. 获取 Source 路径（支持复制带引号路径、拖入文件夹或.zip包）
set /p "RAW_SOURCE=请输入数据源路径 (文件夹或 .zip，支持直接拖入): "

:: 去除首尾可能带有的大引号
set "CLEAN_SOURCE=%RAW_SOURCE:"=%"

if "%CLEAN_SOURCE%"=="" (
    echo [错误] 路径不能为空！
    pause
    exit /b 1
)

if not exist "%CLEAN_SOURCE%" (
    echo [错误] 路径不存在: %CLEAN_SOURCE%
    pause
    exit /b 1
)

:: 检查是否是压缩包，若是则自动解压到同名文件夹
set "FINAL_SOURCE=%CLEAN_SOURCE%"
for %%I in ("%CLEAN_SOURCE%") do (
    set "EXT=%%~xI"
    set "PARENT_DIR=%%~dpI"
    set "FILE_NAME=%%~nI"
)

if /i "%EXT%"==".zip" (
    set "EXTRACT_DIR=%PARENT_DIR%%FILE_NAME%"
    echo.
    echo [*] 检测到输入为 ZIP 压缩包，正在自动解压到:
    echo     !EXTRACT_DIR!
    powershell -NoProfile -Command "Expand-Archive -LiteralPath '%CLEAN_SOURCE%' -DestinationPath '!EXTRACT_DIR!' -Force"
    if errorlevel 1 (
        echo [错误] 解压失败，请检查压缩包！
        pause
        exit /b 1
    )
    set "FINAL_SOURCE=!EXTRACT_DIR!"
)

:: 2. 默认输出路径：在输入源同级生成 "[名称]_网页审核"
for %%I in ("%FINAL_SOURCE%") do (
    set "SRC_NAME=%%~nxI"
    set "SRC_DIR=%%~dpI"
)
set "DEFAULT_OUT=!SRC_DIR!!SRC_NAME!_网页审核"

echo.
echo ------------------------------------------------------
set /p "USER_OUT=请输入输出目录 [直接按 Enter 默认: !DEFAULT_OUT!]: "
set "FINAL_OUT=%USER_OUT:"=%"
if "%FINAL_OUT%"=="" set "FINAL_OUT=!DEFAULT_OUT!"

:: 3. 默认批次名称
echo.
set "DEFAULT_BATCH=网页审核"
set /p "USER_BATCH=请输入批次名称 [直接按 Enter 默认: !DEFAULT_BATCH!]: "
set "FINAL_BATCH=%USER_BATCH:"=%"
if "%FINAL_BATCH%"=="" set "FINAL_BATCH=!DEFAULT_BATCH!"

:: 4. 检查入口 ps1 脚本是否存在
set "PS_ENTRY=%~dp0build_review_site.ps1"
if not exist "%PS_ENTRY%" (
    echo.
    echo [错误] 未在当前目录下找到入口脚本: build_review_site.ps1
    echo 请确认已将第七个脚本保存为 "%~dp0build_review_site.ps1"
    pause
    exit /b 1
)

echo.
echo ======================================================
echo 正在运行生成脚本...
echo Source: !FINAL_SOURCE!
echo Output: !FINAL_OUT!
echo Batch : !FINAL_BATCH!
echo ======================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%PS_ENTRY%' -SourceRoot @('!FINAL_SOURCE!') -OutputRoot '!FINAL_OUT!' -BatchName @('!FINAL_BATCH!') -IncludeReferenceAnswers"

if errorlevel 1 (
    echo.
    echo [错误] 生成失败，请查看上方 PowerShell 报错信息。
    pause
    exit /b 1
)

echo.
echo [成功] 网页审核包已生成完毕！
if exist "!FINAL_OUT!\index.html" (
    echo 正在为您打开网页...
    start "" "!FINAL_OUT!\index.html"
)

pause