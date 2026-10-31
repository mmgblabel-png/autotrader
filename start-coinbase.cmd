@echo off
setlocal
cd /d "%~dp0"

echo [Coinbase RiskTrader] Synchronizing exact coinbase-local release...
git fetch origin coinbase-local
if errorlevel 1 (
  echo [Coinbase RiskTrader] Git fetch failed. Trader was not restarted.
  exit /b 1
)

git switch coinbase-local
if errorlevel 1 (
  echo [Coinbase RiskTrader] Could not switch to coinbase-local.
  exit /b 1
)

git reset --hard origin/coinbase-local
if errorlevel 1 (
  echo [Coinbase RiskTrader] Could not reset to origin/coinbase-local.
  exit /b 1
)

for /f %%i in ('git rev-parse --short HEAD') do set LOCAL_COMMIT=%%i
for /f %%i in ('git rev-parse --short origin/coinbase-local') do set REMOTE_COMMIT=%%i

echo [Coinbase RiskTrader] LOCAL  %LOCAL_COMMIT%
echo [Coinbase RiskTrader] REMOTE %REMOTE_COMMIT%

if /I not "%LOCAL_COMMIT%"=="%REMOTE_COMMIT%" (
  echo [Coinbase RiskTrader] Local/remote commit mismatch. Build aborted.
  exit /b 1
)

echo [Coinbase RiskTrader] Starting verified commit %LOCAL_COMMIT%...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-coinbase-local-windows.ps1"
exit /b %errorlevel%
