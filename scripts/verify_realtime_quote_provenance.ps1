#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api/v1",
    [int]$WaitSeconds = 45
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure([string]$Message) {
    $script:failures.Add($Message)
    Write-Host "FAIL  $Message" -ForegroundColor Red
}

function Add-Pass([string]$Message) {
    Write-Host "PASS  $Message" -ForegroundColor Green
}

function Get-ApiData([string]$Path) {
    $response = Invoke-RestMethod -Uri "$ApiBaseUrl$Path" -Method Get -TimeoutSec 20
    if (-not $response.success) { throw "接口未返回 success=true：$Path" }
    return $response.data
}

function Invoke-CheckedCommand([string]$Name, [scriptblock]$Command) {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) { Add-Failure "$Name 失败，退出码 $LASTEXITCODE" } else { Add-Pass $Name }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

Write-Host "开始实时行情 Provider 血缘验收" -ForegroundColor Cyan

$market = $null
$verificationStartedAt = [DateTimeOffset]::UtcNow
$deadline = (Get-Date).AddSeconds($WaitSeconds)
do {
    try {
        $candidate = Get-ApiData "/stock/market/status"
        $candidateBatch = $candidate.latest_batch
        $candidateReceivedAt = if ($candidateBatch.received_at) {
            [DateTimeOffset]::Parse($candidateBatch.received_at).ToUniversalTime()
        } else {
            [DateTimeOffset]::MinValue
        }
        if (
            $candidate.provider_metadata_status -eq "recorded" -and
            $null -ne $candidateBatch -and
            $candidateBatch.status -in @("success", "partial") -and
            [int]$candidateBatch.accepted_symbols -gt 0 -and
            $candidateReceivedAt -ge $verificationStartedAt.AddSeconds(-2)
        ) {
            $market = $candidate
            break
        }
    } catch {
        Write-Host "等待实时行情批次：$($_.Exception.Message)" -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if ($null -eq $market) {
    Add-Failure "未在 $WaitSeconds 秒内获得带 Provider 血缘的实时行情批次"
} else {
    $batch = $market.latest_batch
    if ($market.provider -ne "tencent") { Add-Failure "Provider 不是固定腾讯来源：$($market.provider)" } else { Add-Pass "Provider 固定为 tencent" }
    if ($market.provider_metadata_status -ne "recorded") { Add-Failure "行情 Provider 元数据未记录" } else { Add-Pass "行情 Provider 元数据已记录" }
    if ($market.fallback_status -ne "not_used") { Add-Failure "检测到未知或未记录的 fallback 状态：$($market.fallback_status)" } else { Add-Pass "未使用 fallback" }
    if ($batch.provider -in @("", "unknown", "synthetic") -or $batch.source -in @("", "unknown", "synthetic")) {
        Add-Failure "批次 Provider/source 不合法"
    } else { Add-Pass "批次 Provider/source 明确" }
    if ($batch.status -notin @("success", "partial")) { Add-Failure "最新批次状态不可用：$($batch.status)" } else { Add-Pass "最新批次状态：$($batch.status)" }
    if ([int]$batch.accepted_symbols -le 0) { Add-Failure "最新批次没有成功写入行情" } else { Add-Pass "批次已写入 $($batch.accepted_symbols) 条行情" }
    if (-not $batch.raw_response_hash -or $batch.raw_response_hash.Length -ne 64) { Add-Failure "批次缺少 64 位原始响应 Hash" } else { Add-Pass "批次原始响应 Hash 已记录" }
    if (-not $batch.collector_version -or -not $batch.normalizer_version) { Add-Failure "批次缺少采集或标准化版本" } else { Add-Pass "采集和标准化版本已记录" }
}

try {
    $batches = Get-ApiData "/stock/market/batches?limit=5"
    if (-not $batches.source -or $batches.source -ne "market.quote_batches") { Add-Failure "批次接口来源不明确" } else { Add-Pass "批次接口只读来源明确" }
    if (-not $batches.items -or $batches.items.Count -eq 0) { Add-Failure "批次接口未返回记录" } else { Add-Pass "批次接口返回 $($batches.items.Count) 条记录" }
} catch { Add-Failure "行情批次接口：$($_.Exception.Message)" }

try {
    $execution = Get-ApiData "/trade/execution-status?days=30"
    if (-not $execution.all_release_locks_closed) { Add-Failure "实时行情改造后存在已开启的发布或交易锁" } else { Add-Pass "六个发布与交易锁仍关闭" }
    if ($execution.order_audit.ai_source -ne 0 -or $execution.order_audit.scheduled_source -ne 0) {
        Add-Failure "检测到 AI 或定时任务来源订单"
    } else { Add-Pass "AI 与定时任务均未创建订单" }
} catch { Add-Failure "交易安全状态接口：$($_.Exception.Message)" }

Invoke-CheckedCommand "核心只读数据验收" {
    & (Join-Path $Root "scripts\verify_core_readonly_data.ps1") -ApiBaseUrl $ApiBaseUrl
}

if ($failures.Count -eq 0) {
    Write-Host "实时行情 Provider 血缘验收：PASS" -ForegroundColor Green
    exit 0
}

Write-Host "实时行情 Provider 血缘验收：FAIL" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
