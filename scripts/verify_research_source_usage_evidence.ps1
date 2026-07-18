#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api/v1",
    [string]$EnvFile = ".env.host"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = "1"
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

function Get-EvidenceSnapshot($EvidenceData) {
    $rows = foreach ($item in $EvidenceData.items) {
        "$($item.evidence_id)|$($item.raw_hash)|$($item.available_at)|$($item.usage_status)"
    }
    return [string]::Join("`n", @($rows | Sort-Object))
}

function Import-EnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { throw "缺少环境文件：$Path" }
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        $index = $line.IndexOf("=")
        if ($line -and -not $line.StartsWith("#") -and $index -gt 0) {
            Set-Item -Path "Env:$($line.Substring(0, $index).Trim())" -Value $line.Substring($index + 1).Trim()
        }
    }
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

Write-Host "开始研究来源条款证据与许可预审验收" -ForegroundColor Cyan

$beforeEvidence = $null
try {
    $beforeEvidence = Get-ApiData "/research/evidence?page_size=200"
    if ($beforeEvidence.total -ne 27) {
        Add-Failure "原始研究证据数量不是已确认基线 27：$($beforeEvidence.total)"
    } else {
        Add-Pass "已读取 27 条原始研究证据基线"
    }
} catch {
    Add-Failure "读取原始研究证据基线失败：$($_.Exception.Message)"
}

try {
    $sourceData = Get-ApiData "/research/source-usage-evidence"
    $items = @($sourceData.items)
    $terms = @($items | ForEach-Object { @($_.terms_evidence) })
    $reviews = @($items | ForEach-Object { @($_.review_history) })
    $expectedKeys = @(
        "cninfo/cninfo_listed_company_disclosure",
        "gdelt/gdelt_article_list_rss"
    )
    $actualKeys = @($items | ForEach-Object { "$($_.provider)/$($_.source)" } | Sort-Object)
    if (($actualKeys -join "|") -ne (($expectedKeys | Sort-Object) -join "|")) {
        Add-Failure "来源键未严格限制为两个固定来源"
    } else {
        Add-Pass "来源键严格限制为 CNINFO 与 GDELT 两个固定来源"
    }
    if ($terms.Count -ne 4) {
        Add-Failure "真实条款证据数量不是 4：$($terms.Count)"
    } elseif (@($terms | Where-Object { $_.status -ne "observed" }).Count -ne 0) {
        Add-Failure "存在非 observed 的首期条款证据"
    } elseif (@($terms | Where-Object { $_.raw_hash -notmatch '^[0-9a-f]{64}$' -or $_.document_bytes -le 0 }).Count -ne 0) {
        Add-Failure "条款证据缺少原始响应 Hash 或字节数"
    } else {
        Add-Pass "4 条官方页面均有原始响应 Hash、字节数与获取时间"
    }
    if ($reviews.Count -ne 10) {
        Add-Failure "真实许可预审数量不是 10：$($reviews.Count)"
    } elseif (@($reviews | Where-Object { $_.decision_status -ne "review_required" }).Count -ne 0) {
        Add-Failure "首期预审出现 review_required 以外的状态"
    } elseif (@($reviews | Where-Object { $_.identity_assurance -ne "unverified" }).Count -ne 0) {
        Add-Failure "首期预审出现已认证身份"
    } else {
        Add-Pass "10 条预审均为 review_required 且身份未认证"
    }
    foreach ($item in $items) {
        $latestScopes = @($item.latest_reviews.PSObject.Properties.Name | Sort-Object)
        $expectedScopes = @(
            "automated_fetch", "derived_research", "local_storage",
            "manual_observation", "redistribution"
        ) | Sort-Object
        if (($latestScopes -join "|") -ne ($expectedScopes -join "|")) {
            Add-Failure "$($item.provider)/$($item.source) 缺少五类最新预审"
        }
    }
    if ($sourceData.authorization_granted -or $sourceData.research_readiness -ne "not_granted") {
        Add-Failure "来源证据接口错误授予许可或 Research Readiness"
    } else {
        Add-Pass "来源证据接口保持 authorization_granted=false 与 not_granted"
    }
} catch {
    Add-Failure "来源条款证据接口验收失败：$($_.Exception.Message)"
}

$backendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
try {
    Import-EnvFile (Join-Path $Root $EnvFile)
    $databaseValidation = @'
import os
import uuid
import psycopg2

url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
connection = psycopg2.connect(url)
cursor = connection.cursor()
cursor.execute("SELECT count(*) FROM market.research_source_terms_evidence")
terms_before = cursor.fetchone()[0]
cursor.execute("SELECT count(*) FROM market.research_source_usage_reviews")
reviews_before = cursor.fetchone()[0]

first_id = str(uuid.uuid4())
second_id = str(uuid.uuid4())
base_values = (
    "gdelt", "gdelt_article_list_rss",
    "gdelt:storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss:metadata-only",
    "terms_of_use", "https://www.gdeltproject.org/about.html",
)
insert_sql = """
INSERT INTO market.research_source_terms_evidence (
    terms_evidence_id, provider, source, source_scope, document_kind, terms_url,
    retrieved_at, source_time_precision, raw_hash, document_bytes, content_type,
    status, collector_version
) VALUES (%s, %s, %s, %s, %s, %s, NOW(), 'unresolved', %s, 1,
          'text/html', 'observed', 'sprint14.8-acceptance-v1')
"""
cursor.execute(insert_sql, (first_id, *base_values, "b" * 64))
cursor.execute(insert_sql, (second_id, *base_values, "c" * 64))
cursor.execute(
    "SELECT count(*) FROM market.research_source_terms_evidence WHERE terms_evidence_id IN (%s, %s)",
    (first_id, second_id),
)
assert cursor.fetchone()[0] == 2
print("PASS  新 Hash 追加新版本，旧版本同时保留")

review_id = str(uuid.uuid4())
cursor.execute(
    """INSERT INTO market.research_source_usage_reviews
       (review_id, terms_evidence_id, usage_scope, decision_status, reason,
        reviewer_label, policy_version)
       VALUES (%s, %s, 'automated_fetch', 'review_required',
               '验收事务', 'sprint14.8-acceptance', 'source-usage-pre-review-v1')""",
    (review_id, first_id),
)

def expect_rejected(name, sql, params=()):
    cursor.execute("SAVEPOINT acceptance_case")
    try:
        cursor.execute(sql, params)
    except psycopg2.Error:
        cursor.execute("ROLLBACK TO SAVEPOINT acceptance_case")
        cursor.execute("RELEASE SAVEPOINT acceptance_case")
        print(f"PASS  {name}")
        return
    cursor.execute("ROLLBACK TO SAVEPOINT acceptance_case")
    cursor.execute("RELEASE SAVEPOINT acceptance_case")
    raise AssertionError(f"未拒绝：{name}")

expect_rejected(
    "approved 被数据库拒绝",
    """INSERT INTO market.research_source_usage_reviews
       (review_id, terms_evidence_id, usage_scope, decision_status, reason,
        reviewer_label, policy_version)
       VALUES (%s, %s, 'automated_fetch', 'approved', '非法批准', 'test', 'v1')""",
    (str(uuid.uuid4()), first_id),
)
expect_rejected(
    "非官方 URL 被数据库拒绝",
    """INSERT INTO market.research_source_terms_evidence
       (terms_evidence_id, provider, source, source_scope, document_kind,
        terms_url, source_time_precision, status, failure_reason, collector_version)
       VALUES (%s, 'gdelt', 'gdelt_article_list_rss',
        'gdelt:storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss:metadata-only',
        'other_official', 'https://example.com/terms', 'unresolved',
        'discovery_unresolved', '非法 URL', 'v1')""",
    (str(uuid.uuid4()),),
)
expect_rejected(
    "空失败原因被数据库拒绝",
    """INSERT INTO market.research_source_terms_evidence
       (terms_evidence_id, provider, source, source_scope, document_kind,
        terms_url, source_time_precision, status, failure_reason, collector_version)
       VALUES (%s, 'gdelt', 'gdelt_article_list_rss',
        'gdelt:storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss:metadata-only',
        'terms_of_use', 'https://www.gdeltproject.org/about.html', 'unresolved',
        'fetch_failed', '', 'v1')""",
    (str(uuid.uuid4()),),
)
expect_rejected(
    "条款证据更新被数据库拒绝",
    "UPDATE market.research_source_terms_evidence SET collector_version='changed' WHERE terms_evidence_id=%s",
    (first_id,),
)
expect_rejected(
    "预审删除被数据库拒绝",
    "DELETE FROM market.research_source_usage_reviews WHERE review_id=%s",
    (review_id,),
)

connection.rollback()
cursor.execute("SELECT count(*) FROM market.research_source_terms_evidence")
assert cursor.fetchone()[0] == terms_before
cursor.execute("SELECT count(*) FROM market.research_source_usage_reviews")
assert cursor.fetchone()[0] == reviews_before
print("PASS  验收事务已回滚，真实审计记录未增加")
cursor.close()
connection.close()
'@
    $databaseValidation | & $backendPython -
    if ($LASTEXITCODE -ne 0) { Add-Failure "数据库追加与拒绝路径验收失败" } else { Add-Pass "数据库追加与拒绝路径验收" }
} catch {
    Add-Failure "数据库追加与拒绝路径验收异常：$($_.Exception.Message)"
}

Invoke-CheckedCommand "来源条款证据定向测试" {
    Push-Location (Join-Path $Root "backend")
    try { & $backendPython -m unittest tests/test_research_source_usage_evidence.py } finally { Pop-Location }
}

Invoke-CheckedCommand "多维证据与核心只读安全回归" {
    & (Join-Path $Root "scripts\verify_research_evidence_readiness_audit.ps1") -ApiBaseUrl $ApiBaseUrl
}

if ($null -ne $beforeEvidence) {
    try {
        $afterEvidence = Get-ApiData "/research/evidence?page_size=200"
        if ($beforeEvidence.total -ne $afterEvidence.total -or (Get-EvidenceSnapshot $beforeEvidence) -ne (Get-EvidenceSnapshot $afterEvidence)) {
            Add-Failure "Sprint14.8 验收修改了原始证据快照"
        } else {
            Add-Pass "27 条原始证据的 ID、Hash、可得时间和 usage_status 均未变化"
        }
    } catch {
        Add-Failure "读取验收后原始证据快照失败：$($_.Exception.Message)"
    }
}

if ($failures.Count -eq 0) {
    Write-Host "研究来源条款证据与许可预审验收：PASS" -ForegroundColor Green
    exit 0
}

Write-Host "研究来源条款证据与许可预审验收：FAIL" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
