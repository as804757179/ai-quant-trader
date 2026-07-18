#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api/v1",
    [string]$DataServiceUrl = "http://127.0.0.1:8080",
    [string]$Symbol = "000001.SZ"
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

Write-Host "开始多维研究证据观察验收" -ForegroundColor Cyan

$backendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPython)) {
    Add-Failure "缺少后端 Python 环境"
} else {
    Invoke-CheckedCommand "固定 Provider 公告采集" {
        & $backendPython (Join-Path $Root "scripts\collect_research_evidence.py") `
            --symbol $Symbol --limit 1 --data-service-url $DataServiceUrl
    }
}

try {
    $market = Get-ApiData "/stock/market/status"
    if ($market.market_session -in @("calendar_not_covered", "calendar_unresolved")) {
        Add-Failure "当前日期认证交易日历仍不可用：$($market.market_session)"
    } else {
        Add-Pass "当前日期沪深认证交易日历已覆盖：$($market.market_session)"
    }
} catch { Add-Failure "交易日历状态接口：$($_.Exception.Message)" }

try {
    $evidencePath = '/research/evidence?stock_code={0}&page_size=10' -f [Uri]::EscapeDataString($Symbol)
    $evidence = Get-ApiData $evidencePath
    $observed = @($evidence.items | Where-Object { $_.quality_status -eq "observed" }) | Select-Object -First 1
    if ($null -eq $observed) {
        Add-Failure "未找到已观测公告证据"
    } else {
        if ($observed.provider -ne "cninfo" -or $observed.source -ne "cninfo_listed_company_disclosure") {
            Add-Failure "公告 Provider/source 不符合固定来源"
        } else { Add-Pass "公告 Provider/source 已记录" }
        if ($observed.fallback_used) { Add-Failure "公告证据检测到 fallback" } else { Add-Pass "公告证据未使用 fallback" }
        if (-not $observed.raw_hash -or $observed.raw_hash -notmatch '^[0-9a-f]{64}$') {
            Add-Failure "公告原文缺少 64 位 SHA-256 Hash"
        } else { Add-Pass "公告原文 Hash 已记录" }
        if (-not $observed.source_published_date -or $observed.source_published_at) {
            Add-Failure "公告来源时间精度语义错误"
        } elseif ($observed.publication_time_precision -ne "date") {
            Add-Failure "公告时间精度未标记为 date"
        } else { Add-Pass "公告日期精度与来源时间语义正确" }
        if ($observed.availability_basis -ne "system_first_observed" -or -not $observed.available_at) {
            Add-Failure "公告可得时间未按首次系统观测记录"
        } else { Add-Pass "公告可得时间已按首次系统观测记录" }
        if ($observed.usage_status -ne "review_required") {
            Add-Failure "公告 Provider 使用状态被错误放宽"
        } else { Add-Pass "公告 Provider 使用状态保持 review_required" }
    }
    if (-not $evidence.observed_only -or $evidence.research_readiness -ne "not_granted" -or $evidence.tradable -or $evidence.order_created) {
        Add-Failure "公告证据错误获得 Research Readiness 或交易权限"
    } else { Add-Pass "公告证据保持 observed-only 且不可交易" }
} catch { Add-Failure "研究证据接口：$($_.Exception.Message)" }

try {
    $batches = Get-ApiData "/research/evidence/batches?limit=10"
    $batch = @($batches.items | Where-Object { $_.provider -eq "cninfo" }) | Select-Object -First 1
    if ($null -eq $batch) {
        Add-Failure "未找到巨潮公告证据批次"
    } elseif ($batch.status -notin @("success", "partial")) {
        Add-Failure "公告证据批次状态不可用：$($batch.status)"
    } else {
        Add-Pass "公告证据批次状态：$($batch.status)"
    }
} catch { Add-Failure "研究证据批次接口：$($_.Exception.Message)" }

try {
    $execution = Get-ApiData "/trade/execution-status?days=30"
    if (-not $execution.all_release_locks_closed) { Add-Failure "研究证据改造后存在已开启的发布或交易锁" } else { Add-Pass "六个发布与交易锁仍关闭" }
    if ($execution.order_audit.ai_source -ne 0 -or $execution.order_audit.scheduled_source -ne 0) {
        Add-Failure "检测到 AI 或定时任务来源订单"
    } else { Add-Pass "AI 与定时任务均未创建订单" }
} catch { Add-Failure "交易安全状态接口：$($_.Exception.Message)" }

if (Test-Path $backendPython) {
    Invoke-CheckedCommand "Worker 研究证据测试" {
        Push-Location (Join-Path $Root "worker")
        try { & $backendPython -m unittest discover -s tests -p "test_research_evidence*.py" } finally { Pop-Location }
    }
    Invoke-CheckedCommand "公告 Provider 测试" {
        Push-Location $Root
        try { & $backendPython -m unittest discover -s "a-stock-data\tests" -p "test_announcement_provenance.py" } finally { Pop-Location }
    }
}

Invoke-CheckedCommand "核心只读数据验收" {
    & (Join-Path $Root "scripts\verify_core_readonly_data.ps1") -ApiBaseUrl $ApiBaseUrl
}

if ($failures.Count -eq 0) {
    Write-Host "多维研究证据观察验收：PASS" -ForegroundColor Green
    exit 0
}

Write-Host "多维研究证据观察验收：FAIL" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
