#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $BackendPython)) {
    throw "缺少后端 Python 环境：$BackendPython"
}

$original = @{}
foreach ($name in @("APP_ENV", "SECRET_KEY", "DATABASE_URL", "REDIS_URL")) {
    $original[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $env:APP_ENV = "development"
    $env:SECRET_KEY = "legacy-api-l3-verification-secret"
    $env:DATABASE_URL = "postgresql+asyncpg://test:test@localhost/test"
    $env:REDIS_URL = "redis://localhost:6379/0"

    Write-Host "开始 L3 数据与研究事实静态契约验收" -ForegroundColor Cyan
    Push-Location $Root
    try {
        & $BackendPython -m unittest `
            backend.tests.test_data_client_contract `
            backend.tests.test_l3_data_service_fail_closed `
            backend.tests.test_l3_fund_flow_schema_compatibility `
            backend.tests.test_l3_announcement_schema_compatibility `
            backend.tests.test_l3_research_current_fact `
            backend.tests.test_l3_stock_list_snapshot `
            backend.tests.test_research_evidence_readiness_audit `
            backend.tests.test_research_evidence_pagination `
            worker.tests.test_data_client_contract `
            worker.tests.test_quote_sync `
            worker.tests.test_research_evidence_sync
        if ($LASTEXITCODE -ne 0) {
            throw "L3 定向契约测试失败，退出码 $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    & (Join-Path $Root "scripts\verify_legacy_api_l0.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "L0 路由账本回归失败，退出码 $LASTEXITCODE"
    }
} finally {
    foreach ($name in $original.Keys) {
        [Environment]::SetEnvironmentVariable($name, $original[$name], "Process")
    }
}

Write-Host "L3 静态契约验收：PASS；受控抓取、数据库迁移和前端依赖恢复后验收仍待执行" -ForegroundColor Yellow
