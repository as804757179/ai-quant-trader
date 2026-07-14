#Requires -Version 5.1
[CmdletBinding()]
param([switch]$AsJson, [switch]$SkipCodexProcessCheck)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $env:LOCALAPPDATA "AIQuantTrader"
$RegistryPath = Join-Path $RuntimeRoot "run\local-services.json"
$WatchdogStatusPath = Join-Path $RuntimeRoot "run\watchdog-status.json"
$ToolHealthPath = Join-Path $RuntimeRoot "codex-tool-health.json"
$issues = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()
$mcpCount = 0
$mcpMemoryMb = 0
$replCount = 0
$openMcpCircuits = 0

function Add-Issue([string]$Message) { $script:issues.Add($Message) }
function Add-Warning([string]$Message) { $script:warnings.Add($Message) }

$os = Get-CimInstance Win32_OperatingSystem
$freeMemoryMb = [math]::Round($os.FreePhysicalMemory / 1024)
if ($freeMemoryMb -lt 3072) {
    Add-Issue "可用内存仅 $freeMemoryMb MB，低于 3072MB；请先重启 Codex 或释放内存"
}

if (-not $SkipCodexProcessCheck) {
    $processes = @(Get-CimInstance Win32_Process)
    $mcpProcesses = @($processes | Where-Object { $_.Name -eq "node.exe" -and $_.CommandLine -match "[/\\]mcp[/\\]server\.mjs" })
    $mcpCount = $mcpProcesses.Count
    $mcpMemoryMb = [math]::Round((($mcpProcesses | Measure-Object WorkingSetSize -Sum).Sum / 1MB))
    $replCount = @($processes | Where-Object { $_.Name -eq "node.exe" -and $_.CommandLine -match "node_repl" }).Count
    if ($mcpCount -gt 6) { Add-Warning "检测到 $mcpCount 个 MCP Node 进程，共占用约 $mcpMemoryMb MB；若数量继续增长请重启 Codex" }
    if ($mcpCount -ge 12 -or $mcpMemoryMb -gt 768) { Add-Issue "MCP 进程资源占用已超过安全阈值，请重启 Codex" }
    if ($replCount -gt 3) { Add-Warning "检测到 $replCount 个 Node REPL 进程；若任务已结束请重启 Codex" }
    if ($replCount -gt 8) { Add-Issue "Node REPL 残留已超过安全阈值，请重启 Codex" }
}

$backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
$dataPy = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPy)) {
    Add-Issue "缺少后端虚拟环境"
} else {
    $chromadbProbe = & $backendPy -c "import importlib.util; print('ok' if importlib.util.find_spec('chromadb') else 'missing')" 2>$null
    if (($chromadbProbe -join "") -ne "ok") { Add-Warning "当前 Python 无可用 chromadb，RAG 将按项目设计降级为空检索" }
}
if (-not (Test-Path $dataPy)) { Add-Issue "缺少数据服务虚拟环境" }
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) { Add-Issue "缺少前端依赖；请运行 scripts\bootstrap.ps1" }

$legacyLogDir = Join-Path $Root "logs"
if (Test-Path $legacyLogDir) {
    Get-ChildItem $legacyLogDir -File -Filter "*.log" -ErrorAction SilentlyContinue |
        Where-Object { $_.Length -gt 50MB } |
        ForEach-Object { Add-Issue "仓库内存在超过 50MB 的遗留日志：$($_.Name)" }
}
$runtimeLogDir = Join-Path $RuntimeRoot "logs"
if (Test-Path $runtimeLogDir) {
    Get-ChildItem $runtimeLogDir -File -Filter "*.log" -ErrorAction SilentlyContinue |
        Where-Object { $_.Length -gt 51MB } |
        ForEach-Object { Add-Issue "实时日志轮转异常：$($_.Name) 已超过 51MB" }
}

$port3001 = Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue
if ($port3001) { Add-Warning "端口 3001 正在监听，可能存在重复的前端开发服务" }

