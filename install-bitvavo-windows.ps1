$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python 3 is not installed. Install Python 3.11+ from https://www.python.org/downloads/windows/ and enable Add Python to PATH.'
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
}

$python = Join-Path $root '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install -e '.[dev]'
& $python -m pytest -q tests
Write-Host 'Bitvavo project installed and tested. No API keys were requested or stored.' -ForegroundColor Green
Write-Host 'Start shadow mode with .\run-bitvavo-shadow-windows.ps1' -ForegroundColor Cyan
