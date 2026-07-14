#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
$dataPy = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"

function Invoke-Checked([string]$Name, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    Write-Host "正在处理：$Name" -ForegroundColor Cyan
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$Name 失败，退出码：$LASTEXITCODE" }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $backendPy)) { throw "缺少后端虚拟环境：$backendPy" }
if (-not (Test-Path $dataPy)) { throw "缺少数据服务虚拟环境：$dataPy" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "找不到 npm" }

Invoke-Checked "后端依赖" $backendPy @("-m", "pip", "install", "-r", "requirements.txt") (Join-Path $Root "backend")
Invoke-Checked "数据服务依赖" $dataPy @("-m", "pip", "install", "-r", "requirements.txt") (Join-Path $Root "a-stock-data\service")
Invoke-Checked "前端依赖" "npm" @("ci") (Join-Path $Root "frontend")

Write-Host "依赖准备完成。" -ForegroundColor Green
