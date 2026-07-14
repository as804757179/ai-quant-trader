#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$rawInput = [Console]::In.ReadToEnd()
if (-not $rawInput) { exit 0 }

try {
    $payload = $rawInput | ConvertFrom-Json
} catch {
    exit 0
}

$eventName = [string]$payload.hook_event_name
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ToolHealthPath = Join-Path $env:LOCALAPPDATA "AIQuantTrader\codex-tool-health.json"

function Read-ToolHealth {
    $records = [ordered]@{}
    if (-not (Test-Path $ToolHealthPath)) { return $records }
    $state = Get-Content $ToolHealthPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.tools) {
        foreach ($property in $state.tools.PSObject.Properties) {
            $records[$property.Name] = [ordered]@{
                consecutive_timeouts = [int]$property.Value.consecutive_timeouts
                last_timeout_at = [string]$property.Value.last_timeout_at
            }
        }
    }
    return $records
}

function Save-ToolHealth([System.Collections.IDictionary]$Records) {
    $directory = Split-Path -Parent $ToolHealthPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporaryPath = "$ToolHealthPath.tmp"
    [ordered]@{ updated_at = (Get-Date).ToString("o"); tools = $Records } |
        ConvertTo-Json -Depth 5 |
        Set-Content $temporaryPath -Encoding UTF8
    Move-Item $temporaryPath $ToolHealthPath -Force
}

if ($eventName -in @("SessionStart", "UserPromptSubmit")) {
    $doctorOutput = & (Join-Path $Root "scripts\doctor.ps1") -AsJson 2>$null
    if (-not $doctorOutput) {
        if ($eventName -eq "UserPromptSubmit") {
            [ordered]@{ systemMessage = "项目预检失败，请手动运行 scripts\doctor.ps1。" } | ConvertTo-Json -Compress
            exit 0
        }
        [ordered]@{
            continue = $false
            stopReason = "项目预检未产生结果"
            systemMessage = "项目预检失败，请手动运行 scripts\doctor.ps1。"
        } | ConvertTo-Json -Compress
        exit 0
    }
    $diagnosis = ($doctorOutput -join "") | ConvertFrom-Json
    if (-not $diagnosis.ok) {
        $reason = $diagnosis.issues -join "；"
        if ($eventName -eq "UserPromptSubmit") {
            [ordered]@{
                systemMessage = "项目预检未通过：$reason"
                hookSpecificOutput = [ordered]@{
                    hookEventName = "UserPromptSubmit"
                    additionalContext = "先处理项目预检异常，再执行可能加重资源占用的操作：$reason"
                }
            } | ConvertTo-Json -Depth 4 -Compress
            exit 0
        }
        [ordered]@{
            continue = $false
            stopReason = $reason
            systemMessage = "项目预检未通过：$reason"
        } | ConvertTo-Json -Compress
        exit 0
    }
    if ($diagnosis.warnings.Count -gt 0) {
        [ordered]@{
            hookSpecificOutput = [ordered]@{
                hookEventName = $eventName
                additionalContext = "项目预检提醒：" + ($diagnosis.warnings -join "；")
            }
        } | ConvertTo-Json -Depth 4 -Compress
    }
    exit 0
}

