#Requires -Version 5.1
[CmdletBinding()]
param([string]$EnvFile = ".env.host", [int]$TimeoutSeconds = 5)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure([string]$Message) { $script:failures.Add($Message) }
function Test-TcpPort([string]$Name, [string]$HostName, [int]$Port) {
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        if (-not $client.ConnectAsync($HostName, $Port).Wait($TimeoutSeconds * 1000)) {
            Add-Failure "$Name 连接超时：${HostName}:$Port"
        }
        $client.Close()
    } catch { Add-Failure "$Name 连接失败：${HostName}:${Port}：$($_.Exception.Message)" }
}
function Get-EnvMap([string]$Path) {
    $map = @{}
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $index = $line.IndexOf("=")
            if ($index -gt 0) { $map[$line.Substring(0, $index).Trim()] = $line.Substring($index + 1).Trim() }
        }
    }
    return $map
}

$envPath = Join-Path $Root $EnvFile
if (-not (Test-Path $envPath)) {
    Add-Failure "缺少环境文件：$envPath"
} else {
    $config = Get-EnvMap $envPath
    foreach ($entry in $config.GetEnumerator()) { Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value }
    foreach ($key in @("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "A_STOCK_DATA_URL", "A_STOCK_DATA_COMMAND_TOKEN", "WORKER_API_CREDENTIAL", "SECRET_KEY")) {
        if (-not $config[$key]) { Add-Failure "缺少环境变量：$key" }
    }
    if ($config["A_STOCK_DATA_COMMAND_TOKEN"].Length -lt 32 -or $config["A_STOCK_DATA_COMMAND_TOKEN"] -match "(?i)replace-with-|change_me") {
        Add-Failure "A_STOCK_DATA_COMMAND_TOKEN 必须是至少 32 字节的非默认随机值"
    }
    if ($config["WORKER_API_CREDENTIAL"].Length -lt 32 -or $config["WORKER_API_CREDENTIAL"] -match "(?i)replace-with-|change_me|changeme|123456|test") {
        Add-Failure "WORKER_API_CREDENTIAL 必须是至少 32 字节的非默认随机凭据"
    }
    if ($config["TRADE_MODE"] -eq "live" -and $config["QMT_FORCE_MOCK"] -match "^(1|true|yes)$") {
        Add-Failure "不安全配置：live 模式禁止 QMT_FORCE_MOCK=true"
    }
    if ($config["BACKTEST_ALLOW_SYNTHETIC_KLINE"] -match "^(1|true|yes)$" -and $config["SYNTHETIC_KLINE_SMOKE_TEST"] -notmatch "^(1|true|yes)$") {
        Add-Failure "不安全配置：合成 K 线要求 SYNTHETIC_KLINE_SMOKE_TEST=true"
    }
}

$ownerRepairScript = Join-Path $Root "scripts\repair-db-owner.ps1"
if (-not (Test-Path $ownerRepairScript)) {
    Add-Failure "缺少数据库所有者修复脚本"
} else {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $ownerCheck = & $ownerRepairScript -EnvFile $EnvFile -CheckOnly 2>&1
    $ownerCheckExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($ownerCheckExitCode -ne 0 -or ($ownerCheck -join "`n") -notmatch "status=PASS") {
        Add-Failure "数据库对象所有者不正确：$($ownerCheck -join ' ')"
    }
}

Test-TcpPort "PostgreSQL" "127.0.0.1" 5432
Test-TcpPort "Redis" "127.0.0.1" 6379
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8080/health" -TimeoutSec $TimeoutSeconds
    if ($health.status -ne "ok") { Add-Failure "数据服务健康状态异常" }
} catch { Add-Failure "数据服务健康检查失败：$($_.Exception.Message)" }
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/health" -TimeoutSec $TimeoutSeconds
    if ($health.status -ne "ok") { Add-Failure "后端存活状态异常" }
} catch { Add-Failure "后端健康检查失败：$($_.Exception.Message)" }
$backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPy)) {
    Add-Failure "缺少后端 Python 环境"
} else {
    Push-Location (Join-Path $Root "backend")
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $currentRevision = & $backendPy -m alembic current 2>&1
    $currentExitCode = $LASTEXITCODE
    $headRevision = & $backendPy -m alembic heads 2>&1
    $headExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    Pop-Location
    $headId = (($headRevision -join "`n") | Select-String -Pattern "(?m)^([0-9A-Za-z_]+) \(head\)$").Matches.Groups[1].Value
    if ($currentExitCode -ne 0 -or $headExitCode -ne 0 -or -not $headId -or ($currentRevision -join "`n") -notmatch "(?m)^$([regex]::Escape($headId)) \(head\)$") {
        Add-Failure "数据库迁移未处于 Alembic head"
    }
}
try { Invoke-WebRequest "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec $TimeoutSeconds | Out-Null } catch { Add-Failure "前端健康检查失败：$($_.Exception.Message)" }

$runtimeRoot = Join-Path $env:LOCALAPPDATA "AIQuantTrader"
$registryPath = Join-Path $runtimeRoot "run\local-services.json"
if (-not (Test-Path $registryPath)) {
    Add-Failure "缺少启动登记文件：$registryPath"
} else {
    $registry = Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($service in @("data-service", "backend", "worker", "beat", "frontend", "watchdog")) {
        $property = $registry.services.PSObject.Properties[$service]
        if (-not $property) {
            Add-Failure "服务未登记：$service"
        } elseif (-not (Get-Process -Id ([int]$property.Value.pid) -ErrorAction SilentlyContinue)) {
            Add-Failure "服务进程未运行：$service"
        }
    }
    $watchdogStatusPath = Join-Path $runtimeRoot "run\watchdog-status.json"
    if (-not (Test-Path $watchdogStatusPath)) {
        Add-Failure "缺少 Watchdog 状态文件"
    } else {
        try {
            $watchdogStatus = Get-Content $watchdogStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if (-not $watchdogStatus.ok) { Add-Failure "Watchdog 检查未通过：$($watchdogStatus.issues -join '；')" }
            if (((Get-Date) - [DateTimeOffset]::Parse([string]$watchdogStatus.checked_at).LocalDateTime).TotalSeconds -gt 90) {
                Add-Failure "Watchdog 状态已超过 90 秒未更新"
            }
        } catch {
            Add-Failure "Watchdog 状态文件损坏"
        }
    }
}

if ($failures.Count -eq 0) { Write-Host "验收通过" -ForegroundColor Green; exit 0 }
Write-Host "验收失败" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
