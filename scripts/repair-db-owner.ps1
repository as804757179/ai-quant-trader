#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$EnvFile = ".env.host",
    [string]$AdminDatabaseUrl = $env:DB_ADMIN_DATABASE_URL,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $Root $EnvFile
if (-not (Test-Path $envPath)) { Write-Output "OWNER_REPAIR_FAILED missing environment file"; exit 1 }
Get-Content $envPath -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim(); $index = $line.IndexOf("=")
    if ($line -and -not $line.StartsWith("#") -and $index -gt 0) {
        Set-Item -Path "Env:$($line.Substring(0, $index).Trim().TrimStart([char]0xFEFF))" -Value $line.Substring($index + 1).Trim()
    }
}

$backendPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPy)) { Write-Output "OWNER_REPAIR_FAILED missing Backend Python environment"; exit 1 }
if (-not $env:DATABASE_URL) { Write-Output "OWNER_REPAIR_FAILED missing DATABASE_URL"; exit 1 }

$env:DB_OWNER_ADMIN_URL = $AdminDatabaseUrl
$env:DB_OWNER_CHECK_ONLY = if ($CheckOnly) { "true" } else { "false" }
$output = @'
import asyncio
import os
import sys
import asyncpg

TARGETS = (
    "backtest.results",
    "trade.orders",
    "market.quotes",
    "market.fund_flows",
    "market.quote_batches",
    "market.quote_provenance",
    "audit.operation_logs",
)

def normalize(url):
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)

async def owner_status(url):
    conn = await asyncpg.connect(normalize(url), timeout=10)
    try:
        expected = await conn.fetchval("SELECT current_user")
        rows = []
        for target in TARGETS:
            schema, table = target.split(".")
            row = await conn.fetchrow("""
                SELECT c.relowner::regrole::text AS table_owner
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = $1 AND c.relname = $2
            """, schema, table)
            if row is None:
                raise RuntimeError(f"{target} does not exist")
            rows.append((target, row["table_owner"]))
        return expected, rows
    finally:
        await conn.close()

async def main():
    app_url = os.environ["DATABASE_URL"]
    expected, statuses = await owner_status(app_url)
    mismatches = [(target, owner) for target, owner in statuses if owner != expected]
    for target, owner in statuses:
        print(f"OWNER_CHECK table={target} owner={owner} expected={expected} status={'PASS' if owner == expected else 'FAIL'}")
    if not mismatches:
        return 0
    if os.getenv("DB_OWNER_CHECK_ONLY") == "true":
        return 2

    admin_url = os.getenv("DB_OWNER_ADMIN_URL") or app_url
    conn = await asyncpg.connect(normalize(admin_url), timeout=10)
    try:
        admin = await conn.fetchrow("SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser")
        if not admin["is_superuser"] and any(admin["current_user"] != owner for _, owner in mismatches):
            print("OWNER_REPAIR_REQUIRED administrator or table-owner database credentials are required")
            return 3
        for target, _ in mismatches:
            await conn.execute(f"ALTER TABLE {target} OWNER TO {expected}")
    finally:
        await conn.close()

    _, repaired = await owner_status(app_url)
    if any(owner != expected for _, owner in repaired):
        print("OWNER_REPAIR_FAILED owner verification failed after repair")
        return 4
    print(f"OWNER_REPAIR_PASS owner={expected}")
    return 0

sys.exit(asyncio.run(main()))
'@ | & $backendPy -
$output | ForEach-Object { Write-Output $_ }
exit $LASTEXITCODE
