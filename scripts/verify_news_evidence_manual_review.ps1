#Requires -Version 5.1
[CmdletBinding()]
param([string]$ApiBaseUrl = "http://127.0.0.1:8000/api/v1")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ReviewerLabel = "sprint14.6-acceptance"
$ReviewReason = "Acceptance: title/link requires more evidence; no body claim."
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

Write-Host "开始新闻证据人工复核验收" -ForegroundColor Cyan

$target = $null
try {
    $evidence = Get-ApiData "/research/evidence?evidence_type=news&quality_status=observed&page_size=50"
    $target = $evidence.items | Select-Object -First 1
    if ($null -eq $target) {
        Add-Failure "缺少已观察新闻证据，无法执行人工复核验收"
    } else {
        Add-Pass "找到已观察新闻证据：$($target.evidence_id)"
    }
} catch {
    Add-Failure "读取新闻证据失败：$($_.Exception.Message)"
}

if ($null -ne $target) {
    $beforeHash = $target.raw_hash
    $beforeAvailableAt = $target.available_at
    $beforeUsageStatus = $target.usage_status
    $payload = @{
        reviewer_label = $ReviewerLabel
        conclusion = "needs_more_evidence"
        reason = $ReviewReason
    } | ConvertTo-Json -Compress
    try {
        $reviewResponse = Invoke-RestMethod -Uri "$ApiBaseUrl/research/evidence/$($target.evidence_id)/reviews" -Method Post -ContentType "application/json; charset=utf-8" -Body $payload -TimeoutSec 20
        if (-not $reviewResponse.success) { throw "人工复核接口未返回 success=true" }
        $review = $reviewResponse.data.item
        if (($review.reviewer_label -ne $ReviewerLabel) -or ($review.conclusion -ne "needs_more_evidence") -or ($review.reason -ne $ReviewReason) -or (-not $review.reviewed_at)) {
            Add-Failure "人工复核记录字段不完整或语义错误"
        } else { Add-Pass "人工复核已追加并记录复核人、结论、理由和时间" }

        $history = Get-ApiData "/research/evidence/$($target.evidence_id)/reviews"
        if (@($history.items | Where-Object { $_.review_id -eq $review.review_id }).Count -ne 1) {
            Add-Failure "复核历史未保留新增记录"
        } else { Add-Pass "复核历史保留新增追加记录" }

        $afterResponse = Get-ApiData "/research/evidence?evidence_type=news&quality_status=observed&page_size=50"
        $after = $afterResponse.items | Where-Object { $_.evidence_id -eq $target.evidence_id } | Select-Object -First 1
        if ($null -eq $after) {
            Add-Failure "追加复核后无法读取原始新闻证据"
        } elseif (($after.raw_hash -ne $beforeHash) -or ($after.available_at -ne $beforeAvailableAt) -or ($after.usage_status -ne $beforeUsageStatus) -or ($after.manual_review.review_id -ne $review.review_id)) {
            Add-Failure "人工复核错误修改了原始新闻证据或未返回最新复核"
        } else { Add-Pass "原始 Hash、可得时间和使用状态保持不可变，最新复核可读" }
    } catch {
        Add-Failure "追加人工复核失败：$($_.Exception.Message)"
    }
}

try {
    $rejectedEvidence = Get-ApiData "/research/evidence?evidence_type=news&quality_status=rejected&page_size=1"
    $rejected = $rejectedEvidence.items | Select-Object -First 1
    if ($null -eq $rejected) {
        Add-Pass "当前无 rejected 新闻，跳过非法目标写入验证"
    } else {
        try {
            Invoke-RestMethod -Uri "$ApiBaseUrl/research/evidence/$($rejected.evidence_id)/reviews" -Method Post -ContentType "application/json; charset=utf-8" -Body (@{ reviewer_label = $ReviewerLabel; conclusion = "needs_more_evidence"; reason = $ReviewReason } | ConvertTo-Json -Compress) -TimeoutSec 20 | Out-Null
            Add-Failure "rejected 新闻被错误允许追加人工复核"
        } catch {
            $statusCode = [int]$_.Exception.Response.StatusCode
            if ($statusCode -eq 404) { Add-Pass "rejected 新闻被 fail-closed 拒绝" } else { Add-Failure "rejected 新闻拒绝状态异常：$statusCode" }
        }
    }
} catch {
    Add-Failure "非法目标写入验证失败：$($_.Exception.Message)"
}

try {
    $execution = Get-ApiData "/trade/execution-status?days=30"
    if (-not $execution.all_release_locks_closed) { Add-Failure "人工复核后存在已开启的发布或交易锁" } else { Add-Pass "六个发布与交易锁仍关闭" }
    if ($execution.order_audit.ai_source -ne 0 -or $execution.order_audit.scheduled_source -ne 0) {
        Add-Failure "检测到 AI 或定时任务来源订单"
    } else { Add-Pass "AI 与定时任务均未创建订单" }
} catch { Add-Failure "交易安全状态接口：$($_.Exception.Message)" }

$backendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (Test-Path $backendPython) {
    Invoke-CheckedCommand "后端新闻复核契约测试" {
        Push-Location (Join-Path $Root "backend")
        try { & $backendPython -m unittest discover -s tests -p "test_research_evidence_contracts.py" } finally { Pop-Location }
    }
}

Invoke-CheckedCommand "核心只读数据验收" {
    & (Join-Path $Root "scripts\verify_core_readonly_data.ps1") -ApiBaseUrl $ApiBaseUrl
}

if ($failures.Count -eq 0) {
    Write-Host "新闻证据人工复核验收：PASS" -ForegroundColor Green
    exit 0
}

Write-Host "新闻证据人工复核验收：FAIL" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
