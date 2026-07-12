#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
$Failures = [System.Collections.Generic.List[string]]::new()
Get-Content (Join-Path $Root ".env.host") -Encoding UTF8 | ForEach-Object {
  $line=$_.Trim(); $i=$line.IndexOf('='); if($line -and -not $line.StartsWith('#') -and $i -gt 0){Set-Item "Env:$($line.Substring(0,$i).Trim().TrimStart([char]0xFEFF))" $line.Substring($i+1).Trim()}
}
$env:PYTHONPATH=Join-Path $Root "backend"
$Code=@'
import asyncio,asyncpg,hashlib,json,os
from datetime import date,datetime
from decimal import Decimal
from pathlib import Path
import yaml

ROOT=Path(os.environ['PYTHONPATH']).parent
RUN='sprint13-controlled-certified-v1-run1'
START=date(2025,7,1); END=date(2026,6,30)
def norm(v):
    if isinstance(v,(date,datetime)): return v.isoformat()
    if isinstance(v,Decimal): return format(v,'f')
    return v
def stable(rows):
    data=[{k:norm(v) for k,v in sorted(dict(r).items())} for r in rows]
    data.sort(key=lambda x:json.dumps(x,sort_keys=True,default=str))
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
async def snapshots(c):
    legacy=await c.fetch("SELECT time,stock_code,period,open,high,low,close,volume,amount,turnover_rate FROM market.klines ORDER BY stock_code,period,time")
    existing=await c.fetch("SELECT stock_code,period,trading_date,adjustment,open,high,low,close,volume,amount,provider,source,batch_id,raw_hash FROM market.certified_klines WHERE created_at<(SELECT started_at FROM market.dataset_expansion_runs WHERE run_id=$1) ORDER BY stock_code,trading_date",RUN)
    allrows=await c.fetch("SELECT stock_code,period,trading_date,adjustment,open,high,low,close,volume,amount,provider,source,batch_id,raw_hash FROM market.certified_klines ORDER BY stock_code,trading_date")
    return {'legacy':stable(legacy),'existing_certified':stable(existing),'dataset':stable(allrows)}
async def inspect():
    c=await asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://'))
    failures=[]; checks={}
    try:
      manifest=yaml.safe_load((ROOT/'config/datasets/sprint13_universe.yaml').read_text(encoding='utf-8'))
      codes=[s['stock_code'] for s in manifest['stocks']]
      checks['manifest']={'count':len(codes),'frozen':manifest['frozen'],'future_returns':manifest['selection_uses_target_period_returns'],'codes':codes}
      if len(codes)!=10 or not manifest['frozen'] or manifest['selection_uses_target_period_returns'] or manifest['date_from']!='2025-07-01' or manifest['date_to']!='2026-06-30' or manifest['period']!='1d' or manifest['adjustment']!='raw': failures.append('manifest invalid')
      run=await c.fetchrow("SELECT * FROM market.dataset_expansion_runs WHERE run_id=$1",RUN)
      cps=await c.fetch("SELECT status,count(*) n FROM market.dataset_import_checkpoints WHERE run_id=$1 GROUP BY status",RUN)
      checks['checkpoints']={'run_status':run['status'] if run else None,'counts':{r['status']:r['n'] for r in cps},'total':sum(r['n'] for r in cps)}
      if not run or sum(r['n'] for r in cps)!=120 or any(r['status'] not in ('certified','rejected','fetch_failed','validation_failed','review_required') for r in cps): failures.append('checkpoint terminal state invalid')
      coverage=await c.fetch("""SELECT s.code,COUNT(k.*) rows,(SELECT COUNT(*) FROM market.trading_calendar c WHERE c.exchange=split_part(s.code,'.',2) AND c.trading_date BETWEEN $2 AND $3 AND c.is_trading_day AND c.status='confirmed') expected FROM unnest($1::varchar[]) s(code) LEFT JOIN market.certified_klines k ON k.stock_code=s.code AND k.period='1d' AND k.adjustment='raw' AND k.trading_date BETWEEN $2 AND $3 GROUP BY s.code""",codes,START,END)
      checks['coverage']={r['code']:{'rows':r['rows'],'expected':r['expected'],'ratio':r['rows']/r['expected']} for r in coverage}
      invalid=await c.fetchval("SELECT COUNT(*) FROM market.certified_klines WHERE stock_code=ANY($1::varchar[]) AND (provider IN ('unknown','synthetic') OR source IN ('unknown','synthetic') OR certification_status<>'certified' OR quality_status<>'pass' OR adjustment<>'raw')",codes)
      if invalid: failures.append('invalid certified rows')
      calendars=await c.fetch("SELECT exchange,count(*) n,count(*) filter(where is_trading_day and status='confirmed') open FROM market.trading_calendar WHERE trading_date BETWEEN $1 AND $2 GROUP BY exchange",START,END)
      dates=await c.fetch("SELECT stock_code,count(*) n,count(*) filter(where status='unresolved') unresolved FROM market.research_date_reviews WHERE dataset_scope=$1 GROUP BY stock_code",RUN)
      security=await c.fetch("SELECT stock_code,count(*) n FROM market.security_status_reviews WHERE run_id=$1 GROUP BY stock_code",RUN)
      checks['calendar_status']={'calendar':{r['exchange']:{'days':r['n'],'open':r['open']} for r in calendars},'date_reviews':{r['stock_code']:{'days':r['n'],'unresolved':r['unresolved']} for r in dates},'security_reviews':{r['stock_code']:r['n'] for r in security}}
      if len(calendars)!=2 or any(r['n']!=365 for r in calendars) or len(dates)!=10 or any(r['n']!=365 for r in dates) or len(security)!=10: failures.append('calendar/security/date review coverage invalid')
      if any(r['unresolved'] for r in dates): failures.append('unresolved trading dates remain')
      providers=await c.fetch("SELECT stock_code,count(*) n,count(*) filter(where result='PASS') passed FROM market.provider_validation_reviews WHERE run_id=$1 GROUP BY stock_code",RUN)
      second_written=await c.fetchval("SELECT COUNT(*) FROM market.certified_klines WHERE provider='tencent' OR source LIKE 'tencent%'")
      checks['provider_validation']={r['stock_code']:{'samples':r['n'],'pass':r['passed']} for r in providers}; checks['secondary_written']=second_written
      if len(providers)!=10 or any(r['n']!=12 for r in providers) or second_written: failures.append('secondary provider validation invalid')
      actions=await c.fetch("SELECT stock_code,verification_status,count(*) n FROM market.corporate_action_reviews WHERE reviewer_version='sprint13-controlled-expansion-v1' GROUP BY stock_code,verification_status")
      checks['corporate_actions']={r['stock_code']:{'status':r['verification_status'],'reviews':r['n']} for r in actions}
      if len(actions)!=10: failures.append('corporate action discovery coverage invalid')
      if any(r['verification_status']=='unresolved' for r in actions): failures.append('corporate action reviews remain unresolved')
      readiness=await c.fetch("SELECT stock_code,requirement_profile,research_use_scope,readiness_status,date_from,date_to FROM market.research_readiness_reviews WHERE reviewer_version='sprint13-controlled-expansion-v1' ORDER BY stock_code,requirement_profile")
      checks['readiness']=[dict(r) for r in readiness]
      if len(readiness)!=30 or any(r['date_from']!=START or r['date_to']!=END for r in readiness) or any(r['readiness_status']=='ready' for r in readiness) or any(r['requirement_profile']=='EXECUTION_REFERENCE_V1' and r['readiness_status']!='rejected' for r in readiness): failures.append('readiness isolation invalid')
      locks=['CERTIFIED_BACKTEST_EXECUTION_ENABLED','CERTIFIED_SCREENER_OUTPUT_ENABLED','TRADING_EXECUTION_ENABLED','LIVE_TRADING_ENABLED','AI_ORDER_ENABLED','ALLOW_SCHEDULED_ORDER']
      lock_values={k:os.environ.get(k,'').lower() for k in locks}; checks['locks']=lock_values
      if any(v!='false' for v in lock_values.values()): failures.append('release lock enabled')
      checks['orders']=await c.fetchval('SELECT COUNT(*) FROM trade.orders')
      checks['snapshots']=await snapshots(c)
      checks['dataset_hash']=checks['snapshots']['dataset']
    finally: await c.close()
    return failures,checks
