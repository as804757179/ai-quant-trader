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
foreach ($name in @("APP_ENV", "SECRET_KEY", "DATABASE_URL", "REDIS_URL", "WS_REDIS_ENABLED")) {
    $original[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $env:APP_ENV = "development"
    $env:SECRET_KEY = "legacy-api-l2-verification-secret"
    $env:DATABASE_URL = "postgresql+asyncpg://test:test@localhost/test"
    $env:REDIS_URL = "redis://localhost:6379/0"
    $env:WS_REDIS_ENABLED = "false"

    Write-Host "开始 L2 交易、风险与审批静态契约验收" -ForegroundColor Cyan
    Push-Location (Join-Path $Root "backend")
    try {
        & $BackendPython -m py_compile `
            app\api\trade.py `
            app\api\risk.py `
            app\risk\rule_snapshot.py `
            app\services\trade_service.py `
            app\trade\execution_authorization.py `
            app\trade\order_manager.py `
            app\risk\fuse.py `
            alembic\versions\029_execution_approval_policy_version.py `
            alembic\versions\030_order_intent_idempotency_window.py
        if ($LASTEXITCODE -ne 0) {
            throw "L2 Python 编译检查失败，退出码 $LASTEXITCODE"
        }

        & $BackendPython -m unittest `
            tests.test_l2_execution_safety_contracts `
            tests.test_l2_execution_data_authorization `
            tests.test_l2_execution_snapshot `
            tests.test_l2_fuse_fail_closed `
            tests.test_l2_order_intent_idempotency `
            tests.test_l2_operation_approval_contracts `
            tests.test_l2_risk_rule_snapshot `
            tests.test_l1_http_contracts `
            tests.test_legacy_api_inventory
        if ($LASTEXITCODE -ne 0) {
            throw "L2 后端契约测试失败，退出码 $LASTEXITCODE"
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

Write-Host "L2 静态契约验收：PASS；数据库迁移与受控运行时验收待 Docker 可用后执行" -ForegroundColor Yellow
