#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Failures = [System.Collections.Generic.List[string]]::new()
$env:PYTHONDONTWRITEBYTECODE = "1"

Get-Content (Join-Path $Root ".env.host") -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim(); $index = $line.IndexOf("=")
    if ($line -and -not $line.StartsWith("#") -and $index -gt 0) {
        Set-Item -Path "Env:$($line.Substring(0, $index).Trim().TrimStart([char]0xFEFF))" -Value $line.Substring($index + 1).Trim()
    }
}

$BackendPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
$ProviderPython = Join-Path $Root "a-stock-data\service\.venv\Scripts\python.exe"
if (-not (Test-Path $BackendPython)) { $Failures.Add("缺少 backend Python 环境") }
if (-not (Test-Path $ProviderPython)) { $Failures.Add("缺少 Provider 校验 Python 环境") }

foreach ($lock in @(
    "CERTIFIED_BACKTEST_EXECUTION_ENABLED",
    "CERTIFIED_SCREENER_OUTPUT_ENABLED",
    "TRADING_EXECUTION_ENABLED",
    "LIVE_TRADING_ENABLED",
    "AI_ORDER_ENABLED"
)) {
    if ((Get-Item "Env:$lock" -ErrorAction SilentlyContinue).Value -ne "false") {
        $Failures.Add("发布锁必须保持关闭: $lock")
    }
}