async def main():
    failures,before=await inspect()
    print('S13_BEFORE='+json.dumps({'failures':failures,'checks':before},ensure_ascii=False,default=str,sort_keys=True))
asyncio.run(main())
'@
$Before=$Code|&$Python - 2>&1; if($LASTEXITCODE -ne 0){$Failures.Add('pre-rerun inspection failed')}
$BeforeLine=$Before|Where-Object{$_ -like 'S13_BEFORE=*'}|Select-Object -Last 1
if(-not $BeforeLine){$Failures.Add('missing pre-rerun summary')}else{$BeforeJson=ConvertFrom-Json $BeforeLine.Substring(11);$BeforeJson.failures|ForEach-Object{$Failures.Add($_)}}
$Import=&$Python (Join-Path $Root 'backend/scripts/import_sprint13_dataset.py') 2>&1
if($LASTEXITCODE -ne 0){$Failures.Add('idempotent importer rerun failed')}
$After=$Code|&$Python - 2>&1; if($LASTEXITCODE -ne 0){$Failures.Add('post-rerun inspection failed')}
$AfterLine=$After|Where-Object{$_ -like 'S13_BEFORE=*'}|Select-Object -Last 1
if(-not $AfterLine){$Failures.Add('missing post-rerun summary')}else{$AfterJson=ConvertFrom-Json $AfterLine.Substring(11);$AfterJson.failures|ForEach-Object{$Failures.Add($_)}}
if($BeforeJson.checks.snapshots.legacy -ne $AfterJson.checks.snapshots.legacy){$Failures.Add('legacy snapshot changed')}
if($BeforeJson.checks.snapshots.existing_certified -ne $AfterJson.checks.snapshots.existing_certified){$Failures.Add('existing certified snapshot changed')}
if($BeforeJson.checks.dataset_hash -ne $AfterJson.checks.dataset_hash){$Failures.Add('dataset hash is not deterministic')}
$SavedErrorAction=$ErrorActionPreference;$ErrorActionPreference='Continue'
$Prior=&powershell -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts/verify_corporate_action_pit.ps1') 2>&1
$ErrorActionPreference=$SavedErrorAction
if($LASTEXITCODE -ne 0 -or ($Prior-join"`n")-notmatch'PASS'){$Failures.Add('existing verification chain failed')}
Write-Host ('SPRINT13_JSON='+(@{before=$BeforeJson;after=$AfterJson;failures=@($Failures)}|ConvertTo-Json -Depth 12 -Compress))
if($Failures.Count){Write-Host 'FAIL' -ForegroundColor Red;$Failures|ForEach-Object{Write-Host "- $_"};exit 1}
Write-Host 'PASS' -ForegroundColor Green
