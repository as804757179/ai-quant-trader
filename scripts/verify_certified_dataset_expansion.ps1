#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
$TestPython = (Get-Command python -ErrorAction Stop).Source
$Failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure([string]$Message) {
    $Failures.Add($Message)
    Write-Host "FAIL: $Message" -ForegroundColor Red
}

function Import-HostEnvironment {
    Get-Content (Join-Path $Root ".env.host") -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        $index = $line.IndexOf("=")
        if ($line -and -not $line.StartsWith("#") -and $index -gt 0) {
            Set-Item "Env:$($line.Substring(0,$index).Trim().TrimStart([char]0xFEFF))" $line.Substring($index + 1).Trim()
        }
    }
    $env:PYTHONPATH = "$(Join-Path $Root 'backend');$(Join-Path $Root 'worker')"
}

function Get-PrefixedJson([object[]]$Output, [string]$Prefix) {
    $line = @($Output | ForEach-Object { $_.ToString() } | Where-Object { $_.StartsWith($Prefix) } | Select-Object -Last 1)
    if (-not $line) { throw "Missing structured output prefix: $Prefix" }
    return ($line.Substring($Prefix.Length) | ConvertFrom-Json)
}

function Invoke-Inspection([bool]$DatasetHashStable) {
    $value = if ($DatasetHashStable) { "true" } else { "false" }
    $output = & $Python (Join-Path $Root "backend\scripts\verify_sprint13_dataset.py") --dataset-hash-stable $value 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Sprint13 inspection failed: $($output -join "`n")" }
    return Get-PrefixedJson $output "S13_INSPECTION="
}

function Invoke-VerificationScript([string]$Path) {
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & powershell -ExecutionPolicy Bypass -File $Path 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $savedPreference
    $passed = $exitCode -eq 0 -and ($output -join "`n") -match "(?m)^PASS\s*$"
    if (-not $passed) {
        Add-Failure "Existing verification failed: $(Split-Path $Path -Leaf)"
    }
    return @{ passed = $passed; output = $output }
}

function Invoke-Pytest([string]$Path, [string]$Label) {
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $TestPython -m pytest $Path 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $savedPreference
    $text = $output -join "`n"
    $skip = ([regex]::Matches($text, "(?im)\b\d+\s+skipped\b")).Count
    $xfail = ([regex]::Matches($text, "(?im)\b\d+\s+xfailed\b")).Count
    $xpass = ([regex]::Matches($text, "(?im)\b\d+\s+xpassed\b")).Count
    if ($exitCode -ne 0) { Add-Failure "$Label pytest failed" }
    if ($skip -or $xfail -or $xpass) { Add-Failure "$Label pytest contains skip/xfail/xpass" }
    return @{ output = $output; exit_code = $exitCode; skip = $skip; xfail = $xfail; xpass = $xpass }
}

Import-HostEnvironment
if (-not (Test-Path $Python)) { throw "Backend Python environment is missing: $Python" }

$Before = Invoke-Inspection $true
$ImportOutput = & $Python (Join-Path $Root "backend\scripts\import_sprint13_dataset.py") 2>&1
if ($LASTEXITCODE -ne 0) {
    Add-Failure "Controlled importer rerun failed"
}
$After = Invoke-Inspection $true

$snapshotStable = $true
foreach ($field in @("legacy", "existing_certified", "corporate_actions")) {
    if ($Before.snapshots.$field -ne $After.snapshots.$field) {
        Add-Failure "Immutable snapshot changed: $field"
        $snapshotStable = $false
    }
}
if ($Before.dataset_hash -ne $After.dataset_hash) {
    Add-Failure "Sprint13 scoped dataset hash is not deterministic"
    $snapshotStable = $false
}
if (-not $After.run_manifest_match) { Add-Failure "Run and manifest binding mismatch" }
if ($After.verifier_status -ne "PASS") {
    $After.verifier_blockers | ForEach-Object { Add-Failure "Verifier blocker: $_" }
}

$VerificationScripts = @(
    "verify_data_certification.ps1",
    "verify_execution_safety.ps1",
    "verify_certified_ingestion_pilot.ps1",
    "verify_certified_kline_store.ps1",
    "verify_research_readiness.ps1",
    "verify_field_level_readiness.ps1",
    "verify_backtest_integrity.ps1",
    "verify_backtest_market_rules.ps1",
    "verify_market_microstructure_boundaries.ps1",
    "verify_corporate_action_pit.ps1"
)
$ExistingVerification = @{}
foreach ($scriptName in $VerificationScripts) {
    $ExistingVerification[$scriptName] = Invoke-VerificationScript (Join-Path $Root "scripts\$scriptName")
}

$BackendTests = Invoke-Pytest "backend/tests" "Backend"
$WorkerTests = Invoke-Pytest "worker/tests" "Worker"

$Summary = [ordered]@{
    verifier_status = if ($Failures.Count -eq 0) { "PASS" } else { "FAIL" }
    dataset_release_status = $After.dataset_release_status
    sprint13_status = $After.sprint13_status
    sprint14_admission = [bool]$After.sprint14_admission
    manifest_hash = $After.manifest_hash
    run_manifest_match = [bool]$After.run_manifest_match
    dataset_hash = $After.dataset_hash
    dataset_hash_stable = $snapshotStable
    dataset_row_count = $After.dataset_row_count
    existing_data_validation = $After.existing_data_validation
    checkpoint_state_summary = $After.checkpoint_state_summary
    retry_summary = $After.retry_summary
    provider_validation_by_stock = $After.provider_validation_by_stock
    security_status_summary = $After.security_status_summary
    missing_date_summary = $After.missing_date_summary
    corporate_action_summary = $After.corporate_action_summary
    readiness_summary = $After.readiness_summary
    scoped_ready_stock_count = $After.scoped_ready_stock_count
    scoped_ready_row_count = $After.scoped_ready_row_count
    release_lock_status = $After.release_lock_status
    orders_created = $After.orders_created
    candidates_created = $After.candidates_created
    existing_verification = [ordered]@{}
    backend_test_result = $BackendTests.exit_code -eq 0
    worker_test_result = $WorkerTests.exit_code -eq 0
    skip_count = $BackendTests.skip + $WorkerTests.skip
    xfail_count = $BackendTests.xfail + $WorkerTests.xfail
    xpass_count = $BackendTests.xpass + $WorkerTests.xpass
    P0 = $After.P0
    P1 = $After.P1
    P2 = $After.P2
    failures = @($Failures)
}
$ExistingVerification.GetEnumerator() | Sort-Object Key | ForEach-Object {
    $Summary.existing_verification[$_.Key] = [bool]$_.Value.passed
}
Write-Host ("SPRINT13_JSON=" + ($Summary | ConvertTo-Json -Depth 14 -Compress))
if ($Failures.Count -gt 0) {
    Write-Host "FAIL" -ForegroundColor Red
    exit 1
}
Write-Host "PASS" -ForegroundColor Green
