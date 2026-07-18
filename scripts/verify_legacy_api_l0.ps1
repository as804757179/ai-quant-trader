#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
$DataPython = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"
$LedgerPath = Join-Path $Root "docs\api\legacy-api-ledger.json"

if (-not (Test-Path $BackendPython)) {
    throw "缺少后端 Python 环境：$BackendPython"
}
if (-not (Test-Path $DataPython)) {
    throw "缺少数据服务 Python 环境：$DataPython"
}
if (-not (Test-Path $LedgerPath)) {
    throw "缺少旧接口账本：$LedgerPath"
}

$ledger = Get-Content -LiteralPath $LedgerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$originalSecretKey = $env:SECRET_KEY
$originalDatabaseUrl = $env:DATABASE_URL
$originalRedisUrl = $env:REDIS_URL

function Get-OpenApiHash([string]$Python, [string]$WorkingDirectory, [string]$ImportCode) {
    Push-Location $WorkingDirectory
    try {
        $hash = & $Python -c $ImportCode
        if ($LASTEXITCODE -ne 0) {
            throw "OpenAPI Hash 计算失败，退出码 $LASTEXITCODE"
        }
        return ($hash | Select-Object -Last 1).Trim()
    } finally {
        Pop-Location
    }
}

try {
    $env:SECRET_KEY = "legacy-api-l0-test"
    $env:DATABASE_URL = "postgresql+asyncpg://test:test@localhost/test"
    $env:REDIS_URL = "redis://localhost:6379/0"

    Write-Host "开始 L0 旧接口账本验收" -ForegroundColor Cyan

    Push-Location (Join-Path $Root "backend")
    try {
        & $BackendPython -m unittest discover -s tests -p "test_legacy_api_inventory.py"
        if ($LASTEXITCODE -ne 0) {
            throw "旧接口账本测试失败，退出码 $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    $backendCode = @'
import hashlib
import json
from app.main import app

payload = json.dumps(
    app.openapi(),
    ensure_ascii=False,
    sort_keys=True,
    separators=(',', ':'),
).encode('utf-8')
print(hashlib.sha256(payload).hexdigest())
'@
    $dataCode = @'
import hashlib
import json
from main import app

payload = json.dumps(
    app.openapi(),
    ensure_ascii=False,
    sort_keys=True,
    separators=(',', ':'),
).encode('utf-8')
print(hashlib.sha256(payload).hexdigest())
'@

    $backendHash = Get-OpenApiHash $BackendPython (Join-Path $Root "backend") $backendCode
    if ($backendHash -ne $ledger.openapi_baselines.main_http.sha256) {
        throw "主应用 OpenAPI 快照漂移：$backendHash"
    }

    $dataHash = Get-OpenApiHash $DataPython (Join-Path $Root "a-stock-data\service") $dataCode
    if ($dataHash -ne $ledger.openapi_baselines.internal_data_http.sha256) {
        throw "内部数据服务 OpenAPI 快照漂移：$dataHash"
    }
} finally {
    $env:SECRET_KEY = $originalSecretKey
    $env:DATABASE_URL = $originalDatabaseUrl
    $env:REDIS_URL = $originalRedisUrl
}

Write-Host "L0 旧接口账本验收：PASS" -ForegroundColor Green
