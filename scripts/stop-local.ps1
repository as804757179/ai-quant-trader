#Requires -Version 5.1
[CmdletBinding()]
param([switch]$KeepInfrastructure, [switch]$Quiet)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $env:LOCALAPPDATA "AIQuantTrader"
$RegistryPath = Join-Path $RuntimeRoot "run\local-services.json"
$WatchdogStatusPath = Join-Path $RuntimeRoot "run\watchdog-status.json"
$failures = [System.Collections.Generic.List[string]]::new()

function Write-Status([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::Gray) {
    if (-not $Quiet) { Write-Host $Message -ForegroundColor $Color }
}

function Stop-RegisteredProcess([string]$Name, [object]$Entry) {
    if (-not $Entry -or -not $Entry.pid) { return }
    $processId = [int]$Entry.pid
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if (-not $process) {
        Write-Status "已停止：$Name（登记进程不存在）"
        return
    }
    if (-not $Entry.command_pattern -or $process.CommandLine -notmatch [string]$Entry.command_pattern) {
        $failures.Add("$Name 的 PID $processId 与登记的命令行指纹不匹配，已拒绝终止")
        return
    }
    if ($Entry.started_at) {
        $expectedStart = [DateTimeOffset]::Parse([string]$Entry.started_at).UtcDateTime
        $actualStart = ([datetime]$process.CreationDate).ToUniversalTime()
        if ([math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 2) {
            $failures.Add("$Name 的 PID $processId 启动时间不匹配，已拒绝终止")
            return
        }
    }
    & taskkill.exe /PID $processId /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $failures.Add("$Name 的 PID $processId 终止失败")
        return
    }
    Write-Status "已停止：$Name"
}

function Clear-RedBeatLock {
    $envPath = Join-Path $Root ".env.host"
    if (-not (Test-Path $envPath)) {
        $failures.Add("无法清理 RedBeat 锁：缺少 .env.host")
        return
    }
    $redisUrl = $null
    Get-Content $envPath -Encoding UTF8 | ForEach-Object {
        if ($_.Trim() -match "^REDIS_URL=(.+)$") { $redisUrl = $matches[1].Trim() }
    }
    if (-not $redisUrl -or -not (Get-Command redis-cli -ErrorAction SilentlyContinue)) {
        $failures.Add("无法清理 RedBeat 锁：缺少 Redis 连接或 redis-cli")
        return
    }
    $activeBeat = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match "-m celery -A celery_app beat" }
    if ($activeBeat) {
        $failures.Add("检测到仍在运行的 Celery Beat，已拒绝清理 RedBeat 锁")
        return
    }
    try {
        $redisUri = [Uri]$redisUrl
    } catch {
        $failures.Add("无法清理 RedBeat 锁：REDIS_URL 格式无效")
        return
    }
    $result = & redis-cli -h $redisUri.Host -p $redisUri.Port DEL "redbeat::lock"
    if ($LASTEXITCODE -ne 0) {
        $failures.Add("清理 RedBeat 锁失败")
        return
    }
    Write-Status "RedBeat 锁已清理：$result" DarkGray
}

if (-not (Test-Path $RegistryPath)) {
    Remove-Item $WatchdogStatusPath -Force -ErrorAction SilentlyContinue
    Write-Status "没有已登记的本地服务。" DarkGray
    exit 0
}

try {
    $registry = Get-Content $RegistryPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Host "停止失败：运行登记文件损坏：$RegistryPath" -ForegroundColor Red
    exit 1
}

if (-not $registry.root -or [IO.Path]::GetFullPath([string]$registry.root) -ne [IO.Path]::GetFullPath($Root)) {
    Write-Host "停止失败：运行登记文件不属于当前项目，已拒绝操作。" -ForegroundColor Red
    exit 1
}

foreach ($serviceName in @("watchdog", "frontend", "beat", "worker", "backend", "data-service")) {
    $property = $registry.services.PSObject.Properties[$serviceName]
    if ($property) { Stop-RegisteredProcess $serviceName $property.Value }
}

if ($failures.Count -eq 0 -and $registry.services.PSObject.Properties["beat"]) {
    Clear-RedBeatLock
}

if ($failures.Count -eq 0 -and $registry.infrastructure_started -and -not $KeepInfrastructure) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        $failures.Add("本次启动的 PostgreSQL/Redis 需要停止，但找不到 docker")
    } else {
        $dockerOut = Join-Path $RuntimeRoot "run\docker-stop.out.log"
        $dockerErr = Join-Path $RuntimeRoot "run\docker-stop.err.log"
        $docker = Start-Process -FilePath "docker" -ArgumentList @("compose", "stop", "postgres", "redis") -WorkingDirectory $Root -RedirectStandardOutput $dockerOut -RedirectStandardError $dockerErr -WindowStyle Hidden -PassThru
        [void]$docker.Handle
        if (-not $docker.WaitForExit(30000)) {
            & taskkill.exe /PID $docker.Id /T /F | Out-Null
            $failures.Add("停止 PostgreSQL/Redis 超过 30 秒")
        } elseif ($docker.ExitCode -ne 0) {
            $failures.Add("停止 PostgreSQL/Redis 失败，请检查 $dockerErr")
        }
    }
}

if ($failures.Count -gt 0) {
    Write-Host "停止未完成：" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Remove-Item $RegistryPath -Force
Remove-Item $WatchdogStatusPath -Force -ErrorAction SilentlyContinue
Write-Status "本地项目服务已安全停止。" Green
exit 0
