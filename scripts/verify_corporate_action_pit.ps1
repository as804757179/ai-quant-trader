#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Failures = [System.Collections.Generic.List[string]]::new()
$Results = [ordered]@{}
$Python = (Get-Command python -ErrorAction Stop).Source
Get-Content (Join-Path $Root ".env.host") -Encoding UTF8 | ForEach-Object {
    $Line = $_.Trim()
    $Index = $Line.IndexOf("=")
    if ($Line -and -not $Line.StartsWith("#") -and $Index -gt 0) {
        Set-Item -Path "Env:$($Line.Substring(0, $Index).Trim().TrimStart([char]0xFEFF))" -Value $Line.Substring($Index + 1).Trim()
    }
}
$env:PYTHONPATH = (Join-Path $Root "backend")
$env:SPRINT12_EVIDENCE_FILE = Join-Path $Root "evidence\corporate_actions\cninfo\1225351859_bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d.pdf"

$ValidationCode = @'
import asyncio
import asyncpg
import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.backtest.corporate_action_validation import validate_fixed_scenarios
from app.backtest.corporate_actions import CorporateActionEvent, CorporateActionRepository, CorporateActionProcessor
from app.core.config import settings

STOCK = "300502.SZ"
PERIOD = "1d"
ADJUSTMENT = "raw"
DATE_FROM = date(2026, 6, 1)
DATE_TO = date(2026, 6, 30)
SCOPE = "return_backtest"
GROSS_PROFILE = "OHLCV_TOTAL_RETURN_GROSS_V1"
EXPECTED_HASH = "bc589a6d4467409f84cc106d17022e5fd4c8633f0c3cb2080e9f98264390029d"
ACTION_ID = "cninfo-1225351859-v1"
EXPECTED_SCENARIOS = {
    "no_holding_no_entitlement",
    "record_date_100_shares",
    "sold_before_record_no_entitlement",
    "bought_after_record_no_entitlement",
    "partial_holding",
    "one_hundred_becomes_140",
    "sell_140_supported",
    "sell_100_then_odd_lot_40_supported",
    "cash_not_before_payment_date",
    "shares_not_before_credit_date",
    "pre_announcement_hidden",
    "event_version_changes_hash",
}
SNAPSHOT_COLUMNS = (
    "stock_code", "period", "trading_date", "adjustment", "open", "high", "low",
    "close", "volume", "amount", "provider", "source", "batch_id", "raw_hash",
    "certification_status", "quality_status",
)


