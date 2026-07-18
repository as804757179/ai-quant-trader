#Requires -Version 5.1
[CmdletBinding()]
param([string]$EnvFile = ".env.host", [switch]$SkipInstall, [switch]$InstallDependencies, [string]$FrontendWorktree, [switch]$FrontendOnly)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $env:LOCALAPPDATA "AIQuantTrader"
$LogDir = Join-Path $RuntimeRoot "logs"
$RunDir = Join-Path $RuntimeRoot "run"
$registryPath = Join-Path $RunDir "local-services.json"
New-Item -ItemType Directory -Path $LogDir, $RunDir -Force | Out-Null
$Registry = [ordered]@{ root = $Root; started_at = (Get-Date).ToString("o"); infrastructure_started = $false; services = [ordered]@{} }
$script:StartupInProgress = $false
$script:LockHandle = $null

function Save-Registry { $Registry | ConvertTo-Json -Depth 6 | Set-Content $registryPath -Encoding UTF8 }
function Fail([string]$Message) { throw $Message }
trap {
    $message = $_.Exception.Message
    if ($script:StartupInProgress) {
        $script:StartupInProgress = $false
        & (Join-Path $Root "scripts\stop-local.ps1") -Quiet
    }
    if ($script:LockHandle) { $script:LockHandle.Dispose() }
    Write-Host "启动失败：$message" -ForegroundColor Red
    exit 1
}
function Import-EnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { Fail "缺少环境文件：$Path" }
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim(); $index = $line.IndexOf("=")
        if ($line -and -not $line.StartsWith("#") -and $index -gt 0) { Set-Item -Path "Env:$($line.Substring(0, $index).Trim())" -Value $line.Substring($index + 1).Trim() }
    }
}
function Test-Port([int]$Port) { return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) }
function Wait-Http([string]$Name, [string]$Uri, [int]$Seconds = 30) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) { try { Invoke-WebRequest $Uri -UseBasicParsing -TimeoutSec 2 | Out-Null; return } catch { Start-Sleep -Milliseconds 500 } }
    Fail "$Name 在 $Seconds 秒内未就绪：$Uri"
}
function Wait-Celery([int]$Seconds = 30) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $workerLog = Join-Path $LogDir "worker.err.log"
    $workerPid = [int]$Registry.services["worker"].pid
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $workerPid -ErrorAction SilentlyContinue)) { Fail "Celery Worker 在就绪前退出" }
        if ((Get-Content $workerLog -Raw -ErrorAction SilentlyContinue) -match "\bready\.") { return }
        Start-Sleep -Milliseconds 500
    }
    Fail "Celery Worker 在 $Seconds 秒内未就绪"
}
function Wait-Watchdog([int]$Seconds = 10) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $statusPath = Join-Path $RunDir "watchdog-status.json"
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $statusPath) {
            try {
                $status = Get-Content $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($status.ok -and [DateTimeOffset]::Parse([string]$status.checked_at) -gt [DateTimeOffset]::Parse([string]$Registry.started_at)) { return }
                if (-not $status.ok) { Fail "Watchdog 启动检查未通过：$($status.issues -join '；')" }
            } catch {
                if ($_.Exception.Message -like "Watchdog 启动检查未通过：*") { throw }
            }
        }
        Start-Sleep -Milliseconds 250
    }
    Fail "Watchdog 在 $Seconds 秒内未产生有效状态"
}
function Invoke-BoundedProcess([string]$Name, [string]$FileName, [string[]]$Arguments, [string]$WorkingDirectory, [int]$TimeoutSeconds) {
    $stdout = Join-Path $RunDir "$Name.out.log"; $stderr = Join-Path $RunDir "$Name.err.log"
    Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $FileName -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    [void]$process.Handle
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        Fail "$Name 超过 $TimeoutSeconds 秒"
    }
    $process.WaitForExit()
    $output = @((Get-Content $stdout -ErrorAction SilentlyContinue), (Get-Content $stderr -ErrorAction SilentlyContinue)) -join [Environment]::NewLine
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Output = $output }
}
function Start-ManagedProcess([string]$Name, [string]$FileName, [string[]]$Arguments, [string]$WorkingDirectory) {
    $stdout = Join-Path $LogDir "$Name.out.log"; $stderr = Join-Path $LogDir "$Name.err.log"
    $runner = Join-Path $Root "scripts\run_managed.py"
    $runnerArguments = @($runner, "--name", $Name, "--stdout-log", $stdout, "--stderr-log", $stderr, "--cwd", $WorkingDirectory, "--", $FileName) + $Arguments
    $process = Start-Process -FilePath $backendPy -ArgumentList $runnerArguments -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    if ($process.HasExited) { Fail "$Name 已退出：$((Get-Content $stderr -Raw -ErrorAction SilentlyContinue).Trim())" }
    $commandPattern = "run_managed\.py.*--name $([regex]::Escape($Name))"
    $Registry.services[$Name] = [ordered]@{ pid = $process.Id; started_at = $process.StartTime.ToString("o"); command_pattern = $commandPattern }
    Save-Registry
    return $process
}
function Test-ExistingCeleryProcess {
    $existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match "-m celery -A celery_app (worker|beat)" }
    if ($existing) { Fail "检测到未登记的 Celery worker/beat，请先确认并手动停止" }
}
function Resolve-FrontendWorktree([string]$Path) {
    $worktreeRoot = [IO.Path]::GetFullPath($Path)
    $worktreeOutput = @(& git -C $Root worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) { Fail "无法读取 Git 工作树列表" }
    $registeredRoots = @($worktreeOutput | Where-Object { $_.StartsWith("worktree ") } | ForEach-Object { [IO.Path]::GetFullPath($_.Substring(9)) })
    if ($registeredRoots -notcontains $worktreeRoot) { Fail "前端工作树未登记在当前 Git 仓库：$worktreeRoot" }
    $frontendDirectory = Join-Path $worktreeRoot "frontend"
    if (-not (Test-Path (Join-Path $frontendDirectory "package.json"))) { Fail "前端工作树缺少 frontend\package.json：$worktreeRoot" }
    if (-not (Test-Path (Join-Path $frontendDirectory "node_modules"))) { Fail "前端工作树缺少依赖；请在该工作树运行 scripts\bootstrap.ps1" }
    return $frontendDirectory
}

