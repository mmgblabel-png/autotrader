param(
    [string]$CoinbaseKeyJson = "$HOME\Downloads\cdp_api_key.json",
    [string]$PortfolioId = "57471e6d-48a6-4493-a765-b0a072b87bc1"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function First-JsonValue($Object, [string[]]$Names) {
    foreach ($name in $Names) {
        $prop = $Object.PSObject.Properties[$name]
        if ($null -ne $prop -and -not [string]::IsNullOrWhiteSpace([string]$prop.Value)) {
            return [string]$prop.Value
        }
    }
    return ""
}

function Set-EnvValue([string]$Text, [string]$Key, [string]$Value) {
    $pattern = "(?m)^" + [regex]::Escape($Key) + "=.*$"
    $line = "$Key=$Value"
    if ([regex]::IsMatch($Text, $pattern)) {
        return [regex]::Replace($Text, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $line }, 1)
    }
    if (-not $Text.EndsWith([Environment]::NewLine)) {
        $Text += [Environment]::NewLine
    }
    return $Text + $line + [Environment]::NewLine
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

$envPath = Join-Path $PSScriptRoot ".env.coinbase.local"
if (-not (Test-Path $envPath)) { throw ".env.coinbase.local ontbreekt." }
if (-not (Test-Path $CoinbaseKeyJson)) { throw "Coinbase key JSON niet gevonden: $CoinbaseKeyJson" }

$json = Get-Content -Raw -LiteralPath $CoinbaseKeyJson | ConvertFrom-Json
$keyName = First-JsonValue $json @("name", "apiKeyName", "api_key_name", "keyName", "key_name")
$privateKey = First-JsonValue $json @("privateKey", "private_key", "secret", "apiSecret", "api_secret")
if ([string]::IsNullOrWhiteSpace($keyName) -or [string]::IsNullOrWhiteSpace($privateKey)) {
    throw "Coinbase JSON bevat geen herkenbare API Key Name en Private Key."
}

$privateKey = $privateKey.Replace([string][char]13 + [string][char]10, "\n")
$privateKey = $privateKey.Replace([string][char]10, "\n").Replace([string][char]13, "\n")

$text = [System.IO.File]::ReadAllText($envPath)
$text = Set-EnvValue $text "COINBASE_API_KEY" $keyName.Trim()
$text = Set-EnvValue $text "COINBASE_API_SECRET" $privateKey.Trim()
$text = Set-EnvValue $text "COINBASE_AGENT_PORTFOLIO_ID" $PortfolioId.Trim()
Write-Utf8NoBom $envPath $text

try {
    & icacls $envPath /inheritance:r /grant:r "$($env:USERNAME):(F)" | Out-Null
} catch {
    Write-Warning "Kon ACL niet aanpassen; key is wel bijgewerkt."
}

Write-Host "Coinbase key lokaal vervangen. Secrets worden niet getoond."
Write-Host "Container wordt opnieuw aangemaakt zonder image rebuild..."

& docker compose --env-file .env.coinbase.local -f docker-compose.coinbase.local.yml up -d --no-build --force-recreate
if ($LASTEXITCODE -ne 0) { throw "Docker recreate mislukt." }

$healthy = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:8787/api/health" -TimeoutSec 5
        if ($h.status -eq "ok" -and $h.coinbase_only) {
            $healthy = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $healthy) {
    & docker logs --tail 120 coinbase-risktrader-local
    throw "Container werd niet gezond na re-key."
}

Write-Host "Container gezond. Coinbase diagnose:"
& (Join-Path $PSScriptRoot "diagnose-coinbase.ps1")
