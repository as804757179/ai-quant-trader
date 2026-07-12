#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()
$env:PYTHONDONTWRITEBYTECODE = "1"

Get-Content (Join-Path $Root ".env.host") -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim(); $index = $line.IndexOf("=")
    if ($line -and -not $line.StartsWith("#") -and $index -gt 0) {
        Set-Item -Path "Env:$($line.Substring(0, $index).Trim().TrimStart([char]0xFEFF))" -Value $line.Substring($index + 1).Trim()
    }
}

$python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if ($env:CERTIFIED_BACKTEST_EXECUTION_ENABLED -ne "false") {
    $failures.Add("certified backtest execution must remain disabled")
}
if ($env:CERTIFIED_SCREENER_OUTPUT_ENABLED -ne "false") {
    $failures.Add("certified screener output must remain disabled")
}
if (-not (Test-Path $python)) {
    $failures.Add("missing backend python")
} else {
    $dbResult = @'
import asyncio, os, sys, asyncpg

async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://'))
    failures=[]
    try:
        batches = await conn.fetch("""
            SELECT batch_id, stock_code, provider, source, period, start_date, end_date,
                   fetch_time, importer_version, total_rows,
                   accepted_rows, rejected_rows, quality_score, status, reject_reason,
                   provider_priority, fallback_used, fetch_endpoint, raw_hash
            FROM market.data_batches
            WHERE importer_version='sprint06-sohu-daily-v1'
            ORDER BY created_at
        """)
        scoped={r['stock_code'] for r in batches if r['stock_code']}
        if not {'300308','603986','300502'}.issubset(scoped): failures.append('three stock attempts are missing')
        certified_batches=[r for r in batches if r['status']=='certified']
        if not certified_batches: failures.append('no certified Sprint06 batch')
        for row in certified_batches:
            if row['provider'] in ('unknown','synthetic') or row['source'] in ('unknown','synthetic'):
                failures.append('certified batch has invalid provider/source')
            if (row['period'] != '1d' or str(row['start_date']) != '2026-06-01'
                    or str(row['end_date']) != '2026-06-30' or not row['fetch_time']
                    or row['accepted_rows'] != row['total_rows'] or row['rejected_rows'] != 0):
                failures.append('certified batch row counts are invalid')
            if row['fallback_used'] or not row['fetch_endpoint'] or not row['raw_hash']:
                failures.append('certified batch provider metadata is incomplete')
        rejected_603986=[r for r in batches if r['stock_code']=='603986' and r['status']=='rejected']
        if not rejected_603986 or not any('legacy data preserved' in (r['reject_reason'] or '') for r in rejected_603986):
            failures.append('603986 legacy collision was not explicitly rejected')

        certified=await conn.fetchval("""
            SELECT COUNT(*) FROM market.kline_provenance p
            JOIN market.klines k USING(time, stock_code, period)
            WHERE p.importer_version='sprint06-sohu-daily-v1'
              AND p.certification_status='certified'
              AND p.quality_status='pass' AND NOT p.is_synthetic
              AND p.batch_id IS NOT NULL
              AND p.provider='sohu' AND p.source='sohu_daily_kline'
              AND k.volume > 0 AND k.amount > 0
              AND k.high >= GREATEST(k.open,k.close,k.low)
              AND k.low <= LEAST(k.open,k.close,k.high)
        """)
        if certified <= 0: failures.append('no valid certified provenance rows')
        if certified != sum(r['accepted_rows'] for r in certified_batches):
            failures.append('certified row count does not match accepted batch rows')
        invalid_kline=await conn.fetchval("""
            SELECT COUNT(*) FROM market.kline_provenance p
            JOIN market.klines k USING(time, stock_code, period)
            WHERE p.importer_version='sprint06-sohu-daily-v1'
              AND p.certification_status='certified'
              AND (k.volume <= 0 OR k.amount <= 0 OR k.open <= 0 OR k.high <= 0
                   OR k.low <= 0 OR k.close <= 0
                   OR k.high < GREATEST(k.open,k.close,k.low)
                   OR k.low > LEAST(k.open,k.close,k.high))
        """)
        if invalid_kline: failures.append('invalid OHLC/volume/amount is certified')
        provenance_mismatch=await conn.fetchval("""
            SELECT COUNT(*) FROM market.kline_provenance p
            WHERE p.importer_version='sprint06-sohu-daily-v1'
              AND p.certification_status='certified'
              AND (p.batch_id IS NULL OR p.quality_status<>'pass' OR p.is_synthetic
                   OR p.provider<>'sohu' OR p.source<>'sohu_daily_kline')
        """)
        if provenance_mismatch: failures.append('certified provenance metadata mismatch')
        duplicates=await conn.fetchval("""
            SELECT COUNT(*) FROM (
              SELECT stock_code, period, time::date, COUNT(*)
              FROM market.kline_provenance
              WHERE certification_status='certified'
              GROUP BY stock_code, period, time::date HAVING COUNT(*) > 1
            ) d
        """)
        if duplicates: failures.append('certified natural-day duplicates exist')
        bad_time=await conn.fetchval("""
            SELECT COUNT(*) FROM market.kline_provenance
            WHERE certification_status='certified'
              AND (EXTRACT(HOUR FROM time AT TIME ZONE 'Asia/Shanghai') <> 15
                   OR EXTRACT(MINUTE FROM time AT TIME ZONE 'Asia/Shanghai') <> 0)
        """)
        if bad_time: failures.append('certified timestamp is not 15:00 Asia/Shanghai')
        unknown_certified=await conn.fetchval("SELECT COUNT(*) FROM market.kline_provenance WHERE source='unknown' AND certification_status='certified'")
        synthetic_certified=await conn.fetchval("SELECT COUNT(*) FROM market.kline_provenance WHERE is_synthetic AND certification_status='certified'")
        if unknown_certified: failures.append('unknown data is certified')
        if synthetic_certified: failures.append('synthetic data is certified')
    finally:
        await conn.close()
    if failures:
        print('FAIL')
        for item in failures: print('- '+item)
        return 1
    print('PASS')
    return 0

sys.exit(asyncio.run(main()))
'@ | & $python -
    $dbExit = $LASTEXITCODE
    $dbResult | ForEach-Object { Write-Output $_ }
    if ($dbExit -ne 0) { $failures.Add("pilot database verification failed") }

    $env:PYTHONPATH = (Join-Path $Root "backend")
    & $python -m pytest backend/tests/test_certified_ingestion_pilot.py backend/tests/test_data_certification.py backend/tests/test_execution_gate.py backend/tests/test_screener.py::test_screen_preset_ai_momentum -q
    if ($LASTEXITCODE -ne 0) { $failures.Add("pilot safety regression tests failed") }
}

& powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\verify_data_certification.ps1")
if ($LASTEXITCODE -ne 0) { $failures.Add("data certification verification failed") }
& powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\verify_execution_safety.ps1")
if ($LASTEXITCODE -ne 0) { $failures.Add("execution safety verification failed") }

if ($failures.Count -gt 0) {
    Write-Output "FAIL"
    $failures | ForEach-Object { Write-Output "- $_" }
    exit 1
}
Write-Output "PASS"
