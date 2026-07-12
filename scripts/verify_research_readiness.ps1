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
$env:PYTHONPATH = "$(Join-Path $Root 'backend');$(Join-Path $Root 'worker')"

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

if (-not (Test-Path $BackendPython)) {
    $Failures.Add("缺少 backend Python 环境")
} else {
    $DatabaseOutput = @'
import asyncio, json, os, asyncpg

async def main():
    conn=await asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://'))
    failures=[]
    try:
        tables=('research_readiness_reviews','research_date_reviews','corporate_action_reviews')
        for table in tables:
            if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f'market.{table}'):
                failures.append(f'missing table: {table}')
            owner=await conn.fetchval("SELECT tableowner FROM pg_tables WHERE schemaname='market' AND tablename=$1",table)
            if owner!='quant_admin': failures.append(f'invalid owner: {table}')
        reviews=await conn.fetchval("SELECT COUNT(*) FROM market.research_readiness_reviews WHERE reviewer_version<>'sprint13-controlled-expansion-v1'")
        stocks=await conn.fetchval("SELECT COUNT(DISTINCT stock_code) FROM market.research_readiness_reviews WHERE reviewer_version<>'sprint13-controlled-expansion-v1'")
        if reviews!=13 or stocks!=3: failures.append(f'invalid readiness review coverage: {reviews}/{stocks}')
        scopes=await conn.fetchval("SELECT COUNT(DISTINCT research_use_scope) FROM market.research_readiness_reviews WHERE reviewer_version<>'sprint13-controlled-expansion-v1'")
        if scopes!=3: failures.append('research use scopes are incomplete')
        primary=await conn.fetchval("SELECT COUNT(*) FROM market.research_date_reviews WHERE dataset_scope='certified_store'")
        normal=await conn.fetchval("SELECT COUNT(*) FROM market.research_date_reviews WHERE dataset_scope='certified_store' AND status='normal_trade'")
        closed=await conn.fetchval("SELECT COUNT(*) FROM market.research_date_reviews WHERE dataset_scope='certified_store' AND status='exchange_closed'")
        unresolved=await conn.fetchval("SELECT COUNT(*) FROM market.research_date_reviews WHERE status='unresolved' AND reviewer_version='sprint08-readiness-v1'")
        if (primary,normal,closed)!=(90,63,27): failures.append(f'invalid date review counts: {primary}/{normal}/{closed}')
        if unresolved: failures.append(f'unresolved date review exists: {unresolved}')
        sina_missing=await conn.fetchval("""
            SELECT COUNT(*) FROM market.research_date_reviews
            WHERE dataset_scope='secondary:sina_klc_archive' AND trading_date='2026-06-30'
              AND status='provider_missing'
        """)
        if sina_missing!=3: failures.append('Sina 2026-06-30 missingness is not attributed for all stocks')
        actions=await conn.fetch("SELECT stock_code,event_type,verification_status FROM market.corporate_action_reviews WHERE reviewer_version='sprint08-readiness-v1'")
        action_map={r['stock_code']:dict(r) for r in actions}
        if set(action_map)!= {'300308.SZ','603986.SH','300502.SZ'}: failures.append('corporate-action reviews are incomplete')
        if action_map.get('300308.SZ',{}).get('verification_status')!='verified_no_event': failures.append('300308 no-event review failed')
        if action_map.get('603986.SH',{}).get('verification_status')!='verified_no_event': failures.append('603986 no-event review failed')
        if action_map.get('300502.SZ',{}).get('event_type')!='cash_dividend_and_capital_increase': failures.append('300502 action is missing')
        ready=await conn.fetchval("SELECT COUNT(*) FROM market.certified_klines WHERE research_readiness_status='ready'")
        pending=await conn.fetchval("SELECT COUNT(*) FROM market.certified_klines WHERE research_readiness_status='review_required'")
        if ready!=0 or pending<63: failures.append(f'unsafe Store readiness state: ready={ready}, pending={pending}')
        invalid_mix=await conn.fetchval("SELECT COUNT(*) FROM market.certified_klines WHERE adjustment<>'raw'")
        if invalid_mix: failures.append('adjustment mixing exists')
        invalid_source=await conn.fetchval("""
            SELECT COUNT(*) FROM market.certified_klines
            WHERE provider IN ('unknown','synthetic') OR source IN ('unknown','synthetic')
               OR quality_status<>'pass' OR certification_status<>'certified'
        """)
        if invalid_source: failures.append('invalid data exists in Certified Store')
        unsafe_review=await conn.fetchval("""
            SELECT COUNT(*) FROM market.research_readiness_reviews
            WHERE readiness_status='ready'
               AND (missingness_status<>'complete' OR provider_validation_status<>'pass'
                    OR (research_use_scope='return_backtest'
                        AND corporate_action_status NOT IN ('verified_no_event','event_verified_handled')))
        """)
        if unsafe_review: failures.append('unsafe ready review exists')
    finally:
        await conn.close()
    print(json.dumps(failures))

