#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$RegistryPath = (Join-Path $env:LOCALAPPDATA "AIQuantTrader\run\local-services.json"),
    [string]$StatusPath = (Join-Path $env:LOCALAPPDATA "AIQuantTrader\run\watchdog-status.json"),
    [string]$LogDir = (Join-Path $env:LOCALAPPDATA "AIQuantTrader\logs"),
    [int]$IntervalSeconds = 30,
    [long]$MaxLogBytes = 50MB,
    [int]$MinFreeMemoryMb = 3072,
    [int]$MaxMcpCount = 12,
    [int]$MaxMcpMemoryMb = 768,
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$lastFingerprint = $null

function Get-WatchdogStatus {
    $issues = [System.Collections.Generic.List[string]]::new()
    $warnings = [System.Collections.Generic.List[string]]::new()
    if (-not (Test-Path $RegistryPath)) {
        $issues.Add("运行登记文件不存在")
    } else {
        try {
            $registry = Get-Content $RegistryPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if (-not $registry.root -or [IO.Path]::GetFullPath([string]$registry.root) -ne [IO.Path]::GetFullPath($Root)) {
                $issues.Add("运行登记文件不属于当前项目")
            } else {
                foreach ($property in $registry.services.PSObject.Properties) {
                    $entry = $property.Value
                    $processId = [int]$entry.pid
                    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
                    if (-not $process) {
                        $issues.Add("$($property.Name) 的登记进程不存在")
                        continue
                    }
                    if (-not $entry.command_pattern -or $process.CommandLine -notmatch [string]$entry.command_pattern) {
                        $issues.Add("$($property.Name) 的命令行指纹不匹配")
                    }
                    if ($entry.started_at) {
                        $expectedStart = [DateTimeOffset]::Parse([string]$entry.started_at).UtcDateTime
                        $actualStart = ([datetime]$process.CreationDate).ToUniversalTime()
                        if ([math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 2) {
                            $issues.Add("$($property.Name) 的启动时间不匹配")
                        }
                    }
                }
            }
        } catch {
            $issues.Add("运行登记文件损坏：$($_.Exception.Message)")
        }
    }

    if (Test-Path $LogDir) {
        Get-ChildItem $LogDir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "\.log$" -and $_.Length -gt ($MaxLogBytes + 1MB) } |
            ForEach-Object { $issues.Add("实时日志轮转异常：$($_.Name) 已达到 $([math]::Round($_.Length / 1MB, 1)) MB") }
    }

    $os = Get-CimInstance Win32_OperatingSystem
    $freeMemoryMb = [math]::Round($os.FreePhysicalMemory / 1024)
    if ($freeMemoryMb -lt $MinFreeMemoryMb) {
        $issues.Add("可用内存仅 $freeMemoryMb MB，低于 $MinFreeMemoryMb MB")
    }
    $processes = @(Get-CimInstance Win32_Process)
    $mcpProcesses = @($processes | Where-Object { $_.Name -eq "node.exe" -and $_.CommandLine -match "[/\\]mcp[/\\]server\.mjs" })
    $mcpCount = $mcpProcesses.Count
    $mcpMemoryMb = [math]::Round((($mcpProcesses | Measure-Object WorkingSetSize -Sum).Sum / 1MB))
    if ($mcpCount -gt 6) { $warnings.Add("MCP Node 进程数为 $mcpCount，共约 $mcpMemoryMb MB") }
    if ($mcpCount -ge $MaxMcpCount -or $mcpMemoryMb -gt $MaxMcpMemoryMb) {
        $issues.Add("MCP 进程资源超过安全阈值，请重启 Codex")
    }

    return [ordered]@{
        ok = ($issues.Count -eq 0)
        checked_at = (Get-Date).ToString("o")
        issues = @($issues)
        warnings = @($warnings)
        metrics = [ordered]@{
            free_memory_mb = $freeMemoryMb
            mcp_process_count = $mcpCount
            mcp_memory_mb = $mcpMemoryMb
        }
    }
}

do {
    try {
        $status = Get-WatchdogStatus
    } catch {
        $status = [ordered]@{
            ok = $false
            checked_at = (Get-Date).ToString("o")
            issues = @("Watchdog 检查失败：$($_.Exception.Message)")
            warnings = @()
            metrics = [ordered]@{}
        }
    }
    $statusDirectory = Split-Path -Parent $StatusPath
    New-Item -ItemType Directory -Path $statusDirectory -Force | Out-Null
    $temporaryPath = "$StatusPath.tmp"
    $status | ConvertTo-Json -Depth 5 | Set-Content $temporaryPath -Encoding UTF8
    Move-Item $temporaryPath $StatusPath -Force

    $fingerprint = (@($status.issues) + @($status.warnings)) -join "|"
    if ($fingerprint -ne $lastFingerprint) {
        if ($status.ok) {
            Write-Output "Watchdog 检查通过。"
        } else {
            Write-Output "Watchdog 发现异常：$($status.issues -join '；')"
        }
        if ($status.warnings.Count -gt 0) { Write-Output "Watchdog 提醒：$($status.warnings -join '；')" }
        $lastFingerprint = $fingerprint
    }
    if (-not $Once) { Start-Sleep -Seconds $IntervalSeconds }
} while (-not $Once)
