#Requires -Version 5.1
& (Join-Path $PSScriptRoot "start-local.ps1") @args
exit $LASTEXITCODE
