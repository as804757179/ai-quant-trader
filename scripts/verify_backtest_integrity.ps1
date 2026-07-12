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
    $ValidationOutput = @'
import asyncio, json
from datetime import date
from app.backtest.integrity_validation import validate_backtest_integrity
from app.data.research_profiles import ResearchDataRequirementProfile
from app.data.research_readiness import ResearchReadinessService

async def main():
    failures=[]
    runs=[await validate_backtest_integrity() for _ in range(3)]
    reverse=await validate_backtest_integrity(['603986.SH','300308.SZ'])
    hashes=[item['result_hash'] for item in runs]+[reverse['result_hash']]
    if len(set(hashes))!=1: failures.append(f'result hash is not deterministic: {hashes}')
    first=runs[0]
    if first['lineage']['stock_codes']!=['300308.SZ','603986.SH']: failures.append('validation universe is invalid')
    if first['lineage']['date_from']!='2026-06-01' or first['lineage']['date_to']!='2026-06-30': failures.append('validation date range is invalid')
    if first['lineage']['adjustment']!='raw' or first['lineage']['requirement_profile']!='OHLCV_RETURN_V1': failures.append('profile declaration is invalid')
    if len(first['lineage']['raw_hashes'])!=42: failures.append('certified lineage does not contain 42 raw hashes')
    if first['engine_reference_differences']: failures.append(f"engine/reference differences: {first['engine_reference_differences']}")
    if not all(first[name] for name in ('validation_only','not_for_investment','sample_size_insufficient')): failures.append('validation safety labels are incomplete')
    for name in ('dual_ma_validation','accounting_baseline_engine'):
        result=first[name]
        for signal in result['signal_audit']:
            if signal['information_cutoff']!=signal['signal_date']: failures.append(f'{name}: information cutoff mismatch')
            if signal['execution_date']<=signal['signal_date']: failures.append(f'{name}: same-day execution detected')
            if signal['quantity']%100: failures.append(f'{name}: non-lot quantity detected')
        for audit in result['execution_audit']:
            if audit['execution_price_source']!='next_trading_day_open': failures.append(f'{name}: execution model mismatch')
        if any(trade['quantity']%100 for trade in result['trades']): failures.append(f'{name}: trade quantity violates lot size')
    cost=first['lineage']['cost_config']
    expected={'commission_rate':0.003,'stamp_duty_rate_sell':0.0005,'transfer_fee_rate':0.00001,'slippage_rate':0.002,'minimum_commission':5.0,'lot_size':100}
    if any(cost.get(key)!=value for key,value in expected.items()): failures.append('cost configuration mismatch')
    if cost.get('transfer_fee_implemented') is not True: failures.append('transfer fee is not implemented')
    if not first['lineage'].get('readiness_review_ids') or not first['lineage'].get('certified_batch_ids'): failures.append('lineage identifiers are incomplete')
    gate=ResearchReadinessService()
    fields=list(ResearchDataRequirementProfile.get('OHLCV_RETURN_V1').required_fields)
    try:
        await gate.assert_ready(['300502.SZ'],period='1d',adjustment='raw',research_use_scope='return_backtest',requirement_profile='OHLCV_RETURN_V1',required_fields=fields,start_date=date(2026,6,1),end_date=date(2026,6,30))
        failures.append('300502 was incorrectly released')
    except ValueError:
        pass
    print('SPRINT10_JSON='+json.dumps({'failures':failures,'hashes':hashes,'result_hash':hashes[0]}))

asyncio.run(main())
'@ | & $BackendPython - 2>&1
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("回测完整性验证执行失败")
    } else {
        $SummaryLine = $ValidationOutput | Where-Object { $_ -like "SPRINT10_JSON=*" } | Select-Object -Last 1
        if (-not $SummaryLine) {
            $Failures.Add("回测完整性验证未输出摘要")
        } else {
            $Summary = ConvertFrom-Json $SummaryLine.Substring("SPRINT10_JSON=".Length)
            $Summary.failures | ForEach-Object { $Failures.Add($_) }
            Write-Host "result_hash=$($Summary.result_hash)"
        }
    }

    $SourceOutput = @'
import inspect, json
from app.backtest.service import BacktestService
from app.data.certified_kline_repository import CertifiedKlineRepository
failures=[]
repository=inspect.getsource(CertifiedKlineRepository.get_bars_for_profile)
service=inspect.getsource(BacktestService._load_bars)
if 'market.certified_klines' not in repository: failures.append('repository does not read Certified Store')
if 'market.klines' in repository: failures.append('repository reads legacy store')
if 'amount,' in repository or 'turnover_rate,' in repository: failures.append('OHLCV reader selects unauthorized fields')
if 'get_bars_for_profile' not in service: failures.append('Backtest service bypasses profile reader')
print(json.dumps(failures))
'@ | & $BackendPython -
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("数据读取路径静态检查失败")
    } else {
        (ConvertFrom-Json ($SourceOutput -join "`n")) | ForEach-Object { $Failures.Add($_) }
    }
}

$PriorOutput = & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_field_level_readiness.ps1") 2>&1
if ($LASTEXITCODE -ne 0 -or ($PriorOutput -join "`n") -notmatch "PASS") {
    $Failures.Add("既有完整验收链失败: verify_field_level_readiness.ps1")
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
Write-Host "固定样本、时序、A股约束、独立参考、确定性、血缘与全部安全回归均通过。"
exit 0
