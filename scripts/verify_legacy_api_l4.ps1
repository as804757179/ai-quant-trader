#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
$DataPython = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"

if (-not (Test-Path $BackendPython)) {
    throw "缺少后端 Python 环境：$BackendPython"
}
if (-not (Test-Path $DataPython)) {
    throw "缺少数据服务 Python 环境：$DataPython"
}

$original = @{}
foreach ($name in @("APP_ENV", "SECRET_KEY", "DATABASE_URL", "REDIS_URL")) {
    $original[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $env:APP_ENV = "development"
    $env:SECRET_KEY = "legacy-api-l4-verification-secret"
    $env:DATABASE_URL = "postgresql+asyncpg://test:test@localhost/test"
    $env:REDIS_URL = "redis://localhost:6379/0"

    Write-Host "开始 L4 异步 Job 与可信回测静态契约验收" -ForegroundColor Cyan
    Push-Location (Join-Path $Root "backend")
    try {
        & $BackendPython -m py_compile `
            app\api\backtest.py `
            app\api\stock.py `
            app\api\ai.py `
            app\api\trade.py `
            app\api\jobs.py `
            app\backtest\jobs.py `
            app\backtest\service.py `
            app\jobs\service.py `
            app\jobs\dispatch.py `
            app\jobs\operations.py `
            app\core\auth.py `
            alembic\versions\027_async_job_backtest_governance.py `
            alembic\versions\031_operation_job_results.py `
            alembic\versions\032_operation_job_recovery.py `
            alembic\versions\033_operation_job_approval_binding.py `
            alembic\versions\034_operation_log_provisioning_compatibility.py `
            alembic\versions\035_operation_log_auth_compatibility.py `
            alembic\versions\036_async_job_attempt_diagnostics.py `
            ..\worker\tasks\jobs.py `
            ..\worker\celery_app.py
        if ($LASTEXITCODE -ne 0) {
            throw "L4 Python 编译检查失败，退出码 $LASTEXITCODE"
        }

        & $BackendPython -m unittest `
            tests.test_l4_async_job_contracts `
            tests.test_l4_operation_job_contracts `
            tests.test_l1_http_contracts `
            tests.test_l2_execution_safety_contracts
        if ($LASTEXITCODE -ne 0) {
            throw "L4 后端契约回归失败，退出码 $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    Push-Location (Join-Path $Root "a-stock-data\service")
    try {
        & $DataPython -m py_compile main.py providers.py
        if ($LASTEXITCODE -ne 0) {
            throw "L4 数据服务编译检查失败，退出码 $LASTEXITCODE"
        }
        & $DataPython -m unittest discover -s ..\tests -p "test_stock_list_snapshot.py"
        if ($LASTEXITCODE -ne 0) {
            throw "L4 数据服务快照契约失败，退出码 $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $original.Keys) {
        [Environment]::SetEnvironmentVariable($name, $original[$name], "Process")
    }
}

Write-Host "L4 静态契约验收：PASS；数据库迁移、服务凭据配置和受控 Worker 运行时验收仍待执行" -ForegroundColor Yellow
