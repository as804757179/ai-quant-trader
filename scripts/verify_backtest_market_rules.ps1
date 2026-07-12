#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Failures = [System.Collections.Generic.List[string]]::new()
$env:PYTHONDONTWRITEBYTECODE = "1"
$TestSummaryPattern = '\b(?:skipped|xfailed|xpassed)\b'

foreach ($case in @(
    @{ Text = "1 skipped"; Expected = $true },
    @{ Text = "1 xfailed"; Expected = $true },
    @{ Text = "1 xpassed"; Expected = $true },
    @{ Text = "19 passed"; Expected = $false }
)) {
    if (($case.Text -match $TestSummaryPattern) -ne $case.Expected) {
        $Failures.Add("测试摘要检测器自测失败: $($case.Text)")
    }
}

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
    $ValidationOutput = @'
import asyncio, json
from datetime import date
from app.backtest.integrity_validation import validate_backtest_integrity, _hash
from app.backtest.market_rules import AshareMarketRuleRegistry, MarketRuleError, SecurityStatusSnapshot
from app.data.research_profiles import ResearchDataRequirementProfile
from app.data.research_readiness import ResearchReadinessService

async def main():
    failures=[]
    runs=[await validate_backtest_integrity() for _ in range(3)]
    reverse=await validate_backtest_integrity(['603986.SH','300308.SZ'])
    hashes=[item['result_hash'] for item in runs]+[reverse['result_hash']]
    first=runs[0]
    if len(set(hashes))!=1: failures.append(f'nondeterministic hashes: {hashes}')
    if hashes[0]=='0bdf29f536408b61ac190d8c5674f87c7fd56df5553410c84e164a2101c7daff': failures.append('Sprint10 result hash was silently reused')
    if first['engine_reference_differences']: failures.append(f"baseline differences: {first['engine_reference_differences']}")
    accounting=first['accounting_scenarios']
    if len(accounting['scenarios'])!=19 or accounting['differences']: failures.append(f"accounting differences: {accounting['differences']}")
    expected_rejections={
        'insufficient_cash':'INSUFFICIENT_CASH',
        'oversell':'INSUFFICIENT_POSITION',
        't_plus_one_same_execution_day':'INSUFFICIENT_POSITION',
        'suspended':'SUSPENDED',
        'limit_up_buy':'LIMIT_UP',
        'limit_down_sell':'LIMIT_DOWN',
    }
    for scenario,reason in expected_rejections.items():
        if reason not in accounting['scenarios'][scenario]['failed_reasons']: failures.append(f'{scenario} did not reject with {reason}')
    boundary=accounting['scenarios']['transfer_fee_effective_boundary']
    if boundary['before_effective_date']!='blocked' or boundary['on_effective_date_rate']!=0.00001: failures.append('transfer fee date boundary is invalid')
    costs=first['lineage']['cost_config']
    if costs.get('transfer_fee_implemented') is not True or costs.get('transfer_fee_rate')!=0.00001: failures.append('transfer fee is not implemented')
    if not first['lineage'].get('market_rule_versions') or not first['lineage'].get('calendar'): failures.append('market rule/calendar lineage is incomplete')
    if _hash({'rules':['v1']})==_hash({'rules':['v2']}): failures.append('rule version does not affect hash')
    registry=AshareMarketRuleRegistry()
    official=('sse.com.cn','szse.cn','chinaclear.cn','chinatax.gov.cn')
    for rule in registry.records():
        if not any(domain in rule['source_reference'] for domain in official): failures.append(f"non-official rule source: {rule['rule_version']}")
    unknown=SecurityStatusSnapshot('603986.SH','SH','MAIN','UNKNOWN',date(2026,6,1),date(2026,6,30),False,False,True,'SSE',registry.SSE_RULES_2023,'unknown-v1')
    try: registry.resolve(date(2026,6,2),unknown); failures.append('unknown security status was released')
    except MarketRuleError: pass
    gate=ResearchReadinessService(); fields=list(ResearchDataRequirementProfile.get('OHLCV_RETURN_V1').required_fields)
    try:
        await gate.assert_ready(['300502.SZ'],period='1d',adjustment='raw',research_use_scope='return_backtest',requirement_profile='OHLCV_RETURN_V1',required_fields=fields,start_date=date(2026,6,1),end_date=date(2026,6,30))
        failures.append('300502 was incorrectly released')
    except ValueError: pass
    print('SPRINT11_JSON='+json.dumps({'failures':failures,'result_hash':hashes[0]}))

