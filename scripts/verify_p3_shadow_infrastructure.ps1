param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot "backend"

Push-Location $backendPath
try {
    Write-Output "开始 P3-0 通用基础设施定向验收"
    python -m unittest `
        tests.test_p3_shadow_contracts `
        tests.test_p3_shadow_storage_contracts `
        tests.test_p3_shadow_test_execution `
        tests.test_p3_shadow_read_api_contracts `
        tests.test_p3_shadow_acceptance
    if ($LASTEXITCODE -ne 0) {
        throw "P3-0 定向验收失败"
    }
    Write-Output "P3-0 通用基础设施定向验收通过"
}
finally {
    Pop-Location
}
