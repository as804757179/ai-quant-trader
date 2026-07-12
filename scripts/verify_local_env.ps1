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
            Add-Failure "$Name connection timed out at ${HostName}:$Port"
        }
        $client.Close()
    } catch { Add-Failure "$Name connection failed at ${HostName}:${Port}: $($_.Exception.Message)" }
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
    Add-Failure "Missing environment file: $envPath"
} else {
    $config = Get-EnvMap $envPath
    foreach ($entry in $config.GetEnumerator()) { Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value }
    foreach ($key in @("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "A_STOCK_DATA_URL", "SECRET_KEY")) {
        if (-not $config[$key]) { Add-Failure "Missing environment variable: $key" }
    }
    if ($config["TRADE_MODE"] -eq "live" -and $config["QMT_FORCE_MOCK"] -match "^(1|true|yes)$") {
        Add-Failure "Unsafe configuration: live mode forbids QMT_FORCE_MOCK=true"
    }
    if ($config["BACKTEST_ALLOW_SYNTHETIC_KLINE"] -match "^(1|true|yes)$" -and $config["SYNTHETIC_KLINE_SMOKE_TEST"] -notmatch "^(1|true|yes)$") {
        Add-Failure "Unsafe configuration: Synthetic Kline requires SYNTHETIC_KLINE_SMOKE_TEST=true"
    }
}

$ownerRepairScript = Join-Path $Root "scripts\repair-db-owner.ps1"
if (-not (Test-Path $ownerRepairScript)) {
    Add-Failure "Missing database owner repair script"
} else {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $ownerCheck = & $ownerRepairScript -EnvFile $EnvFile -CheckOnly 2>&1
    $ownerCheckExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($ownerCheckExitCode -ne 0 -or ($ownerCheck -join "`n") -notmatch "status=PASS") {
        Add-Failure "Database owner is incorrect: $($ownerCheck -join ' ')"
    }
}

Test-TcpPort "PostgreSQL" "127.0.0.1" 5432
Test-TcpPort "Redis" "127.0.0.1" 6379
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8080/health" -TimeoutSec $TimeoutSeconds
    if ($health.status -ne "ok") { Add-Failure "Data Service health status is unhealthy" }
} catch { Add-Failure "Data Service health check failed: $($_.Exception.Message)" }
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/health" -TimeoutSec $TimeoutSeconds
    if ($health.status -ne "ok" -or $health.checks.database -ne "ok") { Add-Failure "Backend health status is unhealthy" }
} catch { Add-Failure "Backend health check failed: $($_.Exception.Message)" }
$backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPy)) {
    Add-Failure "Missing Backend Python environment"
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
        Add-Failure "Database migration is not at Alembic head"
    }
}
try { Invoke-WebRequest "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec $TimeoutSeconds | Out-Null } catch { Add-Failure "Frontend health check failed: $($_.Exception.Message)" }

$registryPath = Join-Path $Root "logs\local-services.json"
if (-not (Test-Path $registryPath)) {
    Add-Failure "Missing startup registry: $registryPath"
} else {
    $registry = Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($service in @("worker", "beat")) {
        if (-not (Get-Process -Id $registry.$service.pid -ErrorAction SilentlyContinue)) { Add-Failure "Celery $service process is not running" }
    }
    if (-not (Test-Path $backendPy)) {
        Add-Failure "Missing Backend Python environment"
    } else {
        Push-Location (Join-Path $Root "worker")
        $env:PYTHONPATH = "$Root\worker;$Root\backend"
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $ping = & $backendPy -m celery -A celery_app inspect ping --timeout=3 2>&1
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
        if ($LASTEXITCODE -ne 0 -or ($ping -join "`n") -notmatch "pong") { Add-Failure "Celery Worker did not respond to inspect ping" }
    }
}

if ($failures.Count -eq 0) { Write-Host "PASS" -ForegroundColor Green; exit 0 }
Write-Host "FAIL" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
