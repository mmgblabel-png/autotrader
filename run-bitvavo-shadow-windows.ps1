$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run .\install-bitvavo-windows.ps1 first.' }

$env:EXCHANGE_VENUE = 'bitvavo'
$env:BITVAVO_DRY_RUN = 'true'
$env:EXECUTION_MODE = 'shadow'
$env:EMERGENCY_STOP = 'true'
$env:MAX_TRADE_EUR = '10'
$env:MAX_DAILY_EXPOSURE_EUR = '50'
$env:MAX_DAILY_LOSS_EUR = '25'
$env:MAX_SLIPPAGE_BPS = '50'

Write-Host 'Starting AutoTrader with Bitvavo shadow mode. No orders will be sent.' -ForegroundColor Yellow
& $python -m uvicorn autotrader.api.server:app --host 127.0.0.1 --port 8787