$toolName = [string]$payload.tool_name
if ($eventName -eq "PostToolUse") {
    if ($toolName -notmatch "^mcp__") { exit 0 }
    $mutex = $null
    $lockTaken = $false
    try {
        $responseText = $payload.tool_response | ConvertTo-Json -Depth 20 -Compress
        $errorProperty = $payload.tool_response.PSObject.Properties["error"]
        $isErrorProperty = $payload.tool_response.PSObject.Properties["isError"]
        $isErrorSnakeProperty = $payload.tool_response.PSObject.Properties["is_error"]
        $reportedError = ($errorProperty -and $errorProperty.Value) -or
            ($isErrorProperty -and [bool]$isErrorProperty.Value) -or
            ($isErrorSnakeProperty -and [bool]$isErrorSnakeProperty.Value) -or
            ($payload.tool_response -is [string] -and [string]$payload.tool_response -match "(?i)^(error|tool .*failed|request .*failed)")
        $mutex = [Threading.Mutex]::new($false, "Local\AIQuantTraderCodexToolHealth")
        $lockTaken = $mutex.WaitOne(2000)
        if (-not $lockTaken) { throw "等待 MCP 状态锁超过 2 秒" }
        $records = Read-ToolHealth
        if ($reportedError -and $responseText -match "(?i)timed?\s*out|timeout|deadline exceeded|ETIMEDOUT|operation.*time.*out|工具.*超时") {
            $previousCount = if ($records.Contains($toolName)) { [int]$records[$toolName].consecutive_timeouts } else { 0 }
            $records[$toolName] = [ordered]@{
                consecutive_timeouts = $previousCount + 1
                last_timeout_at = (Get-Date).ToString("o")
            }
            Save-ToolHealth $records
            if (($previousCount + 1) -ge 3) {
                [ordered]@{ systemMessage = "MCP 工具 $toolName 已连续超时 $($previousCount + 1) 次，将熔断 10 分钟。" } | ConvertTo-Json -Compress
            }
        } elseif ($records.Contains($toolName)) {
            $records.Remove($toolName)
            Save-ToolHealth $records
        }
    } catch {
        [ordered]@{ systemMessage = "MCP 超时状态记录失败：$($_.Exception.Message)" } | ConvertTo-Json -Compress
    } finally {
        if ($lockTaken) { $mutex.ReleaseMutex() }
        if ($mutex) { $mutex.Dispose() }
    }
    exit 0
}

if ($eventName -ne "PreToolUse") { exit 0 }
if ($toolName -match "^mcp__") {
    try {
        $records = Read-ToolHealth
        if ($records.Contains($toolName) -and [int]$records[$toolName].consecutive_timeouts -ge 3) {
            $lastTimeout = [DateTimeOffset]::Parse([string]$records[$toolName].last_timeout_at)
            if (((Get-Date) - $lastTimeout.LocalDateTime).TotalMinutes -lt 10) {
                [ordered]@{
                    hookSpecificOutput = [ordered]@{
                        hookEventName = "PreToolUse"
                        permissionDecision = "deny"
                        permissionDecisionReason = "MCP 工具 $toolName 已连续超时，10 分钟熔断期内拒绝再次调用；请改用其他工具或稍后重试。"
                    }
                } | ConvertTo-Json -Depth 4 -Compress
                exit 0
            }
        }
    } catch {
        [ordered]@{ systemMessage = "MCP 熔断状态读取失败：$($_.Exception.Message)" } | ConvertTo-Json -Compress
    }
}

$command = [string]$payload.tool_input.command
if ($toolName -match "functions\.exec") {
    if ($command -notmatch "tools\.shell_command") { exit 0 }
    $commandMatch = [regex]::Match($command, 'command\s*:\s*"(?<command>(?:\\.|[^"])*)"')
    if (-not $commandMatch.Success) { exit 0 }
    $command = $commandMatch.Groups["command"].Value -replace '\\"', '"'
}
if (-not $command) { exit 0 }
if ($command -match "scripts[\\/]start-(local|dev)\.ps1|scripts[\\/]stop-local\.ps1") { exit 0 }

$blockedReason = $null
if ($command -match "(?i)\b(npm|pnpm|yarn)(\.cmd|\.exe)?\s+(run\s+)?dev\b|\bmake\s+(dev|logs)\b") {
    $blockedReason = "禁止直接启动前台开发服务，请使用 scripts\start-dev.ps1。"
} elseif ($command -match "(?i)\b(vite|uvicorn)(\.exe)?\s+|\bcelery\b.*\b(worker|beat)\b") {
    $blockedReason = "禁止绕过项目运行登记启动常驻进程，请使用 scripts\start-local.ps1。"
} elseif ($command -match "(?i)docker\s+compose\s+logs\b.*(--follow|-f)\b") {
    $blockedReason = "禁止无界跟随日志；请读取有限行数的运行日志。"
} elseif ($command -match "(?i)docker\s+compose\s+up\b" -and $command -notmatch "(?i)(^|\s)-d(\s|$)") {
    $blockedReason = "禁止前台运行 docker compose up；请使用项目启动脚本。"
}

if ($blockedReason) {
    [ordered]@{
        hookSpecificOutput = [ordered]@{
            hookEventName = "PreToolUse"
            permissionDecision = "deny"
            permissionDecisionReason = $blockedReason
        }
    } | ConvertTo-Json -Depth 4 -Compress
}
exit 0
