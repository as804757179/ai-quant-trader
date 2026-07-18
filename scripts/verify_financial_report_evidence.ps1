#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api/v1",
    [string]$DataServiceUrl = "http://127.0.0.1:8080"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Symbols = @("000001.SZ", "600000.SH")
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

Write-Host "开始年报全文证据观察验收" -ForegroundColor Cyan

$backendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPython)) {
    Add-Failure "缺少后端 Python 环境"
} else {
    Invoke-CheckedCommand "固定 Provider 年报采集" {
        & $backendPython (Join-Path $Root "scripts\collect_financial_report_evidence.py") `
            --data-service-url $DataServiceUrl
    }
}

foreach ($symbol in $Symbols) {
    try {
        $evidencePath = '/research/evidence?stock_code={0}&evidence_type=financial_report&page_size=20' -f [Uri]::EscapeDataString($symbol)
        $evidence = Get-ApiData $evidencePath
        $observed = @($evidence.items | Where-Object { $_.quality_status -eq "observed" }) | Select-Object -First 1
        if ($null -eq $observed) {
            Add-Failure "$symbol 未找到已观测年报全文证据"
            continue
        }
        if (($observed.provider -ne "cninfo") -or ($observed.source -ne "cninfo_listed_company_disclosure")) {
            Add-Failure "$symbol 年报 Provider/source 不符合固定来源"
        }
        else {
            Add-Pass "$symbol 年报 Provider/source 已记录"
        }
        if ($observed.fallback_used) {
            Add-Failure "$symbol 年报检测到 fallback"
        }
        else {
            Add-Pass "$symbol 年报未使用 fallback"
        }
        if ((-not $observed.raw_hash) -or ($observed.raw_hash -notmatch '^[0-9a-f]{64}$')) {
            Add-Failure "$symbol 年报原文缺少 64 位 SHA-256 Hash"
        }
        else {
            Add-Pass "$symbol 年报原文 Hash 已记录"
        }
        if ((-not $observed.source_published_date) -or $observed.source_published_at -or ($observed.publication_time_precision -ne "date")) {
            Add-Failure "$symbol 年报来源时间精度语义错误"
        }
        else {
            Add-Pass "$symbol 年报日期精度与来源时间语义正确"
        }
        if (($observed.availability_basis -ne "system_first_observed") -or (-not $observed.available_at)) {
            Add-Failure "$symbol 年报可得时间未按首次系统观测记录"
        }
        else {
            Add-Pass "$symbol 年报可得时间已按首次系统观测记录"
        }
        if ($observed.usage_status -ne "review_required") {
            Add-Failure "$symbol 年报 Provider 使用状态被错误放宽"
        }
        else {
            Add-Pass "$symbol 年报 Provider 使用状态保持 review_required"
        }

        $detail = $observed.financial_report_detail
        if ($null -eq $detail) {
            Add-Failure "$symbol 年报缺少财报详情 sidecar"
        }
        else {
            $invalidMetadata = (
                ($detail.provider_category -ne "category_ndbg_szsh") -or
                ($detail.report_kind -ne "annual") -or
                ($detail.period_precision -ne "title_label") -or
                ($detail.document_role -ne "full_report") -or
                ($detail.detail_parse_status -ne "metadata_observed")
            )
            $invalidUnresolvedState = (
                ($null -ne $detail.report_period_end) -or
                ($detail.consolidation_scope -ne "unresolved") -or
                ($detail.currency_code -ne "unresolved") -or
                ($detail.currency_unit -ne "unresolved") -or
                ($detail.audit_opinion -ne "unresolved") -or
                ($detail.revision_status -ne "none") -or
                ($null -ne $detail.supersedes_evidence_id)
            )
            if ($invalidMetadata) {
                Add-Failure "$symbol 年报详情元数据不符合固定范围"
            }
            if ($invalidUnresolvedState) {
                Add-Failure "$symbol 年报详情错误推导了解析或修订语义"
            }
            if (-not $invalidMetadata -and -not $invalidUnresolvedState) {
                Add-Pass "$symbol 年报详情保持未解析观察语义"
            }
        }
    }
    catch {
        Add-Failure "$symbol 年报证据接口：$($_.Exception.Message)"
    }
}

try {
    $batches = Get-ApiData "/research/evidence/batches?limit=20"
    $annualBatches = @($batches.items | Where-Object { $_.collector_version -eq "cninfo-annual-report-collector-v1" })
    $latestAnnualBatches = @($annualBatches | Select-Object -First $Symbols.Count)
    if ($latestAnnualBatches.Count -lt $Symbols.Count) {
        Add-Failure "未找到完整的固定样本年报证据批次"
    } elseif (@($latestAnnualBatches | Where-Object { $_.status -notin @("success", "partial") }).Count -gt 0) {
        Add-Failure "本轮存在不可用的年报证据批次"
    } else { Add-Pass "本轮固定样本年报证据批次状态可用" }
} catch { Add-Failure "年报证据批次接口：$($_.Exception.Message)" }

try {
    $execution = Get-ApiData "/trade/execution-status?days=30"
    if (-not $execution.all_release_locks_closed) { Add-Failure "年报证据改造后存在已开启的发布或交易锁" } else { Add-Pass "六个发布与交易锁仍关闭" }
    if ($execution.order_audit.ai_source -ne 0 -or $execution.order_audit.scheduled_source -ne 0) {
        Add-Failure "检测到 AI 或定时任务来源订单"
    } else { Add-Pass "AI 与定时任务均未创建订单" }
} catch { Add-Failure "交易安全状态接口：$($_.Exception.Message)" }

if (Test-Path $backendPython) {
    Invoke-CheckedCommand "Worker 研究证据测试" {
        Push-Location (Join-Path $Root "worker")
        try { & $backendPython -m unittest discover -s tests -p "test_research_evidence*.py" } finally { Pop-Location }
    }
    Invoke-CheckedCommand "巨潮证据 Provider 测试" {
        Push-Location $Root
        try { & $backendPython -m unittest discover -s "a-stock-data\tests" -p "test_*_provenance.py" } finally { Pop-Location }
    }
    Invoke-CheckedCommand "后端研究证据契约测试" {
        Push-Location (Join-Path $Root "backend")
        try { & $backendPython -m unittest discover -s tests -p "test_research_evidence_contracts.py" } finally { Pop-Location }
    }
}

Invoke-CheckedCommand "核心只读数据验收" {
    & (Join-Path $Root "scripts\verify_core_readonly_data.ps1") -ApiBaseUrl $ApiBaseUrl
}

if ($failures.Count -eq 0) {
    Write-Host "年报全文证据观察验收：PASS" -ForegroundColor Green
    exit 0
}

Write-Host "年报全文证据观察验收：FAIL" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