asyncio.run(main())
'@ | & $BackendPython - 2>&1
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("市场规则与会计验证执行失败")
    } else {
        $SummaryLine = $ValidationOutput | Where-Object { $_ -like "SPRINT11_JSON=*" } | Select-Object -Last 1
        if (-not $SummaryLine) {
            $Failures.Add("市场规则验证未输出摘要")
        } else {
            $Summary = ConvertFrom-Json $SummaryLine.Substring("SPRINT11_JSON=".Length)
            $Summary.failures | ForEach-Object { $Failures.Add($_) }
            Write-Host "result_hash=$($Summary.result_hash)"
        }
    }

    $DatabaseOutput = @'
import asyncio, json, os, asyncpg
async def main():
    failures=[]
    conn=await asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://'))
    try:
        rows=await conn.fetch("""SELECT exchange,COUNT(*) n,COUNT(*) FILTER(WHERE status='confirmed' AND source IN ('sse','szse') AND source_reference IS NOT NULL) certified FROM market.trading_calendar WHERE trading_date BETWEEN '2026-06-01' AND '2026-06-30' GROUP BY exchange ORDER BY exchange""")
        if [(r['exchange'],r['n'],r['certified']) for r in rows]!=[('SH',30,30),('SZ',30,30)]: failures.append('certified calendar coverage is incomplete')
        if await conn.fetchval("SELECT is_trading_day FROM market.trading_calendar WHERE exchange='SH' AND trading_date='2026-06-19'"): failures.append('official holiday was treated as trading day')
    finally: await conn.close()
    print(json.dumps(failures))
asyncio.run(main())
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("认证交易日历数据库检查失败")
    } else {
        (ConvertFrom-Json ($DatabaseOutput -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }

    $SourceOutput = @'
import inspect, json
from app.backtest.calendar import build_trading_days
from app.backtest.integrity_validation import _canonical_dataset_records, _bars_from_rows
from app.backtest.trusted_calendar import TrustedTradingCalendar
failures=[]
calendar=inspect.getsource(build_trading_days)
validation=inspect.getsource(TrustedTradingCalendar.get_days)
if 'require_certified' not in calendar or 'certified trading calendar is required' not in calendar: failures.append('trusted calendar fail-closed path is missing')
if 'market.trading_calendar' not in validation: failures.append('trusted calendar does not read certified calendar')
if 'sorted' not in inspect.getsource(_canonical_dataset_records): failures.append('dataset records are not explicitly sorted')
reader=inspect.getsource(_bars_from_rows)
if 'amount' not in reader or 'turnover_rate' not in reader: failures.append('unauthorized field assertion is missing')
print(json.dumps(failures))
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("可信链路静态检查失败")
    } else {
        (ConvertFrom-Json ($SourceOutput -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }
}

$PriorOutput = & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_backtest_integrity.ps1") 2>&1
if ($LASTEXITCODE -ne 0 -or ($PriorOutput -join "`n") -notmatch "PASS") {
    $Failures.Add("既有完整验收链失败: verify_backtest_integrity.ps1")
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    $BackendTests = & python -m pytest (Join-Path $Root "backend\tests") -q 2>&1
    if ($LASTEXITCODE -ne 0) { $Failures.Add("backend 全量测试失败") }
    if (($BackendTests -join "`n") -match $TestSummaryPattern) { $Failures.Add("backend 存在 skip/xfail/xpass") }
    $WorkerTests = & python -m pytest (Join-Path $Root "worker\tests") -q 2>&1
    if ($LASTEXITCODE -ne 0) { $Failures.Add("worker 全量测试失败") }
    if (($WorkerTests -join "`n") -match $TestSummaryPattern) { $Failures.Add("worker 存在 skip/xfail/xpass") }
}

if ($Failures.Count) {
    Write-Host "FAIL" -ForegroundColor Red
    $Failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Write-Host "PASS" -ForegroundColor Green
Write-Host "市场规则、过户费、认证日历、复杂会计、Hash 和全部安全回归均通过。"
exit 0
