#Requires -Version 5.1
[CmdletBinding()]
param([switch]$StaticOnly)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
$LedgerPath = Join-Path $Root "docs\api\legacy-api-ledger.json"
$runtimeAttempted = $false

function Invoke-RequiredScript([string]$Name) {
    & (Join-Path $Root "scripts\$Name")
    if ($LASTEXITCODE -ne 0) {
        throw "$Name 失败，退出码 $LASTEXITCODE"
    }
}

function Invoke-BackendTests([string]$Label, [string[]]$Tests) {
    Push-Location (Join-Path $Root "backend")
    try {
        & $BackendPython -m unittest @Tests
        if ($LASTEXITCODE -ne 0) {
            throw "$Label 失败，退出码 $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Test-LedgerClearance {
    if (-not (Test-Path $LedgerPath)) {
        throw "缺少旧接口账本：$LedgerPath"
    }
    $ledger = Get-Content -LiteralPath $LedgerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $entries = foreach ($scope in $ledger.scopes.PSObject.Properties) {
        foreach ($api in $scope.Value.interfaces) {
            $api
        }
    }
    $knownIssues = @(
        $entries | Where-Object { @($_.known_issues).Count -gt 0 }
    )
    $unknownConsumers = @(
        $entries | Where-Object { $_.consumer_state -eq "external_unknown" }
    )
    $reviewRoutes = @(
        $entries | Where-Object { $_.lifecycle -eq "review" }
    )
    $routeOnly = @(
        $entries | Where-Object { $_.verification -eq "route_only" }
    )
    if (
        $knownIssues.Count -gt 0 -or
        $unknownConsumers.Count -gt 0 -or
        $reviewRoutes.Count -gt 0 -or
        $routeOnly.Count -gt 0
    ) {
        throw (
            "旧接口账本尚未清零：" +
            "known_issues=$($knownIssues.Count)，" +
            "external_unknown=$($unknownConsumers.Count)，" +
            "review=$($reviewRoutes.Count)，" +
            "route_only=$($routeOnly.Count)"
        )
    }
}

function Invoke-FrontendChecks {
    Push-Location (Join-Path $Root "frontend")
    try {
        npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw "前端 typecheck 失败，退出码 $LASTEXITCODE" }
        node --test tests\readOnlyApiCore.test.mjs tests\apiClientContract.test.mjs tests\appShellSafety.test.mjs
        if ($LASTEXITCODE -ne 0) { throw "前端契约测试失败，退出码 $LASTEXITCODE" }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "前端生产构建失败，退出码 $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
}

function Test-PostStopRuntimeState {
    foreach ($port in @(3000, 8000, 8080)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "停止后端口仍在监听：$port"
        }
    }
    $runtimeRoot = Join-Path $env:LOCALAPPDATA "AIQuantTrader\run"
    foreach ($name in @("local-services.json", "watchdog-status.json")) {
        if (Test-Path (Join-Path $runtimeRoot $name)) {
            throw "停止后运行状态未清理：$name"
        }
    }
}

if (-not (Test-Path $BackendPython)) {
    throw "缺少后端 Python 环境：$BackendPython"
}

$original = @{}
foreach ($name in @("APP_ENV", "SECRET_KEY", "DATABASE_URL", "REDIS_URL", "WS_REDIS_ENABLED")) {
    $original[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    & (Join-Path $Root "scripts\doctor.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "运行环境诊断失败，退出码 $LASTEXITCODE"
    }

    Invoke-RequiredScript "verify_legacy_api_l0.ps1"
    Invoke-RequiredScript "verify_legacy_api_l1.ps1"
    Invoke-RequiredScript "verify_legacy_api_l2.ps1"
    Invoke-RequiredScript "verify_legacy_api_l3.ps1"
    Invoke-RequiredScript "verify_legacy_api_l4.ps1"

    $env:APP_ENV = "development"
    $env:SECRET_KEY = "legacy-api-clearance-verification-secret"
    $env:DATABASE_URL = "postgresql+asyncpg://test:test@localhost/test"
    $env:REDIS_URL = "redis://localhost:6379/0"
    $env:WS_REDIS_ENABLED = "false"
    Invoke-BackendTests "L5 领域一致性测试" @(
        "tests.test_l5_ai_context_gate",
        "tests.test_l5_ai_fail_closed",
        "tests.test_l5_durable_risk_alerts",
        "tests.test_l5_order_fill_semantics",
        "tests.test_l5_portfolio_read_only",
        "tests.test_l5_risk_precheck_dry_run",
        "tests.test_l5_strategy_fail_closed",
        "tests.test_l5_strategy_version_governance",
        "tests.test_l5_valuation_semantics"
    )
    Invoke-BackendTests "L6-L7 契约测试" @(
        "tests.test_legacy_order_pagination",
        "tests.test_research_evidence_pagination",
        "tests.test_research_evidence_contracts",
        "tests.test_realtime_quote_provenance_contracts",
        "tests.test_l7_deprecation_telemetry"
    )
    Invoke-FrontendChecks
    Test-LedgerClearance

    if ($StaticOnly) {
        throw "静态预检完成，但 -StaticOnly 未执行真实运行时验收；LEGACY_API_CLEARANCE=BLOCKED"
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "未找到 Docker，无法执行真实运行时验收"
    }
    & docker version --format "{{.Server.Version}}" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 服务不可用，无法执行真实运行时验收"
    }

    $runtimeAttempted = $true
    & (Join-Path $Root "scripts\start-local.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "受控启动失败，退出码 $LASTEXITCODE"
    }
    & (Join-Path $Root "scripts\verify_local_env.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "受控运行环境验收失败，退出码 $LASTEXITCODE"
    }
    & (Join-Path $Root "scripts\doctor.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "运行中 Watchdog/资源诊断失败，退出码 $LASTEXITCODE"
    }

    & (Join-Path $Root "scripts\stop-local.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "受控停止失败，退出码 $LASTEXITCODE"
    }
    $runtimeAttempted = $false
    Test-PostStopRuntimeState
    Write-Host "LEGACY_API_CLEARANCE=PASS" -ForegroundColor Green
} catch {
    Write-Host "LEGACY_API_CLEARANCE=BLOCKED：$($_.Exception.Message)" -ForegroundColor Yellow
    exit 1
} finally {
    if ($runtimeAttempted) {
        & (Join-Path $Root "scripts\stop-local.ps1") -Quiet
    }
    foreach ($name in $original.Keys) {
        [Environment]::SetEnvironmentVariable($name, $original[$name], "Process")
    }
}

