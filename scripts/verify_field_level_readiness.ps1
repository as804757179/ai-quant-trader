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
        profiles=await conn.fetch("SELECT requirement_profile,required_fields,policy_version FROM market.research_requirement_profiles WHERE enabled")
        names={r['requirement_profile'] for r in profiles}
        if not {'OHLCV_RETURN_V1','AMOUNT_FACTOR_V1','EXECUTION_REFERENCE_V1'}.issubset(names):
            failures.append(f'invalid profiles: {names}')
        owner=await conn.fetchval("SELECT tableowner FROM pg_tables WHERE schemaname='market' AND tablename='research_requirement_profiles'")
        if owner!='quant_admin': failures.append('profile table owner is invalid')
        incomplete=await conn.fetchval("""
            SELECT COUNT(*) FROM market.research_readiness_reviews
            WHERE requirement_profile IS NULL OR required_fields IS NULL
               OR validated_fields IS NULL OR unresolved_fields IS NULL
               OR rejected_fields IS NULL OR policy_version IS NULL
        """)
        if incomplete: failures.append(f'incomplete field reviews: {incomplete}')
        ready_ohlcv=await conn.fetch("""
            SELECT stock_code FROM market.research_readiness_reviews
            WHERE research_use_scope='return_backtest' AND requirement_profile='OHLCV_RETURN_V1'
              AND readiness_status='ready' ORDER BY stock_code
        """)
        if [r['stock_code'] for r in ready_ohlcv]!=['300308.SZ','603986.SH']:
            failures.append('clean OHLCV ready sample is invalid')
        status_300502=await conn.fetchval("""
            SELECT readiness_status FROM market.research_readiness_reviews
            WHERE stock_code='300502.SZ' AND research_use_scope='return_backtest'
              AND requirement_profile='OHLCV_RETURN_V1'
        """)
        if status_300502!='rejected': failures.append('300502 OHLCV return review is not rejected')
        if await conn.fetchval("SELECT COUNT(*) FROM market.research_readiness_reviews WHERE requirement_profile='AMOUNT_FACTOR_V1' AND readiness_status='ready'"):
            failures.append('AMOUNT_FACTOR_V1 was incorrectly released')
        if await conn.fetchval("SELECT COUNT(*) FROM market.research_readiness_reviews WHERE requirement_profile='EXECUTION_REFERENCE_V1' AND readiness_status='ready'"):
            failures.append('EXECUTION_REFERENCE_V1 was incorrectly released')
        unsafe=await conn.fetchval("""
            SELECT COUNT(*) FROM market.research_readiness_reviews r
            WHERE r.readiness_status='ready' AND (
              EXISTS (SELECT 1 FROM jsonb_array_elements_text(r.unresolved_fields) f WHERE f.value IN (SELECT jsonb_array_elements_text(r.required_fields)))
              OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(r.rejected_fields) f WHERE f.value IN (SELECT jsonb_array_elements_text(r.required_fields)))
            )
        """)
        if unsafe: failures.append(f'unsafe field-level ready reviews: {unsafe}')
        store=await conn.fetchrow("SELECT COUNT(*) FILTER(WHERE research_readiness_status='ready') ready, COUNT(*) FILTER(WHERE research_readiness_status='review_required') pending FROM market.certified_klines")
        if store['ready']!=0 or store['pending']<63: failures.append('Store rows were incorrectly made globally ready')
        invalid=await conn.fetchval("""
            SELECT COUNT(*) FROM market.certified_klines
            WHERE provider IN ('unknown','synthetic') OR source IN ('unknown','synthetic')
               OR certification_status<>'certified' OR quality_status<>'pass'
        """)
        if invalid: failures.append('invalid source is certified')
    finally:
        await conn.close()
    print(json.dumps(failures))

asyncio.run(main())
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("字段级数据库检查执行失败")
    } else {
        (ConvertFrom-Json ($DatabaseOutput -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }

    $GateOutput = @'
import asyncio, json
from datetime import date
from app.data.research_readiness import ResearchReadinessService
from app.data.research_profiles import ResearchDataRequirementProfile

async def main():
    failures=[]; gate=ResearchReadinessService(); start=date(2026,6,1); end=date(2026,6,30)
    def fields(name): return list(ResearchDataRequirementProfile.get(name).required_fields)
    try: ResearchDataRequirementProfile.get(None); failures.append('missing profile did not fail')
    except ValueError: pass
    try:
        await gate.assert_ready(['300308.SZ','603986.SH'],period='1d',adjustment='raw',research_use_scope='return_backtest',requirement_profile='OHLCV_RETURN_V1',required_fields=fields('OHLCV_RETURN_V1'),start_date=start,end_date=end)
    except ValueError as exc: failures.append(f'clean OHLCV sample blocked: {exc}')
    for code,profile,scope in (
        ('300502.SZ','OHLCV_RETURN_V1','return_backtest'),
        ('300308.SZ','AMOUNT_FACTOR_V1','return_backtest'),
        ('300308.SZ','EXECUTION_REFERENCE_V1','execution_reference'),
    ):
        try:
            await gate.assert_ready([code],period='1d',adjustment='raw',research_use_scope=scope,requirement_profile=profile,required_fields=fields(profile),start_date=start,end_date=end)
            failures.append(f'unsafe profile released: {code}/{profile}')
        except ValueError: pass
    print(json.dumps(failures))
asyncio.run(main())
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("字段级 Gate 集成检查失败")
    } else {
        (ConvertFrom-Json ($GateOutput -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }

    $SourceOutput = @'
import inspect, json
from app.backtest.service import BacktestService
from app.screener.engine import ScreenerEngine
from app.trade.simulation_trader import SimulationTrader
from app.strategy.catalog import STRATEGY_CATALOG
failures=[]
backtest=inspect.getsource(BacktestService._load_bars)
if 'requirement_profile' not in backtest or 'required_fields' not in backtest: failures.append('Backtest reader does not declare fields')
screener=inspect.getsource(ScreenerEngine._load_universe)
if 'requirement_profile' not in screener or 'required_fields' not in screener: failures.append('Screener does not declare fields')
if 'EXECUTION_REFERENCE_V1' not in inspect.getsource(SimulationTrader._resolve_market): failures.append('Simulation profile is missing')
for name,meta in STRATEGY_CATALOG.items():
    if not meta.get('requirement_profile') or not meta.get('required_fields'): failures.append(f'strategy declaration missing: {name}')
print(json.dumps(failures))
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("调用方 Profile 声明检查失败")
    } else {
        (ConvertFrom-Json ($SourceOutput -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }
}

$PriorOutput = & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_research_readiness.ps1") 2>&1
if ($LASTEXITCODE -ne 0 -or ($PriorOutput -join "`n") -notmatch "PASS") {
    $Failures.Add("既有完整验收链失败: verify_research_readiness.ps1")
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
Write-Host "字段级 Profile、Scoped Ready、企业行动阻断和全部安全回归均通过。"
exit 0
