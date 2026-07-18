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

Write-Host "开始核心只读数据验收" -ForegroundColor Cyan

try {
    $execution = Get-ApiData "/trade/execution-status?days=30"
    if (-not $execution.all_release_locks_closed) { Add-Failure "存在已开启的发布或交易锁" } else { Add-Pass "六个发布与交易锁均关闭" }
    if ($execution.order_audit.ai_source -ne 0) { Add-Failure "检测到 AI 来源订单" } else { Add-Pass "AI 来源订单为 0" }
    if ($execution.order_audit.scheduled_source -ne 0) { Add-Failure "检测到定时任务来源订单" } else { Add-Pass "定时任务来源订单为 0" }
} catch { Add-Failure "交易执行状态接口：$($_.Exception.Message)" }

try {
    $market = Get-ApiData "/stock/market/status"
    if (-not $market.source) { Add-Failure "行情状态缺少来源说明" } else { Add-Pass "行情状态包含来源和降级说明" }
    if ($market.provider_metadata_status -notin @("recorded", "not_recorded")) { Add-Failure "行情 Provider 元数据状态不明确" }
} catch { Add-Failure "行情状态接口：$($_.Exception.Message)" }

try {
    $readiness = Get-ApiData "/research/readiness"
    if ($null -eq $readiness.summary.ready -or -not $readiness.source_version) { Add-Failure "Readiness 汇总不完整" } else { Add-Pass "Readiness 字段级汇总可用" }
} catch { Add-Failure "Research Readiness 接口：$($_.Exception.Message)" }

try {
    $candidates = Get-ApiData "/research/candidate-status?limit=5"
    if ($candidates.tradable -or $candidates.order_created) { Add-Failure "研究候选错误获得交易或订单权限" } else { Add-Pass "研究候选保持不可交易且未创建订单" }
    if ($candidates.candidate_status -ne "release_locked") { Add-Failure "候选发布锁状态异常" }
} catch { Add-Failure "研究候选状态接口：$($_.Exception.Message)" }

try {
    $backtest = Get-ApiData "/backtest/validation-summary"
    if ($backtest.public_execution_enabled) { Add-Failure "公共回测执行被开启" } else { Add-Pass "公共回测执行保持关闭" }
    if ($backtest.latest_persisted_result -and $backtest.latest_persisted_result.validation_status -notin @("validated", "blocked")) {
        Add-Failure "历史回测验证状态不明确"
    }
} catch { Add-Failure "回测验证汇总接口：$($_.Exception.Message)" }

try {
    $strategy = Get-ApiData "/strategy/runtime-status"
    if (-not $strategy.config_hash -or -not $strategy.catalog_version) { Add-Failure "策略运行配置缺少版本或 Hash" } else { Add-Pass "策略配置版本和 Hash 可追踪" }
} catch { Add-Failure "策略运行状态接口：$($_.Exception.Message)" }

try {
    $equity = Get-ApiData "/portfolio/equity-curve?mode=simulation&days=30"
    if (-not $equity.source_version) { Add-Failure "资产曲线缺少来源版本" } else { Add-Pass "资产曲线来源可追踪" }
} catch { Add-Failure "资产曲线接口：$($_.Exception.Message)" }

try {
    $ai = Get-ApiData "/ai/audit-summary"
    if ($ai.ai_order_count -ne 0 -or $ai.order_created) { Add-Failure "AI 审计发现已创建订单" } else { Add-Pass "AI 创建订单数为 0" }
} catch { Add-Failure "AI 审计接口：$($_.Exception.Message)" }

$backendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPython)) {
    Add-Failure "缺少后端 Python 环境"
} else {
    Invoke-CheckedCommand "Backend 只读契约测试" {
        Push-Location (Join-Path $Root "backend")
        try { & $backendPython -m pytest tests -q } finally { Pop-Location }
    }
}

Invoke-CheckedCommand "Frontend 只读契约测试" {
    Push-Location (Join-Path $Root "frontend")
    try { & npm run test:contracts } finally { Pop-Location }
}

Invoke-CheckedCommand "Frontend TypeScript 检查" {
    Push-Location (Join-Path $Root "frontend")
    try { & npm run typecheck } finally { Pop-Location }
}

Invoke-CheckedCommand "Frontend 构建" {
    Push-Location (Join-Path $Root "frontend")
    try { & npm run build } finally { Pop-Location }
}

if ($failures.Count -eq 0) {
    Write-Host "核心只读数据验收：PASS" -ForegroundColor Green
    exit 0
}

Write-Host "核心只读数据验收：FAIL" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
exit 1
