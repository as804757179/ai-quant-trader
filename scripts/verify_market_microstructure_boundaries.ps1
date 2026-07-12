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
$SummaryPattern = '\b(?:skipped|xfailed|xpassed)\b'

foreach ($case in @(
    @{ Text = "1 skipped"; Expected = $true },
    @{ Text = "1 xfailed"; Expected = $true },
    @{ Text = "1 xpassed"; Expected = $true },
    @{ Text = "19 passed"; Expected = $false }
)) {
    if (($case.Text -match $SummaryPattern) -ne $case.Expected) {
        $Failures.Add("测试摘要检测器自测失败: $($case.Text)")
    }
}

$MarketVerifier = Join-Path $PSScriptRoot "verify_backtest_market_rules.ps1"
if ([IO.File]::ReadAllBytes($MarketVerifier) -contains 8) {
    $Failures.Add("Worker skip 检测器仍包含退格字符")
}

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
import asyncio, copy, inspect, json
from datetime import date
from decimal import Decimal
from app.backtest.accounting_validation import validate_accounting_scenarios
from app.backtest.engine import BacktestEngine
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
    if hashes[0]=='6a75636c1e812ca7b716e49bc41e9367b8113a02a5074576e15c6e5f3b3e81bc': failures.append('Sprint11 result hash was silently reused')
    if first['engine_reference_differences']: failures.append(f"baseline differences: {first['engine_reference_differences']}")
    accounting=first['accounting_scenarios']
    if len(accounting['scenarios'])!=19 or accounting['differences']: failures.append(f"accounting differences: {accounting['differences']}")
    scenarios=accounting['scenarios']
    if scenarios['odd_lot_140_full_sell']['final_position']!={}: failures.append('140 shares cannot be fully sold')
    if scenarios['odd_lot_140_sell_round_lot']['final_position'].get('total_qty')!=40: failures.append('140 -> 100 sell does not retain 40')
    if scenarios['odd_lot_40_full_sell']['final_position']!={}: failures.append('40-share odd lot cannot be fully sold')
    if scenarios['odd_lot_40_partial_rejected']['failed_reasons']!=['INVALID_ODD_LOT_SELL']: failures.append('partial odd lot was not rejected')
    if scenarios['odd_lot_split_rejected']['failed_reasons']!=['INVALID_ODD_LOT_SELL','INVALID_ODD_LOT_SELL']: failures.append('split odd lot was not rejected')
    if scenarios['buy_odd_lot_40_rejected']['failed_reasons']!=['INVALID_QUANTITY']: failures.append('40-share buy was not rejected')
    if scenarios['buy_140_normalized_to_100']['final_position'].get('total_qty')!=100: failures.append('140-share buy normalization is not explicit')
    micro=first['lineage'].get('market_microstructure',{})
    expected={'buy_lot_size':100,'sell_lot_size':100,'odd_lot_sell_policy':'FULL_ODD_LOT_ONLY','price_tick':'0.01','price_rounding_mode':'ROUND_HALF_UP','price_limit_formula_version':'PREV_CLOSE_RATE_TICK_V1'}
    if micro!=expected: failures.append(f'microstructure lineage mismatch: {micro}')
    altered=copy.deepcopy(first['lineage']); altered['market_microstructure']['price_tick']='0.001'
    if _hash(first['lineage'])==_hash(altered): failures.append('price tick change does not affect hash')
    altered=copy.deepcopy(first['lineage']); altered['market_microstructure']['odd_lot_sell_policy']='OTHER_VERSION'
    if _hash(first['lineage'])==_hash(altered): failures.append('odd-lot policy change does not affect hash')
    registry=AshareMarketRuleRegistry(); status=SecurityStatusSnapshot('603986.SH','SH','MAIN','NORMAL',date(2026,6,1),date(2026,6,30),False,False,True,'SSE',registry.SSE_RULES_2023,'main-v1')
    rules=registry.resolve(date(2026,6,2),status)
    if registry.price_limits(10.03,0.10,rules)!=(Decimal('11.03'),Decimal('9.03')): failures.append('main-board tick rounding failed')
    invalid=SecurityStatusSnapshot('603986.SH','SH','MAIN','NORMAL',date(2026,6,1),date(2026,6,30),False,False,False,'SSE',registry.SSE_RULES_2023,'invalid-prev-close-v1')
    try: registry.resolve(date(2026,6,2),invalid); failures.append('invalid previous close was released')
    except MarketRuleError: pass
    source=inspect.getsource(BacktestEngine)
    if '0.999' in source or '1.001' in source: failures.append('fuzzy price-limit tolerance remains in trusted engine')
    gate=ResearchReadinessService(); fields=list(ResearchDataRequirementProfile.get('OHLCV_RETURN_V1').required_fields)
    try:
        await gate.assert_ready(['300502.SZ'],period='1d',adjustment='raw',research_use_scope='return_backtest',requirement_profile='OHLCV_RETURN_V1',required_fields=fields,start_date=date(2026,6,1),end_date=date(2026,6,30))
        failures.append('300502 was incorrectly released')
    except ValueError: pass
    print('SPRINT111_JSON='+json.dumps({'failures':failures,'result_hash':hashes[0]}))

asyncio.run(main())
'@ | & $BackendPython - 2>&1
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("市场微观规则验证执行失败")
    } else {
        $SummaryLine = $ValidationOutput | Where-Object { $_ -like "SPRINT111_JSON=*" } | Select-Object -Last 1
        if (-not $SummaryLine) {
            $Failures.Add("市场微观规则验证未输出摘要")
        } else {
            $Summary = ConvertFrom-Json $SummaryLine.Substring("SPRINT111_JSON=".Length)
            $Summary.failures | ForEach-Object { $Failures.Add($_) }
            Write-Host "result_hash=$($Summary.result_hash)"
        }
    }
}

$PriorOutput = & powershell -ExecutionPolicy Bypass -File $MarketVerifier 2>&1
if ($LASTEXITCODE -ne 0 -or ($PriorOutput -join "`n") -notmatch "PASS") {
    $Failures.Add("既有完整验收链失败: verify_backtest_market_rules.ps1")
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    $BackendTests = & python -m pytest (Join-Path $Root "backend\tests") -q 2>&1
    if ($LASTEXITCODE -ne 0) { $Failures.Add("backend 全量测试失败") }
    if (($BackendTests -join "`n") -match $SummaryPattern) { $Failures.Add("backend 存在 skip/xfail/xpass") }
    $WorkerTests = & python -m pytest (Join-Path $Root "worker\tests") -q 2>&1
    if ($LASTEXITCODE -ne 0) { $Failures.Add("worker 全量测试失败") }
    if (($WorkerTests -join "`n") -match $SummaryPattern) { $Failures.Add("worker 存在 skip/xfail/xpass") }
}

if ($Failures.Count) {
    Write-Host "FAIL" -ForegroundColor Red
    $Failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Write-Host "PASS" -ForegroundColor Green
Write-Host "skip 检测、买入整手、卖出零股、价格 tick、Hash 与全部安全回归均通过。"
exit 0
