#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
$DataPython = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"
$ClientPath = Join-Path $Root "frontend\src\api\client.ts"

if (-not (Test-Path $BackendPython)) {
    throw "缺少后端 Python 环境：$BackendPython"
}
if (-not (Test-Path $DataPython)) {
    throw "缺少内部数据服务 Python 环境：$DataPython"
}
if (-not (Test-Path $ClientPath)) {
    throw "缺少前端 API 客户端：$ClientPath"
}

$original = @{}
foreach ($name in @(
    "APP_ENV", "SECRET_KEY", "DATABASE_URL", "REDIS_URL",
    "API_ALLOW_ANONYMOUS_READS", "API_LEGACY_KEY_MIGRATION_ENABLED",
    "WS_REDIS_ENABLED"
)) {
    $original[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $env:APP_ENV = "development"
    $env:SECRET_KEY = "legacy-api-l1-verification-secret"
    $env:DATABASE_URL = "postgresql+asyncpg://test:test@localhost/test"
    $env:REDIS_URL = "redis://localhost:6379/0"
    $env:API_ALLOW_ANONYMOUS_READS = "true"
    $env:API_LEGACY_KEY_MIGRATION_ENABLED = "false"
    $env:WS_REDIS_ENABLED = "false"

    $httpxVersion = (& $BackendPython -c "import httpx; print(httpx.__version__)").Trim()
    if ($httpxVersion -ne "0.26.0") {
        throw "后端 httpx 未恢复到锁定版本 0.26.0，当前为：$httpxVersion"
    }

    Write-Host "开始 L1 身份、权限与契约验收" -ForegroundColor Cyan
    & $DataPython -m unittest discover -s (Join-Path $Root "a-stock-data\tests") -p "test_health_contract.py"
    if ($LASTEXITCODE -ne 0) {
        throw "L1 内部数据服务健康契约测试失败，退出码 $LASTEXITCODE"
    }
    Push-Location (Join-Path $Root "backend")
    try {
        & $BackendPython -m unittest `
            tests.test_l1_api_security_contracts `
            tests.test_l1_http_contracts `
            tests.test_l1_worker_credential_contract `
            tests.test_l1_ws_security_contracts `
            tests.test_l1_ws_integration `
            tests.test_l1_migration_contract `
            tests.test_legacy_api_inventory
        if ($LASTEXITCODE -ne 0) {
            throw "L1 后端契约测试失败，退出码 $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    if (Select-String -LiteralPath $ClientPath -Pattern "VITE_API_KEY" -Quiet) {
        throw "前端 API 客户端仍包含 VITE_API_KEY"
    }
    if (-not (Select-String -LiteralPath $ClientPath -Pattern "withCredentials: true" -Quiet)) {
        throw "前端 API 客户端未启用浏览器会话凭据"
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

Write-Host "L1 身份、权限与契约验收：PASS" -ForegroundColor Green