Set-Location $Root
$lockPath = Join-Path $RunDir "start-local.lock"
try {
    $script:LockHandle = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
} catch {
    Fail "另一个启动或停止操作正在运行"
}
& (Join-Path $Root "scripts\stop-local.ps1") -Quiet
if ($LASTEXITCODE -ne 0) { Fail "无法清理上一次已登记的服务" }
if ($FrontendWorktree -and -not $FrontendOnly) { Fail "指定 FrontendWorktree 时必须同时使用 -FrontendOnly" }
if ($FrontendOnly -and -not $FrontendWorktree) { Fail "-FrontendOnly 必须指定 -FrontendWorktree" }
if ($FrontendOnly) {
    $frontendDirectory = Resolve-FrontendWorktree $FrontendWorktree
    $backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $backendPy)) { Fail "缺少后端 Python 环境：$backendPy" }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "找不到 npm" }
    if (Test-Port 3000) { Fail "端口 3000 被未登记进程占用，已拒绝复用" }
    $Registry["frontend_worktree"] = Split-Path -Parent $frontendDirectory
    $script:StartupInProgress = $true
    Save-Registry
    [void](Start-ManagedProcess "frontend" "cmd.exe" @("/c", "npm", "run", "dev") $frontendDirectory)
    Wait-Http "前端工作树" "http://127.0.0.1:3000"
    [void](Start-ManagedProcess "watchdog" "powershell.exe" @("-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Root "scripts\watchdog.ps1"), "-RegistryPath", $registryPath, "-StatusPath", (Join-Path $RunDir "watchdog-status.json"), "-LogDir", $LogDir) $Root)
    Wait-Watchdog
    $script:StartupInProgress = $false
    $script:LockHandle.Dispose()
    Write-Host "前端工作树启动完成：http://127.0.0.1:3000 日志=$LogDir" -ForegroundColor Green
    exit 0
}
Import-EnvFile (Join-Path $Root $EnvFile)
$env:PYTHONUTF8 = "1"; $env:PYTHONDONTWRITEBYTECODE = "1"; $env:PYTHONPATH = "$Root\worker;$Root\backend"
foreach ($required in @("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "A_STOCK_DATA_URL", "A_STOCK_DATA_COMMAND_TOKEN", "WORKER_API_CREDENTIAL", "SECRET_KEY")) {
    if (-not (Get-Item "Env:$required" -ErrorAction SilentlyContinue).Value) { Fail "缺少环境变量：$required" }
}
if ($env:A_STOCK_DATA_COMMAND_TOKEN.Length -lt 32 -or $env:A_STOCK_DATA_COMMAND_TOKEN -match "(?i)replace-with-|change_me") { Fail "A_STOCK_DATA_COMMAND_TOKEN 必须是至少 32 字节的非默认随机值" }
if ($env:WORKER_API_CREDENTIAL.Length -lt 32 -or $env:WORKER_API_CREDENTIAL -match "(?i)replace-with-|change_me|changeme|123456|test") { Fail "WORKER_API_CREDENTIAL 必须是至少 32 字节的非默认随机凭据" }
if ($env:TRADE_MODE -eq "live" -and $env:QMT_FORCE_MOCK -match "^(1|true|yes)$") { Fail "live 模式禁止 QMT_FORCE_MOCK=true" }
Test-ExistingCeleryProcess
if (-not (Test-Port 5432) -or -not (Test-Port 6379)) {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        $dockerResult = Invoke-BoundedProcess "docker-start" "docker" @("compose", "up", "-d", "postgres", "redis") $Root 60
        if ($dockerResult.ExitCode -ne 0) { Fail "无法启动 PostgreSQL/Redis：$($dockerResult.Output)" }
        $Registry.infrastructure_started = $true
        Start-Sleep -Seconds 3
    }
}
if (-not (Test-Port 5432)) { Fail "PostgreSQL 未监听 127.0.0.1:5432" }
if (-not (Test-Port 6379)) { Fail "Redis 未监听 127.0.0.1:6379" }
foreach ($port in @(3000, 8000, 8080)) {
    if (Test-Port $port) { Fail "端口 $port 被未登记进程占用，已拒绝复用" }
}
$script:StartupInProgress = $true
Save-Registry

$backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"; $dataPy = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPy)) { Fail "缺少后端 Python 环境：$backendPy" }
if (-not (Test-Path $dataPy)) { Fail "缺少数据服务 Python 环境：$dataPy" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "找不到 npm" }
if ($InstallDependencies) {
    & (Join-Path $Root "scripts\bootstrap.ps1")
    if ($LASTEXITCODE -ne 0) { Fail "依赖准备失败" }
}
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) { Fail "前端依赖缺失，请先运行 .\scripts\bootstrap.ps1" }
$migrationResult = Invoke-BoundedProcess "migration" $backendPy @("-m", "alembic", "upgrade", "head") (Join-Path $Root "backend") 90
if ($migrationResult.ExitCode -ne 0) {
    if ($migrationResult.Output -match "InsufficientPrivilege|must be owner") {
        Fail "数据库迁移缺少表所有者权限，请运行 .\scripts\repair-db-owner.ps1 -AdminDatabaseUrl <管理员数据库 URL>"
    }
    Fail "数据库迁移失败，请检查 $RunDir 或运行 .\scripts\repair-db-owner.ps1 -CheckOnly"
}

