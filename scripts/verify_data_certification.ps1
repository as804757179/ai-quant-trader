#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONDONTWRITEBYTECODE = "1"
Get-Content (Join-Path $Root ".env.host") -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim(); $index = $line.IndexOf("=")
    if ($line -and -not $line.StartsWith("#") -and $index -gt 0) {
        Set-Item -Path "Env:$($line.Substring(0, $index).Trim().TrimStart([char]0xFEFF))" -Value $line.Substring($index + 1).Trim()
    }
}
$python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Write-Output "FAIL missing backend python"; exit 1 }
$result = @'
import asyncio, os, asyncpg, sys
async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg://','postgresql://'))
    failures=[]
    for table in ('data_batches','kline_provenance'):
        exists=await conn.fetchval("select to_regclass('market.' || $1) is not null", table)
        if not exists: failures.append('missing '+table)
    if not failures:
        total=await conn.fetchval("select count(*) from market.klines")
        provenance=await conn.fetchval("select count(*) from market.kline_provenance")
        certified_legacy=await conn.fetchval("select count(*) from market.kline_provenance where source='unknown' and certification_status='certified'")
        synthetic_certified=await conn.fetchval("select count(*) from market.kline_provenance where is_synthetic and certification_status='certified'")
        if total != provenance: failures.append('provenance row count mismatch')
        if certified_legacy: failures.append('unknown data is certified')
        if synthetic_certified: failures.append('synthetic data is certified')
    await conn.close()
    if failures:
        print('FAIL')
        for item in failures: print('- '+item)
        return 1
    print('PASS')
    return 0
sys.exit(asyncio.run(main()))
'@ | & $python -
$exitCode = $LASTEXITCODE
$result | ForEach-Object { Write-Output $_ }
exit $exitCode
