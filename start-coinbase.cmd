@echo off
setlocal
cd /d "%~dp0"

echo [Coinbase RiskTrader] Updating coinbase-local...
git pull origin coinbase-local
if errorlevel 1 (
  echo [Coinbase RiskTrader] Git update failed. Trader was not restarted.
  exit /b 1
)

for /f %%i in ('git rev-parse --short HEAD') do set COMMIT=%%i
echo [Coinbase RiskTrader] Starting commit %COMMIT%...

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-coinbase-local-windows.ps1"
exit /b %errorlevel%