[void](Start-ManagedProcess "data-service" $dataPy @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8080", "--no-access-log") (Join-Path $Root "a-stock-data\service"))
Wait-Http "数据服务" "http://127.0.0.1:8080/health"
[void](Start-ManagedProcess "backend" $backendPy @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log") (Join-Path $Root "backend"))
Wait-Http "后端" "http://127.0.0.1:8000/api/v1/health"
[void](Start-ManagedProcess "worker" $backendPy @("-m", "celery", "-A", "celery_app", "worker", "-Q", "high,normal,low", "--hostname=worker-sprint01@%h", "--pool=solo", "--concurrency=1", "--loglevel=info") (Join-Path $Root "worker"))
Wait-Celery
[void](Start-ManagedProcess "beat" $backendPy @("-m", "celery", "-A", "celery_app", "beat", "--loglevel=warning", "--scheduler", "redbeat.RedBeatScheduler") (Join-Path $Root "worker"))
[void](Start-ManagedProcess "frontend" "cmd.exe" @("/c", "npm", "run", "dev") (Join-Path $Root "frontend"))
Wait-Http "前端" "http://127.0.0.1:3000"
[void](Start-ManagedProcess "watchdog" "powershell.exe" @("-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Root "scripts\watchdog.ps1"), "-RegistryPath", $registryPath, "-StatusPath", (Join-Path $RunDir "watchdog-status.json"), "-LogDir", $LogDir) $Root)
Wait-Watchdog
& (Join-Path $Root "scripts\verify_local_env.ps1") -EnvFile $EnvFile
if ($LASTEXITCODE -ne 0) { Fail "环境验收失败，请检查 $LogDir" }
$script:StartupInProgress = $false
$script:LockHandle.Dispose()
Write-Host "启动完成：前端=http://127.0.0.1:3000 API=http://127.0.0.1:8000 日志=$LogDir" -ForegroundColor Green
