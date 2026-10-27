@echo off
setlocal
powershell.exe -NoProfile -Command "Invoke-RestMethod 'http://127.0.0.1:8787/api/health' | Format-List"
exit /b %errorlevel%