asyncio.run(main())
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("数据库 readiness 检查执行失败")
    } else {
        (ConvertFrom-Json ($DatabaseOutput -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }

    $SourceOutput = @'
import inspect, json
from app.backtest.service import BacktestService
from app.screener.engine import ScreenerEngine
from app.data.service import DataService
from app.trade.simulation_trader import SimulationTrader
failures=[]
checks=(
    (BacktestService.create_and_run,'return_backtest'),
    (ScreenerEngine._load_universe,'return_backtest'),
    (DataService.get_certified_kline,'assert_dataset_ready'),
    (SimulationTrader._resolve_market,'execution_reference'),
)
for method,token in checks:
    if token not in inspect.getsource(method): failures.append(f'{method.__qualname__} missing {token}')
print(json.dumps(failures))
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("业务门禁源码检查执行失败")
    } else {
        (ConvertFrom-Json ($SourceOutput -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }
}

if (-not (Test-Path $ProviderPython)) {
    $Failures.Add("缺少 Provider 校验环境")
} else {
    $EvidenceOutput = & $ProviderPython (Join-Path $Root "scripts\investigate_sina_20260630.py") 2>&1
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("新浪缺失调查脚本失败")
    } else {
        try {
            $Evidence = ConvertFrom-Json ($EvidenceOutput -join "`n")
            if ($Evidence.conclusion -ne "endpoint_specific_provider_missing") {
                $Failures.Add("新浪缺失原因没有明确结论")
            }
            foreach ($stock in $Evidence.stocks) {
                if ($stock.sina_archive_has_date -or -not $stock.sina_daily_has_date -or -not $stock.tencent_has_date) {
                    $Failures.Add("Provider 日期证据异常: $($stock.stock_code)")
                }
                if ($stock.amount_cross_provider_status -ne "unresolved" -or $stock.readiness_conclusion -ne "review_required") {
                    $Failures.Add("未验证 amount 被错误放行: $($stock.stock_code)")
                }
                foreach ($field in $stock.ohlcv_comparisons.PSObject.Properties) {
                    if ($field.Value.max_absolute_difference -gt $field.Value.tolerance) {
                        $Failures.Add("6月30日 OHLCV 超容差: $($stock.stock_code) $($field.Name)")
                    }
                }
            }
        } catch {
            $Failures.Add("新浪缺失调查输出不是有效 JSON")
        }
    }
}

foreach ($script in @(
    "verify_data_certification.ps1",
    "verify_execution_safety.ps1",
    "verify_certified_ingestion_pilot.ps1",
    "verify_certified_kline_store.ps1"
)) {
    $Output = & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot $script) 2>&1
    if ($LASTEXITCODE -ne 0 -or ($Output -join "`n") -notmatch "PASS") {
        $Failures.Add("既有验收失败: $script")
    }
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    $BackendTests = & python -m pytest (Join-Path $Root "backend\tests") -q 2>&1
    if ($LASTEXITCODE -ne 0) { $Failures.Add("backend 全量测试失败") }
    if (($BackendTests -join "`n") -match "\b(skipped|xfailed|xpassed)\b") { $Failures.Add("backend 存在 skip/xfail/xpass") }
    $WorkerTests = & python -m pytest (Join-Path $Root "worker\tests") -q 2>&1
    if ($LASTEXITCODE -ne 0) { $Failures.Add("worker 全量测试失败") }
    if (($WorkerTests -join "`n") -match "\b(skipped|xfailed|xpassed)\b") { $Failures.Add("worker 存在 skip/xfail/xpass") }
}

if ($Failures.Count) {
    Write-Host "FAIL" -ForegroundColor Red
    $Failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Write-Host "PASS" -ForegroundColor Green
Write-Host "Research Readiness Gate、日期归因、企业行动审核和安全回归均通过。"
exit 0