if (Test-Path $BackendPython) {
    $env:PYTHONPATH = Join-Path $Root "backend"
    $DatabaseResult = @'
import asyncio, json, os, asyncpg

async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://'))
    failures=[]
    try:
        exists = await conn.fetchval("SELECT to_regclass('market.certified_klines') IS NOT NULL")
        if not exists: failures.append('Certified Store 不存在')
        if not await conn.fetchval("SELECT to_regclass('market.klines') IS NOT NULL"):
            failures.append('legacy 表不存在')
        if await conn.fetchval("SELECT COUNT(*) FROM market.klines") <= 0:
            failures.append('legacy 数据不存在')
        owner = await conn.fetchval("SELECT tableowner FROM pg_tables WHERE schemaname='market' AND tablename='certified_klines'")
        if owner != 'quant_admin': failures.append('Certified Store Owner 不是 quant_admin')
        migrated = await conn.fetchval("SELECT COUNT(*) FROM market.certified_klines WHERE importer_version='sprint06-sohu-daily-v1'")
        if migrated != 42: failures.append(f'Sprint06 迁移数量不是 42: {migrated}')
        hash_mismatch = await conn.fetchval("""
            SELECT COUNT(*) FROM market.certified_klines c
            JOIN market.kline_provenance p
              ON split_part(c.stock_code,'.',1)=p.stock_code AND c.period=p.period
             AND c.trading_date=(p.time AT TIME ZONE 'Asia/Shanghai')::date
            WHERE c.importer_version='sprint06-sohu-daily-v1' AND c.raw_hash<>p.raw_hash
        """)
        if hash_mismatch: failures.append(f'迁移 raw_hash 不一致: {hash_mismatch}')
        value_mismatch = await conn.fetchval("""
            SELECT COUNT(*) FROM market.certified_klines c
            JOIN market.klines k
              ON split_part(c.stock_code,'.',1)=k.stock_code AND c.period=k.period
             AND c.trading_date=(k.time AT TIME ZONE 'Asia/Shanghai')::date
            WHERE c.importer_version='sprint06-sohu-daily-v1'
              AND (c.open<>k.open OR c.high<>k.high OR c.low<>k.low OR c.close<>k.close
                   OR c.volume<>k.volume OR c.amount<>k.amount)
        """)
        if value_mismatch: failures.append(f'迁移数值不一致: {value_mismatch}')
        invalid = await conn.fetchval("""
            SELECT COUNT(*) FROM market.certified_klines
            WHERE provider IN ('unknown','synthetic') OR source IN ('unknown','synthetic')
               OR quality_status<>'pass' OR certification_status<>'certified'
        """)
        if invalid: failures.append(f'非法数据进入 Certified Store: {invalid}')
        count_603986 = await conn.fetchval("SELECT COUNT(*) FROM market.certified_klines WHERE stock_code='603986.SH' AND trading_date BETWEEN '2026-06-01' AND '2026-06-30'")
        legacy_603986 = await conn.fetchval("SELECT COUNT(*) FROM market.klines WHERE stock_code='603986' AND time::date BETWEEN '2026-06-01' AND '2026-06-30'")
        if count_603986 != 21: failures.append(f'603986 Certified Store 数量不是 21: {count_603986}')
        if legacy_603986 != 21: failures.append(f'603986 legacy 数据被覆盖或删除: {legacy_603986}')
        adjustments = await conn.fetch("SELECT DISTINCT adjustment FROM market.certified_klines")
        if {r['adjustment'] for r in adjustments} != {'raw'}:
            failures.append('adjustment 不是已证明的 raw 单一口径')
        semantic_invalid = await conn.fetchval("""
            SELECT COUNT(*) FROM market.certified_klines
            WHERE market_close_time<>TIME '15:00:00' OR timezone<>'Asia/Shanghai'
               OR price_currency<>'CNY' OR volume_unit<>'share' OR amount_unit<>'CNY'
               OR normalizer_version IS NULL OR schema_version IS NULL OR importer_version IS NULL
        """)
        if semantic_invalid: failures.append(f'时间/货币/单位/版本语义异常: {semantic_invalid}')
        duplicates = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT stock_code, period, trading_date, adjustment, COUNT(*)
                FROM market.certified_klines GROUP BY 1,2,3,4 HAVING COUNT(*)>1
            ) d
        """)
        if duplicates: failures.append(f'同日同 adjustment 重复: {duplicates}')
        if await conn.fetchval("SELECT COUNT(*) FROM market.certified_klines WHERE provider='sina' OR source LIKE 'sina%'"):
            failures.append('第二 Provider 写入了 Certified Store')
        open_days = await conn.fetch("SELECT exchange, COUNT(*) n FROM market.trading_calendar WHERE is_trading_day AND trading_date BETWEEN '2026-06-01' AND '2026-06-30' GROUP BY exchange")
        if {r['exchange']:r['n'] for r in open_days} != {'SH':21, 'SZ':21}:
            failures.append('交易日历开放日数量异常')
        if await conn.fetchval("SELECT is_trading_day FROM market.trading_calendar WHERE exchange='SH' AND trading_date='2026-06-19'"):
            failures.append('法定节假日被标为交易日')
    finally:
        await conn.close()
    print(json.dumps(failures, ensure_ascii=False))

asyncio.run(main())
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("数据库认证 Store 检查执行失败")
    } else {
        (ConvertFrom-Json ($DatabaseResult -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }

    $SourceResult = @'
import inspect, json
from app.backtest.service import BacktestService
from app.screener.engine import ScreenerEngine
from app.data.certified_kline_repository import CertifiedKlineRepository

failures=[]
for method in (BacktestService._load_bars, ScreenerEngine._load_universe):
    source=inspect.getsource(method)
    if 'kline_repository' not in source: failures.append(f'{method.__qualname__} 未通过 Repository')
    if 'market.klines' in source or 'kline_provenance' in source: failures.append(f'{method.__qualname__} 仍读取 legacy')
repository_source=inspect.getsource(CertifiedKlineRepository)
if 'market.klines ' in repository_source or 'market.kline_provenance' in repository_source:
    failures.append('Repository 读取 legacy')
print(json.dumps(failures, ensure_ascii=False))
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("Repository 源码检查执行失败")
    } else {
        (ConvertFrom-Json ($SourceResult -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }
}

if (Test-Path $ProviderPython) {
    $ProviderOutput = & $ProviderPython (Join-Path $Root "scripts\validate_sprint07_providers.py") 2>&1
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("Provider 证据校验执行失败")
    } else {
        try {
            $Provider = ConvertFrom-Json ($ProviderOutput -join "`n")
            if ($Provider.adjustment_evidence.conclusion -ne "raw") {
                $Failures.Add("Sohu adjustment 未证明为 raw")
            }
            foreach ($stock in $Provider.cross_provider_evidence.stocks) {
                if ($stock.common_rows -lt 5 -or $stock.comparisons.Count -lt 5) {
                    $Failures.Add("第二 Provider 共同交易日不足: $($stock.stock_code)")
                }
                foreach ($comparison in $stock.comparisons) {
                    foreach ($field in $comparison.fields.PSObject.Properties) {
                        if (-not $field.Value.passed) {
                            $Failures.Add("第二 Provider 差异超容差: $($stock.stock_code) $($comparison.trading_date) $($field.Name)")
                        }
                    }
                }
            }
        } catch {
            $Failures.Add("Provider 证据输出不是有效 JSON")
        }
    }
}

foreach ($script in @("verify_data_certification.ps1", "verify_execution_safety.ps1")) {
    $Output = & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot $script) 2>&1
    if ($LASTEXITCODE -ne 0 -or ($Output -join "`n") -notmatch "PASS") {
        $Failures.Add("基础验收失败: $script")
    }
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    $env:PYTHONPATH = "$(Join-Path $Root 'backend');$(Join-Path $Root 'worker')"
    $BackendTests = & python -m pytest (Join-Path $Root "backend\tests") -q 2>&1
    if ($LASTEXITCODE -ne 0) { $Failures.Add("backend 全量测试失败") }
    if (($BackendTests -join "`n") -match "\b(skipped|xfailed|xpassed)\b") {
        $Failures.Add("backend 存在 skip/xfail/xpass")
    }
    $WorkerTests = & python -m pytest (Join-Path $Root "worker\tests") -q 2>&1
    if ($LASTEXITCODE -ne 0) { $Failures.Add("worker 全量测试失败") }
    if (($WorkerTests -join "`n") -match "\b(skipped|xfailed|xpassed)\b") {
        $Failures.Add("worker 存在 skip/xfail/xpass")
    }
}

if ($Failures.Count) {
    Write-Host "FAIL" -ForegroundColor Red
    $Failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Write-Host "PASS" -ForegroundColor Green
Write-Host "Certified Store、数据语义、Provider 证据、发布锁和全量回归均通过。"
exit 0
