#Requires -Version 5.1
[CmdletBinding()]
param([string]$EnvFile = ".env.host", [switch]$SkipInstall)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
function Fail([string]$Message) { Write-Host "STARTUP FAILED: $Message" -ForegroundColor Red; exit 1 }
function Import-EnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { Fail "Missing environment file: $Path" }
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim(); $index = $line.IndexOf("=")
        if ($line -and -not $line.StartsWith("#") -and $index -gt 0) { Set-Item -Path "Env:$($line.Substring(0, $index).Trim())" -Value $line.Substring($index + 1).Trim() }
    }
}
function Test-Port([int]$Port) { return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) }
function Wait-Http([string]$Name, [string]$Uri, [int]$Seconds = 30) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) { try { Invoke-WebRequest $Uri -UseBasicParsing -TimeoutSec 2 | Out-Null; return } catch { Start-Sleep -Milliseconds 500 } }
    Fail "$Name was not ready within ${Seconds}s: $Uri"
}
function Start-ManagedProcess([string]$Name, [string]$FileName, [string[]]$Arguments, [string]$WorkingDirectory) {
    $stdout = Join-Path $LogDir "$Name.out.log"; $stderr = Join-Path $LogDir "$Name.err.log"
    Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $FileName -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    if ($process.HasExited) { Fail "$Name exited: $((Get-Content $stderr -Raw -ErrorAction SilentlyContinue).Trim())" }
    return $process
}
function Stop-RegisteredProcess([object]$Registry, [string]$Name) {
    if ($Registry -and $Registry.$Name -and $Registry.$Name.pid) {
        $processId = [int]$Registry.$Name.pid
        if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
            & taskkill.exe /PID $processId /T /F | Out-Null
        }
    }
}
function Test-ExistingCeleryProcess {
    $existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match "-m celery -A celery_app (worker|beat)" }
    if ($existing) { Fail "Existing Celery worker/beat process detected; stop it before startup" }
}

Set-Location $Root
Import-EnvFile (Join-Path $Root $EnvFile)
$env:PYTHONUTF8 = "1"; $env:PYTHONDONTWRITEBYTECODE = "1"; $env:PYTHONPATH = "$Root\worker;$Root\backend"
foreach ($required in @("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "A_STOCK_DATA_URL", "SECRET_KEY")) {
    if (-not (Get-Item "Env:$required" -ErrorAction SilentlyContinue).Value) { Fail "Missing environment variable: $required" }
}
if ($env:TRADE_MODE -eq "live" -and $env:QMT_FORCE_MOCK -match "^(1|true|yes)$") { Fail "live mode forbids QMT_FORCE_MOCK=true" }
$registryPath = Join-Path $LogDir "local-services.json"
$previousRegistry = if (Test-Path $registryPath) { Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
Stop-RegisteredProcess $previousRegistry "worker"
Stop-RegisteredProcess $previousRegistry "beat"
Start-Sleep -Seconds 1
Test-ExistingCeleryProcess
if (-not (Test-Port 5432) -or -not (Test-Port 6379)) {
    if (Get-Command docker -ErrorAction SilentlyContinue) { docker compose up -d postgres redis; if ($LASTEXITCODE -ne 0) { Fail "Cannot start PostgreSQL/Redis" }; Start-Sleep -Seconds 3 }
}
if (-not (Test-Port 5432)) { Fail "PostgreSQL is not listening on 127.0.0.1:5432" }
if (-not (Test-Port 6379)) { Fail "Redis is not listening on 127.0.0.1:6379" }

$backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"; $dataPy = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPy)) { Fail "Missing Backend Python environment: $backendPy" }
if (-not (Test-Path $dataPy)) { Fail "Missing Data Service Python environment: $dataPy" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "npm was not found" }
Push-Location (Join-Path $Root "backend")
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$migrationOutput = & $backendPy -m alembic upgrade head 2>&1
$migrationExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($migrationExitCode -ne 0) {
    Pop-Location
    if (($migrationOutput -join "`n") -match "InsufficientPrivilege|must be owner") {
        Fail "Database migration lacks table-owner permission. Run .\scripts\repair-db-owner.ps1 -AdminDatabaseUrl <administrator database URL>"
    }
    Fail "Database migration failed. Inspect logs or run .\scripts\repair-db-owner.ps1 -CheckOnly"
}
Pop-Location
if (-not $SkipInstall) { Push-Location (Join-Path $Root "frontend"); npm ci; if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Frontend dependency installation failed" }; Pop-Location }

if (-not (Test-Port 8080)) { [void](Start-ManagedProcess "data-service" $dataPy @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8080") (Join-Path $Root "a-stock-data\service")) }
Wait-Http "Data Service" "http://127.0.0.1:8080/health"
if (-not (Test-Port 8000)) { [void](Start-ManagedProcess "backend" $backendPy @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") (Join-Path $Root "backend")) }
Wait-Http "Backend" "http://127.0.0.1:8000/api/v1/health"
$worker = Start-ManagedProcess "worker" $backendPy @("-m", "celery", "-A", "celery_app", "worker", "-Q", "high,normal,low", "--hostname=worker-sprint01@%h", "--pool=solo", "--concurrency=1", "--loglevel=info") (Join-Path $Root "worker")
$beat = Start-ManagedProcess "beat" $backendPy @("-m", "celery", "-A", "celery_app", "beat", "--loglevel=info", "--scheduler", "redbeat.RedBeatScheduler") (Join-Path $Root "worker")
if (-not (Test-Port 3000)) { [void](Start-ManagedProcess "frontend" "cmd.exe" @("/c", "npm", "run", "dev") (Join-Path $Root "frontend")) }
Wait-Http "Frontend" "http://127.0.0.1:3000"
@{ worker = @{ pid = $worker.Id }; beat = @{ pid = $beat.Id }; started_at = (Get-Date).ToString("o") } | ConvertTo-Json | Set-Content (Join-Path $LogDir "local-services.json") -Encoding UTF8
& (Join-Path $Root "scripts\verify_local_env.ps1") -EnvFile $EnvFile
if ($LASTEXITCODE -ne 0) { Fail "Environment verification failed; inspect logs" }
Write-Host "STARTUP PASS: Frontend=http://127.0.0.1:3000 API=http://127.0.0.1:8000" -ForegroundColor Green
