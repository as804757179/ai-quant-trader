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
    $response = Invoke-RestMethod -Uri "$ApiBaseUrl$Path" -TimeoutSec 20
    if (-not $response.success) { throw "接口未返回 success=true：$Path" }
    return $response.data
}

function Import-EnvFile([string]$Path) {
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        $index = $line.IndexOf("=")
        if ($line -and -not $line.StartsWith("#") -and $index -gt 0) {
            Set-Item -Path "Env:$($line.Substring(0, $index).Trim())" -Value $line.Substring($index + 1).Trim()
        }
    }
}

Write-Host "开始 Sprint14.9 财报快照与页级定位验收" -ForegroundColor Cyan

$expected = @{
    "cef779d8-96d7-4a01-8ae3-2b9a023447e0" = @{ Hash="2273565ecbe1b32536631fd4a019a4f4a990f4c793cfd5b70eae90d44d3ff16c"; Bytes=1975076; Pages=288; TextPages=288; Status="success"; Locations=167 }
    "522d97a3-ff33-4001-81da-6575cd4ad8e3" = @{ Hash="e4d1cff0461c0ef24d26551ca68e31ad323a1b3eadd8a3c03f00feada364de22"; Bytes=36054699; Pages=454; TextPages=452; Status="partial"; Locations=195 }
}

try {
    $evidence = Get-ApiData "/research/evidence?page_size=200"
    if ($evidence.total -ne 27) { Add-Failure "原始证据数量不是 27：$($evidence.total)" }
    else { Add-Pass "原始证据数量保持 27" }
    foreach ($evidenceId in $expected.Keys) {
        $item = @($evidence.items | Where-Object { $_.evidence_id -eq $evidenceId })
        if ($item.Count -ne 1) { Add-Failure "$evidenceId 未唯一返回"; continue }
        $sidecar = $item[0].financial_report_snapshot_location
        $run = $sidecar.parse_run
        $want = $expected[$evidenceId]
        if ($sidecar.snapshot_status -ne "observed" -or $sidecar.expected_raw_hash -ne $want.Hash -or
            $sidecar.observed_raw_hash -ne $want.Hash -or $sidecar.observed_bytes -ne $want.Bytes) {
            Add-Failure "$evidenceId 快照 Hash/字节/API 状态不一致"
            continue
        }
        if ($run.status -ne $want.Status -or $run.page_count -ne $want.Pages -or
            $run.text_page_count -ne $want.TextPages -or @($run.locations).Count -ne $want.Locations) {
            Add-Failure "$evidenceId 解析或定位计数不一致"
            continue
        }
        $path = Join-Path $env:LOCALAPPDATA "AIQuantTrader\evidence\financial_reports\cninfo\$($sidecar.storage_key)"
        if (-not (Test-Path -LiteralPath $path)) { Add-Failure "$evidenceId 本地 PDF 缺失"; continue }
        $file = Get-Item -LiteralPath $path
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($file.Length -ne $want.Bytes -or $hash -ne $want.Hash) { Add-Failure "$evidenceId 本地 PDF 验真失败" }
        else { Add-Pass "$evidenceId 快照、页级证据和定位旁路一致" }
    }
    if ($evidence.research_readiness -ne "not_granted" -or $evidence.tradable -or $evidence.order_created) {
        Add-Failure "证据接口错误授予研究或交易权限"
    } else { Add-Pass "证据接口保持只读且 Research Readiness 未授予" }
} catch { Add-Failure "财报证据接口验收失败：$($_.Exception.Message)" }

try {
    $execution = Get-ApiData "/trade/execution-status"
    if (-not $execution.all_release_locks_closed -or $execution.ai_direct_order_allowed -or
        @($execution.release_locks | Where-Object { $_.enabled }).Count -ne 0) {
        Add-Failure "发布锁或 AI 下单边界被打开"
    } else { Add-Pass "六个发布锁关闭且 AI 不可直接下单" }
} catch { Add-Failure "交易安全状态验收失败：$($_.Exception.Message)" }

try {
    Import-EnvFile (Join-Path $Root $EnvFile)
    $python = Join-Path $Root "backend\.venv\Scripts\python.exe"
    $validation = @'
import os
import psycopg2

url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
connection = psycopg2.connect(url)
cursor = connection.cursor()
cursor.execute("SELECT snapshot_id FROM market.research_financial_report_snapshots WHERE status='observed' ORDER BY created_at LIMIT 1")
snapshot_id = cursor.fetchone()[0]

def reject(name, sql, params=()):
    cursor.execute("SAVEPOINT sprint149_case")
    try:
        cursor.execute(sql, params)
    except psycopg2.Error:
        cursor.execute("ROLLBACK TO SAVEPOINT sprint149_case")
        cursor.execute("RELEASE SAVEPOINT sprint149_case")
        print(f"PASS  {name}")
        return
    cursor.execute("ROLLBACK TO SAVEPOINT sprint149_case")
    cursor.execute("RELEASE SAVEPOINT sprint149_case")
    raise AssertionError(f"未拒绝：{name}")

reject("快照更新被数据库拒绝", "UPDATE market.research_financial_report_snapshots SET collector_version='changed' WHERE snapshot_id=%s", (snapshot_id,))
reject("快照删除被数据库拒绝", "DELETE FROM market.research_financial_report_snapshots WHERE snapshot_id=%s", (snapshot_id,))
cursor.execute("SELECT count(*) FROM market.research_financial_report_snapshots WHERE status='observed'")
assert cursor.fetchone()[0] == 2
connection.rollback()
connection.close()
'@
    $validation | & $python -
    if ($LASTEXITCODE -ne 0) { Add-Failure "数据库不可变约束验收失败" }
    else { Add-Pass "数据库不可变约束验收事务已回滚" }
} catch { Add-Failure "数据库验收失败：$($_.Exception.Message)" }

if ($failures.Count -gt 0) {
    Write-Host "Sprint14.9 验收失败：$($failures.Count) 项" -ForegroundColor Red
    exit 1
}
Write-Host "Sprint14.9 验收通过" -ForegroundColor Green
