#Requires -Version 5.1
[CmdletBinding()]
param([string]$ApiBaseUrl = "http://127.0.0.1:8000/api/v1")

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

function Get-AuditData($AuditProfile) {
    $query = [System.Collections.Generic.List[string]]::new()
    $query.Add("research_use_scope=$([Uri]::EscapeDataString($AuditProfile.Scope))")
    $query.Add("requirement_profile=$([Uri]::EscapeDataString($AuditProfile.Name))")
    foreach ($field in $AuditProfile.Fields) {
        $query.Add("required_fields=$([Uri]::EscapeDataString($field))")
    }
    $query.Add("page_size=200")
    return Get-ApiData ("/research/evidence/readiness-audit?" + ($query -join "&"))
}

function Get-EvidenceSnapshot($EvidenceData) {
    $rows = [System.Collections.Generic.List[string]]::new()
    foreach ($item in $EvidenceData.items) {
        $rows.Add("$($item.evidence_id)|$($item.raw_hash)|$($item.available_at)|$($item.usage_status)")
    }
    return [string]::Join("`n", @($rows | Sort-Object))
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

$profiles = @(
    [pscustomobject]@{
        Name = "ANNOUNCEMENT_EVENT_RESEARCH_V1"
        Scope = "announcement_event_research"
        Fields = @(
            "evidence_quality", "original_document_hash", "available_at",
            "source_publication_time", "security_association",
            "event_content_validation", "revision_lineage", "provider_usage_permission"
        )
        ExpectedCodes = @(
            "ANNOUNCEMENT_PUBLICATION_TIME_DATE_ONLY",
            "ANNOUNCEMENT_EVENT_CONTENT_UNPARSED",
            "ANNOUNCEMENT_REVISION_LINEAGE_UNVERIFIED"
        )
    },
    [pscustomobject]@{
        Name = "FINANCIAL_REPORT_FUNDAMENTAL_RESEARCH_V1"
        Scope = "financial_report_research"
        Fields = @(
            "evidence_quality", "original_document_hash", "available_at",
            "security_association", "report_period_end", "consolidation_scope",
            "currency_code", "currency_unit", "audit_opinion",
            "financial_fact_provenance", "revision_lineage", "provider_usage_permission"
        )
        ExpectedCodes = @(
            "REPORT_PERIOD_END_UNRESOLVED", "CONSOLIDATION_SCOPE_UNRESOLVED",
            "CURRENCY_OR_UNIT_UNRESOLVED", "AUDIT_OPINION_UNRESOLVED",
            "FINANCIAL_FACTS_UNPARSED"
        )
    },
    [pscustomobject]@{
        Name = "NEWS_EVENT_RESEARCH_V1"
        Scope = "news_event_research"
        Fields = @(
            "evidence_quality", "article_body_hash", "available_at",
            "source_publication_time", "security_association", "content_validation",
            "coverage_scope", "reviewer_identity", "provider_usage_permission"
        )
        ExpectedCodes = @(
            "NEWS_ARTICLE_BODY_HASH_MISSING", "NEWS_SOURCE_PUBLICATION_TIME_UNRESOLVED",
            "NEWS_CONTENT_SCOPE_TITLE_LINK_ONLY", "NEWS_ROLLING_WINDOW_COVERAGE_LIMITED"
        )
    }
)

Write-Host "开始多维研究证据资格预审验收" -ForegroundColor Cyan

$beforeEvidence = $null
try {
    $beforeEvidence = Get-ApiData "/research/evidence?page_size=200"
    if ($beforeEvidence.total -gt 200) {
        Add-Failure "证据数量超过单页验收上限，拒绝在不完整样本上宣称通过"
    } else {
        Add-Pass "验收前已读取全部研究证据快照"
    }
} catch {
    Add-Failure "读取验收前证据快照失败：$($_.Exception.Message)"
}

$rejectedCount = 0
foreach ($auditProfile in $profiles) {
    try {
        $audit = Get-AuditData $auditProfile
        if ($audit.requirement_profile -ne $auditProfile.Name -or $audit.research_use_scope -ne $auditProfile.Scope) {
            Add-Failure "$($auditProfile.Name) 未回显显式 Profile 与用途"
            continue
        }
        if ($audit.total -gt 200) {
            Add-Failure "$($auditProfile.Name) 结果超过单页验收上限，拒绝在不完整样本上通过"
            continue
        }
        if (-not $audit.observed_only -or $audit.research_readiness -ne "not_granted" -or $audit.tradable -or $audit.order_created) {
            Add-Failure "$($auditProfile.Name) 错误获得研究或交易授权"
        } else {
            Add-Pass "$($auditProfile.Name) 保持 observed-only 且不可交易"
        }

        $items = @($audit.items)
        $observed = @($items | Where-Object { $_.quality_status -eq "observed" })
        if ($observed.Count -eq 0) {
            Add-Failure "$($auditProfile.Name) 缺少真实 observed 证据"
            continue
        }
        foreach ($item in $items) {
            if ($item.precheck_status -notin @("review_required", "rejected")) {
                Add-Failure "$($auditProfile.Name) 出现非法预审状态：$($item.precheck_status)"
            }
            if ($item.blocking_codes -notcontains "READINESS_GRANT_NOT_IMPLEMENTED") {
                Add-Failure "$($auditProfile.Name) 缺少最终 Research Readiness 授权阻塞"
            }
            if (-not $item.input_fingerprint -or $item.input_fingerprint -notmatch '^[0-9a-f]{64}$') {
                Add-Failure "$($auditProfile.Name) 缺少可复核的输入指纹"
            }
            if (-not $item.authorization_key.evidence_id -or -not $item.authorization_key.available_at) {
                Add-Failure "$($auditProfile.Name) 缺少完整授权键"
            }
            if ($item.precheck_status -eq "rejected") { $rejectedCount++ }
        }
        $sample = $observed | Select-Object -First 1
        foreach ($code in $auditProfile.ExpectedCodes) {
            if ($sample.blocking_codes -notcontains $code) {
                Add-Failure "$($auditProfile.Name) 未报告预期阻塞项：$code"
            }
        }
        Add-Pass "$($auditProfile.Name) 真实 observed 证据均保持非 ready"
    } catch {
        Add-Failure "$($auditProfile.Name) 资格预审接口失败：$($_.Exception.Message)"
    }
}

if ($rejectedCount -eq 0) {
    Add-Failure "未验证任何 rejected 证据的拒绝路径"
} else {
    Add-Pass "已验证 $rejectedCount 条 rejected 证据保持拒绝"
}

if ($null -ne $beforeEvidence -and $beforeEvidence.total -le 200) {
    try {
        $afterEvidence = Get-ApiData "/research/evidence?page_size=200"
        if ($beforeEvidence.total -ne $afterEvidence.total -or (Get-EvidenceSnapshot $beforeEvidence) -ne (Get-EvidenceSnapshot $afterEvidence)) {
            Add-Failure "资格预审错误修改了原始证据快照"
        } else {
            Add-Pass "资格预审未修改原始证据、Hash、可得时间或使用状态"
        }
    } catch {
        Add-Failure "读取验收后证据快照失败：$($_.Exception.Message)"
    }
}

try {
    $execution = Get-ApiData "/trade/execution-status?days=30"
    if (-not $execution.all_release_locks_closed) { Add-Failure "资格预审后存在已开启的发布或交易锁" } else { Add-Pass "六个发布与交易锁仍关闭" }
    if ($execution.order_audit.ai_source -ne 0 -or $execution.order_audit.scheduled_source -ne 0) {
        Add-Failure "检测到 AI 或定时任务来源订单"
    } else { Add-Pass "AI 与定时任务均未创建订单" }
} catch {
    Add-Failure "交易安全状态接口失败：$($_.Exception.Message)"
}

$backendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (Test-Path $backendPython) {
    Invoke-CheckedCommand "后端多维证据资格预审测试" {
        Push-Location (Join-Path $Root "backend")
        try { & $backendPython -m unittest discover -s tests -p "test_research_evidence*.py" } finally { Pop-Location }
    }
} else {
    Add-Failure "缺少后端 Python 环境"
}

Invoke-CheckedCommand "核心只读数据验收" {
    & (Join-Path $Root "scripts\verify_core_readonly_data.ps1") -ApiBaseUrl $ApiBaseUrl
}

if ($failures.Count -eq 0) {
    Write-Host "多维研究证据资格预审验收：PASS" -ForegroundColor Green
    exit 0
}

Write-Host "多维研究证据资格预审验收：FAIL" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
