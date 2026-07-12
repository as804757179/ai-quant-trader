#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONDONTWRITEBYTECODE = "1"
$failures = [System.Collections.Generic.List[string]]::new()

Get-Content (Join-Path $Root ".env.host") -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim(); $index = $line.IndexOf("=")
    if ($line -and -not $line.StartsWith("#") -and $index -gt 0) {
        Set-Item -Path "Env:$($line.Substring(0, $index).Trim().TrimStart([char]0xFEFF))" -Value $line.Substring($index + 1).Trim()
    }
}

$expected = @{
    "TRADING_EXECUTION_ENABLED" = "false"
    "AI_ORDER_ENABLED" = "false"
    "LIVE_TRADING_ENABLED" = "false"
    "ALLOW_SCHEDULED_ORDER" = "false"
    "REQUIRE_HUMAN_APPROVAL" = "true"
}
foreach ($key in $expected.Keys) {
    if (([string](Get-Item "Env:$key" -ErrorAction SilentlyContinue).Value).ToLowerInvariant() -ne $expected[$key]) {
        $failures.Add("unsafe $key")
    }
}

$scan = Join-Path $Root "worker\services\signal_scan.py"
if (Select-String -Path $scan -Pattern "submit_order" -Quiet) {
    $failures.Add("signal scan still has order submission")
}
$manager = Join-Path $Root "backend\app\trade\order_manager.py"
if (-not (Select-String -Path $manager -Pattern "execution_gate.evaluate" -Quiet)) {
    $failures.Add("OrderManager does not enforce ExecutionGate")
}
$celery = Join-Path $Root "worker\celery_app.py"
if (-not (Select-String -Path $celery -Pattern "tasks.run_signal_scan" -Quiet)) {
    $failures.Add("signal scan task is not registered")
}

$python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $failures.Add("missing backend python")
} else {
    $env:PYTHONPATH = (Join-Path $Root "backend")
    & $python -m pytest backend/tests/test_execution_gate.py -q
    if ($LASTEXITCODE -ne 0) { $failures.Add("execution gate tests failed") }
    $env:PYTHONPATH = (Join-Path $Root "worker")
    & $python -m pytest worker/tests/test_ai_tasks.py worker/tests/test_celery_app.py -q
    if ($LASTEXITCODE -ne 0) { $failures.Add("worker safety tests failed") }
}

if ($failures.Count -gt 0) {
    Write-Output "FAIL"
    $failures | ForEach-Object { Write-Output "- $_" }
    exit 1
}
Write-Output "PASS"