def normalized(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def stable_snapshot(rows):
    records = [
        {key: normalized(row[key]) for key in SNAPSHOT_COLUMNS}
        for row in rows
    ]
    records.sort(key=lambda row: (row["stock_code"], row["period"], row["trading_date"], row["adjustment"]))
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return records, hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def fetch_snapshot(conn):
    rows = await conn.fetch(
        """
        SELECT stock_code, period, trading_date, adjustment, open, high, low, close,
               volume, amount, provider, source, batch_id, raw_hash,
               certification_status, quality_status
        FROM market.certified_klines
        WHERE stock_code=$1 AND period=$2 AND adjustment=$3
          AND trading_date BETWEEN $4 AND $5
        ORDER BY stock_code, period, trading_date, adjustment
        """,
        STOCK, PERIOD, ADJUSTMENT, DATE_FROM, DATE_TO,
    )
    return stable_snapshot(rows)


async def exact_readiness(conn, stock_code, scope, profile):
    rows = await conn.fetch(
        """
        SELECT readiness_status FROM market.research_readiness_reviews
        WHERE stock_code=$1 AND period=$2 AND adjustment=$3
          AND research_use_scope=$4 AND requirement_profile=$5
          AND date_from=$6 AND date_to=$7
        """,
        stock_code, PERIOD, ADJUSTMENT, scope, profile, DATE_FROM, DATE_TO,
    )
    return [row["readiness_status"] for row in rows]


def immutable_fields(row):
    keys = (
        "action_id", "cash_dividend_per_10", "share_increase_per_10",
        "event_version", "evidence_hash", "supersedes_action_id",
    )
    return {key: normalized(row[key]) for key in keys}


async def mutation_is_blocked(database_url, sql):
    conn = await asyncpg.connect(database_url)
    tx = conn.transaction()
    await tx.start()
    blocked = False
    expected_error = False
    try:
        try:
            await conn.execute(sql)
        except Exception as exc:
            blocked = True
            expected_error = "immutable" in str(exc).lower()
    finally:
        await tx.rollback()
        await conn.close()
    return blocked, expected_error


async def validate_version_chain(database_url, original):
    revision_id = "cninfo-1225351859-v2-sprint121-test"
    revision_version = "cninfo-1225351859-v2"
    conn = await asyncpg.connect(database_url)
    tx = conn.transaction()
    await tx.start()
    result = {
        "new_version_inserted": False,
        "supersedes_link_valid": False,
        "old_version_preserved": False,
        "duplicate_version_blocked": False,
        "transaction_rolled_back": False,
    }
    try:
        await conn.execute(
            """
            INSERT INTO market.corporate_actions (
                action_id, stock_code, event_type, announcement_date, record_date, ex_date,
                cash_payment_date, share_credit_date, cash_dividend_per_10,
                share_increase_per_10, source_name, source_reference, evidence_hash,
                captured_at, event_version, verification_status, supersedes_action_id
            ) SELECT $1, stock_code, event_type, announcement_date, record_date, ex_date,
                     cash_payment_date, share_credit_date, cash_dividend_per_10,
                     share_increase_per_10, source_name, source_reference, evidence_hash,
                     NOW(), $2, verification_status, action_id
              FROM market.corporate_actions WHERE action_id=$3
            """,
            revision_id, revision_version, ACTION_ID,
        )
        chain = await conn.fetch(
            """SELECT action_id,event_version,supersedes_action_id
                 FROM market.corporate_actions
                WHERE action_id=ANY($1::varchar[]) ORDER BY event_version""",
            [ACTION_ID, revision_id],
        )
        result["new_version_inserted"] = len(chain) == 2 and chain[1]["event_version"] > chain[0]["event_version"]
        result["supersedes_link_valid"] = chain[1]["supersedes_action_id"] == ACTION_ID
        old = await conn.fetchrow("SELECT * FROM market.corporate_actions WHERE action_id=$1", ACTION_ID)
        result["old_version_preserved"] = old is not None and immutable_fields(old) == immutable_fields(original)
        try:
            await conn.execute(
                """
                INSERT INTO market.corporate_actions (
                    action_id, stock_code, event_type, announcement_date, record_date, ex_date,
                    cash_payment_date, share_credit_date, cash_dividend_per_10,
                    share_increase_per_10, source_name, source_reference, evidence_hash,
                    captured_at, event_version, verification_status, supersedes_action_id
                ) SELECT 'cninfo-duplicate-version-test', stock_code, event_type,
                         announcement_date, record_date, ex_date, cash_payment_date,
                         share_credit_date, cash_dividend_per_10, share_increase_per_10,
                         source_name, source_reference, evidence_hash, NOW(), $1,
                         verification_status, action_id
                  FROM market.corporate_actions WHERE action_id=$2
                """,
                revision_version, ACTION_ID,
            )
        except asyncpg.UniqueViolationError:
            result["duplicate_version_blocked"] = True
    finally:
        await tx.rollback()
        await conn.close()
    check = await asyncpg.connect(database_url)
    try:
        result["transaction_rolled_back"] = not await check.fetchval(
            "SELECT EXISTS(SELECT 1 FROM market.corporate_actions WHERE action_id=$1)",
            revision_id,
        )
    finally:
        await check.close()
    return result


async def main():
    failures = []
    checks = {}
    database_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(database_url)
    try:
        original = await conn.fetchrow("SELECT * FROM market.corporate_actions WHERE action_id=$1", ACTION_ID)
        if original is None:
            raise RuntimeError("official corporate action is missing")
        original_fields = immutable_fields(original)
        before_records, before_hash = await fetch_snapshot(conn)
        orders_before = await conn.fetchval("SELECT COUNT(*) FROM trade.orders")

        evidence_path = Path(os.environ["SPRINT12_EVIDENCE_FILE"])
        computed_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest() if evidence_path.is_file() else None
        evidence = {
            "file_path": str(evidence_path),
            "file_size": evidence_path.stat().st_size if evidence_path.is_file() else 0,
            "computed_sha256": computed_hash,
            "database_evidence_hash": original["evidence_hash"].strip(),
            "expected_sha256": EXPECTED_HASH,
        }
        evidence["all_match"] = (
            evidence["file_size"] > 0
            and computed_hash == evidence["database_evidence_hash"] == EXPECTED_HASH
        )
        checks["evidence_hash_validation"] = evidence
        if not evidence["all_match"]:
            failures.append("official evidence file/database/expected hash mismatch")

        update_blocked, update_expected = await mutation_is_blocked(
            database_url,
            "UPDATE market.corporate_actions SET cash_dividend_per_10=11 WHERE action_id='cninfo-1225351859-v1'",
        )
        delete_blocked, delete_expected = await mutation_is_blocked(
            database_url,
            "DELETE FROM market.corporate_actions WHERE action_id='cninfo-1225351859-v1'",
        )
        current = await conn.fetchrow("SELECT * FROM market.corporate_actions WHERE action_id=$1", ACTION_ID)
        immutability = {
            "update_blocked": update_blocked,
            "update_expected_error": update_expected,
            "delete_blocked": delete_blocked,
            "delete_expected_error": delete_expected,
            "original_record_exists": current is not None,
            "original_fields_unchanged": current is not None and immutable_fields(current) == original_fields,
        }
        checks["immutable_update_validation"] = {key: immutability[key] for key in ("update_blocked", "update_expected_error", "original_fields_unchanged")}
        checks["immutable_delete_validation"] = {key: immutability[key] for key in ("delete_blocked", "delete_expected_error", "original_record_exists")}
        if not all(immutability.values()):
            failures.append("UPDATE/DELETE immutability validation failed")

        version_chain = await validate_version_chain(database_url, original)
        checks["version_chain_validation"] = version_chain
        if not all(version_chain.values()):
            failures.append("corporate action version-chain validation failed")

        repo = CorporateActionRepository()
        if await repo.visible_events(STOCK, date(2026, 6, 3)):
            failures.append("pre-announcement information leak")
        events = await repo.visible_events(STOCK, date(2026, 6, 4))
        scenarios = validate_fixed_scenarios(events[0]) if len(events) == 1 else {}
        actual_names = set(scenarios)
        failed_scenarios = sorted(name for name, passed in scenarios.items() if passed is not True)
        scenario_validation = {
            "actual_scenario_count": len(scenarios),
            "expected_scenario_count": len(EXPECTED_SCENARIOS),
            "expected_behaviors_present": actual_names == EXPECTED_SCENARIOS,
            "scenarios": {name: bool(scenarios[name]) for name in sorted(scenarios)},
            "failed_scenarios": failed_scenarios,
        }
        checks["scenario_validation"] = scenario_validation
        if not scenarios:
            failures.append("corporate action scenario result is empty")
        if len(scenarios) != len(EXPECTED_SCENARIOS):
            failures.append(f"corporate action scenario count={len(scenarios)}, expected={len(EXPECTED_SCENARIOS)}")
        if actual_names != EXPECTED_SCENARIOS:
            failures.append("corporate action expected behavior names do not match")
        if failed_scenarios:
            failures.append("failed corporate action scenarios: " + ",".join(failed_scenarios))

        readiness = {
            "300502_gross": await exact_readiness(conn, STOCK, SCOPE, GROSS_PROFILE),
            "300502_ohlcv": await exact_readiness(conn, STOCK, SCOPE, "OHLCV_RETURN_V1"),
            "300502_amount": await exact_readiness(conn, STOCK, SCOPE, "AMOUNT_FACTOR_V1"),
            "300502_execution": await exact_readiness(conn, STOCK, "execution_reference", "EXECUTION_REFERENCE_V1"),
            "300308_ohlcv": await exact_readiness(conn, "300308.SZ", SCOPE, "OHLCV_RETURN_V1"),
            "603986_ohlcv": await exact_readiness(conn, "603986.SH", SCOPE, "OHLCV_RETURN_V1"),
            "300308_gross": await exact_readiness(conn, "300308.SZ", SCOPE, GROSS_PROFILE),
            "603986_gross": await exact_readiness(conn, "603986.SH", SCOPE, GROSS_PROFILE),
        }
        net_ready = await conn.fetchval(
            """
            SELECT COUNT(*) FROM market.research_readiness_reviews
             WHERE readiness_status='ready'
               AND (requirement_profile ILIKE '%NET%' OR research_use_scope ILIKE '%NET%')
            """
        )
        readiness["net_tax_ready_count"] = net_ready
        readiness_ok = (
            readiness["300502_gross"] == ["ready"]
            and readiness["300502_ohlcv"] == ["rejected"]
            and readiness["300502_amount"] != ["ready"]
            and readiness["300502_execution"] != ["ready"]
            and readiness["300308_ohlcv"] == ["ready"]
            and readiness["603986_ohlcv"] == ["ready"]
            and readiness["300308_gross"] == []
            and readiness["603986_gross"] == []
            and net_ready == 0
        )
        readiness["complete_authorization_key"] = {
            "stock_code": STOCK, "period": PERIOD, "adjustment": ADJUSTMENT,
            "research_use_scope": SCOPE, "requirement_profile": GROSS_PROFILE,
            "date_from": DATE_FROM.isoformat(), "date_to": DATE_TO.isoformat(),
        }
        readiness["passed"] = readiness_ok
        checks["readiness_validation"] = readiness
        if not readiness_ok:
            failures.append("exact scoped readiness validation failed")

        after_records, after_hash = await fetch_snapshot(conn)
        changed_rows = sum(1 for before, after in zip(before_records, after_records) if before != after) + abs(len(before_records) - len(after_records))
        raw_hash_mismatch = sum(1 for before, after in zip(before_records, after_records) if before["raw_hash"] != after["raw_hash"])
        lineage_mismatch = sum(
            1 for before, after in zip(before_records, after_records)
            if any(before[key] != after[key] for key in ("provider", "source", "batch_id"))
        )
        market_mismatch = sum(
            1 for before, after in zip(before_records, after_records)
            if any(before[key] != after[key] for key in ("open", "high", "low", "close", "volume", "amount"))
        )
        snapshot = {
            "row_count": len(before_records),
            "before_snapshot_hash": before_hash,
            "after_snapshot_hash": after_hash,
            "changed_rows_count": changed_rows,
            "raw_hash_mismatch_count": raw_hash_mismatch,
            "provider_source_batch_mismatch_count": lineage_mismatch,
            "ohlcv_amount_mismatch_count": market_mismatch,
            "all_rows_raw": all(row["adjustment"] == "raw" for row in before_records),
        }
        snapshot["passed"] = (
            snapshot["row_count"] == 21 and before_hash == after_hash
            and changed_rows == raw_hash_mismatch == lineage_mismatch == market_mismatch == 0
            and snapshot["all_rows_raw"]
        )
        checks["raw_snapshot_validation"] = snapshot
        if not snapshot["passed"]:
            failures.append("Certified raw snapshot changed or is incomplete")

        lock_names = [
            "CERTIFIED_BACKTEST_EXECUTION_ENABLED", "CERTIFIED_SCREENER_OUTPUT_ENABLED",
            "TRADING_EXECUTION_ENABLED", "LIVE_TRADING_ENABLED", "AI_ORDER_ENABLED",
            "ALLOW_SCHEDULED_ORDER",
        ]
        lock_values = {name: bool(getattr(settings, name)) for name in lock_names}
        orders_after = await conn.fetchval("SELECT COUNT(*) FROM trade.orders")
        release = {
            "locks": lock_values,
            "all_locks_false": not any(lock_values.values()),
            "orders_before": orders_before,
            "orders_after": orders_after,
            "orders_created": orders_after - orders_before,
        }
        release["passed"] = release["all_locks_false"] and release["orders_created"] == 0
        checks["release_lock_validation"] = release
        if not release["passed"]:
            failures.append("release lock/order validation failed")
    finally:
        await conn.close()

    summary = {
        "failures": failures,
        "checks": checks,
        "processor_version": CorporateActionProcessor.VERSION,
    }
    print("SPRINT12_JSON=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if failures:
        raise SystemExit(1)


asyncio.run(main())
'@

$PreviousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$ValidationOutput = $ValidationCode | & $Python - 2>&1
$ValidationExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorAction
$SummaryLine = $ValidationOutput | Where-Object { $_ -like "SPRINT12_JSON=*" } | Select-Object -Last 1
if (-not $SummaryLine) {
    $ValidationOutput | ForEach-Object { Write-Host $_ }
    Write-Host "FAIL validation subprocess produced no structured summary" -ForegroundColor Red
    exit 1
}
$Summary = ConvertFrom-Json $SummaryLine.Substring(("SPRINT12_JSON=").Length)
foreach ($Property in $Summary.checks.PSObject.Properties) {
    $Failed = $Summary.failures.Count -gt 0 -and (($Summary.failures -join " ") -match [regex]::Escape($Property.Name.Split("_")[0]))
    Write-Host ("CHECK {0}: {1}" -f $Property.Name, $(if ($Failed) { "FAIL" } else { "PASS" }))
}
$Summary.checks.scenario_validation.scenarios.PSObject.Properties | ForEach-Object {
    Write-Host ("SCENARIO {0}: {1}" -f $_.Name, $(if ($_.Value) { "PASS" } else { "FAIL" }))
}
if ($ValidationExitCode -ne 0 -or $Summary.failures.Count -gt 0) {
    $Summary.failures | ForEach-Object { $Failures.Add([string]$_) }
    if ($ValidationExitCode -ne 0 -and $Summary.failures.Count -eq 0) {
        $Failures.Add("Sprint12 validation subprocess failed unexpectedly")
    }
}

$PriorOutput = & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\verify_market_microstructure_boundaries.ps1") 2>&1
$PriorPassed = $LASTEXITCODE -eq 0 -and ($PriorOutput -join "`n") -match "PASS"
$Results["existing_verification_chain"] = $PriorPassed
Write-Host ("CHECK existing_verification_chain: {0}" -f $(if ($PriorPassed) { "PASS" } else { "FAIL" }))
if (-not $PriorPassed) { $Failures.Add("existing verification chain failed") }

$PreviousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$BackendOutput = & $Python -m pytest (Join-Path $Root "backend\tests") -q 2>&1
$BackendExitCode = $LASTEXITCODE
Push-Location (Join-Path $Root "worker")
try {
    $WorkerOutput = & $Python -m pytest tests -q 2>&1
    $WorkerExitCode = $LASTEXITCODE
} finally {
    Pop-Location
    $ErrorActionPreference = $PreviousErrorAction
}
$SummaryPattern = '(?i)\b\d+\s+(skipped|xfailed|xpassed)\b'
$BackendClean = $BackendExitCode -eq 0 -and ($BackendOutput -join "`n") -notmatch $SummaryPattern
$WorkerClean = $WorkerExitCode -eq 0 -and ($WorkerOutput -join "`n") -notmatch $SummaryPattern
$Results["backend_tests"] = $BackendClean
$Results["worker_tests"] = $WorkerClean
Write-Host ("CHECK backend_tests: {0}" -f $(if ($BackendClean) { "PASS" } else { "FAIL" }))
Write-Host ("CHECK worker_tests: {0}" -f $(if ($WorkerClean) { "PASS" } else { "FAIL" }))
if (-not $BackendClean) { $Failures.Add("backend tests failed or contain skip/xfail/xpass") }
if (-not $WorkerClean) { $Failures.Add("worker tests failed or contain skip/xfail/xpass") }

$Final = [ordered]@{
    status = $(if ($Failures.Count) { "FAIL" } else { "PASS" })
    validation = $Summary
    existing_verification_chain = $PriorPassed
    backend_tests = $BackendClean
    worker_tests = $WorkerClean
    failures = @($Failures)
}
Write-Host ("SPRINT12_FINAL_JSON=" + ($Final | ConvertTo-Json -Depth 12 -Compress))
if ($Failures.Count) {
    Write-Host "FAIL" -ForegroundColor Red
    $Failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}
Write-Host "PASS" -ForegroundColor Green
exit 0
