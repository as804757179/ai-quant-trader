#Requires -Version 5.1
<#
.SYNOPSIS
  在本机启动 a-stock-data(8080) + Backend(8000)，使用 .env.host
.DESCRIPTION
  不依赖 Docker 应用容器；要求本机 PostgreSQL:5432 与 Redis:6379 已就绪。
.EXAMPLE
  .\scripts\start-host-api.ps1
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path (Join-Path $Root ".env.host"))) {
    throw "缺少 .env.host，请先配置本机数据库连接"
}

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""
$env:ALL_PROXY = ""
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
$env:TZ = "Asia/Shanghai"
$env:PYTHONUTF8 = "1"

Get-Content (Join-Path $Root ".env.host") -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $i = $line.IndexOf("=")
    if ($i -lt 1) { return }
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim()
    # compose 专用键忽略
    if ($k -in @("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "REDIS_HOST", "REDIS_PORT")) {
        return
    }
    Set-Item -Path "Env:$k" -Value $v
}

function Stop-Port([int]$Port) {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

Write-Host "==> 释放 8000 / 8080 ..." -ForegroundColor Cyan
Stop-Port 8000
Stop-Port 8080
Start-Sleep -Seconds 1

$adataPy = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"
$backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $adataPy)) { throw "未找到 a-stock-data venv: $adataPy" }
if (-not (Test-Path $backendPy)) { throw "未找到 backend venv: $backendPy" }

Write-Host "==> 启动 a-stock-data :8080" -ForegroundColor Cyan
Start-Process -FilePath $adataPy `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8080" `
    -WorkingDirectory (Join-Path $Root "a-stock-data\service") `
    -WindowStyle Minimized

# Backend 必须继承当前进程环境（.env.host）
Write-Host "==> 启动 Backend :8000" -ForegroundColor Cyan
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $backendPy
$psi.Arguments = "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
$psi.WorkingDirectory = Join-Path $Root "backend"
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $false
foreach ($de in [System.Environment]::GetEnvironmentVariables("Process").GetEnumerator()) {
    try { $psi.EnvironmentVariables[$de.Key] = [string]$de.Value } catch {}
}
[void][System.Diagnostics.Process]::Start($psi)

Write-Host "==> 等待健康检查..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 2
        if ($h.status -eq "ok") { $ok = $true; break }
    } catch {}
}
if (-not $ok) {
    Write-Host "Backend 未在 30s 内就绪，请检查数据库/Redis 与终端窗口输出" -ForegroundColor Yellow
    exit 1
}

$list = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/stock/list?page_size=1" -TimeoutSec 15
Write-Host ("OK  Backend 健康 | 股票池 active={0} | 时间 {1}" -f $list.data.total, $list.timestamp) -ForegroundColor Green
Write-Host "前端: http://localhost:3000  （若未启动请 npm run dev）" -ForegroundColor Green