if (Test-Path $ToolHealthPath) {
    try {
        $toolHealth = Get-Content $ToolHealthPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($property in $toolHealth.tools.PSObject.Properties) {
            if ([int]$property.Value.consecutive_timeouts -ge 3) {
                $lastTimeout = [DateTimeOffset]::Parse([string]$property.Value.last_timeout_at)
                if (((Get-Date) - $lastTimeout.LocalDateTime).TotalMinutes -lt 10) {
                    $openMcpCircuits++
                    Add-Warning "MCP 工具 $($property.Name) 处于 10 分钟熔断期"
                }
            }
        }
    } catch {
        Add-Warning "MCP 工具健康状态文件损坏：$ToolHealthPath"
    }
}

if (Test-Path $RegistryPath) {
    try {
        $registry = Get-Content $RegistryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $registry.root -or [IO.Path]::GetFullPath([string]$registry.root) -ne [IO.Path]::GetFullPath($Root)) {
            Add-Issue "运行登记文件不属于当前项目"
        } else {
            foreach ($property in $registry.services.PSObject.Properties) {
                $entry = $property.Value
                $processId = [int]$entry.pid
                $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
                if (-not $process) {
                    Add-Issue "运行登记已过期：$($property.Name) 的进程不存在"
                    continue
                }
                if (-not $entry.command_pattern -or $process.CommandLine -notmatch [string]$entry.command_pattern) {
                    Add-Issue "运行登记异常：$($property.Name) 的命令行指纹不匹配"
                }
                if ($entry.started_at) {
                    $expectedStart = [DateTimeOffset]::Parse([string]$entry.started_at).UtcDateTime
                    $actualStart = ([datetime]$process.CreationDate).ToUniversalTime()
                    if ([math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 2) {
                        Add-Issue "运行登记异常：$($property.Name) 的启动时间不匹配"
                    }
                }
            }
            if (-not $registry.services.PSObject.Properties["watchdog"]) {
                Add-Issue "运行登记缺少 Watchdog"
            } elseif (-not (Test-Path $WatchdogStatusPath)) {
                Add-Issue "Watchdog 尚未产生状态文件"
            } else {
                try {
                    $watchdogStatus = Get-Content $WatchdogStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    $watchdogAgeSeconds = ((Get-Date) - [DateTimeOffset]::Parse([string]$watchdogStatus.checked_at).LocalDateTime).TotalSeconds
                    if ($watchdogAgeSeconds -gt 90) { Add-Issue "Watchdog 状态已超过 90 秒未更新" }
                    if (-not $watchdogStatus.ok) {
                        $watchdogStatus.issues | ForEach-Object { Add-Issue "Watchdog：$_" }
                    }
                    $watchdogStatus.warnings | ForEach-Object { Add-Warning "Watchdog：$_" }
                } catch {
                    Add-Issue "Watchdog 状态文件损坏：$WatchdogStatusPath"
                }
            }
        }
    } catch {
        Add-Issue "运行登记文件损坏：$RegistryPath"
    }
}

$result = [ordered]@{
    ok = ($issues.Count -eq 0)
    free_memory_mb = $freeMemoryMb
    mcp_process_count = $mcpCount
    mcp_memory_mb = $mcpMemoryMb
    repl_process_count = $replCount
    open_mcp_circuits = $openMcpCircuits
    issues = @($issues)
    warnings = @($warnings)
}
if ($AsJson) {
    $result | ConvertTo-Json -Depth 4 -Compress
} else {
    if ($issues.Count -eq 0) {
        Write-Host "诊断通过，可用内存：$freeMemoryMb MB。" -ForegroundColor Green
    } else {
        Write-Host "诊断未通过：" -ForegroundColor Red
        $issues | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    }
    if ($warnings.Count -gt 0) {
        Write-Host "提醒：" -ForegroundColor Yellow
        $warnings | ForEach-Object { Write-Host "- $_" -ForegroundColor Yellow }
    }
}
if ($issues.Count -eq 0) { exit 0 }
exit 1
