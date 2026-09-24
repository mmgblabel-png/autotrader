$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run .\install-bitvavo-windows.ps1 first.' }
$env:BITVAVO_DRY_RUN = 'true'
$env:EXECUTION_MODE = 'shadow'
$env:EMERGENCY_STOP = 'true'
$url = 'http://127.0.0.1:8788'
Start-Process $url
Write-Host "Opening $url. Credentials are used in memory for one balance request only." -ForegroundColor Cyan
& $python -m uvicorn autotrader.api.bitvavo_setup:app --host 127.0.0.1 --port 8788 --no-access-log
