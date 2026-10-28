param(
    [string]$CoinbaseKeyJson = "",
    [string]$PortfolioId = "",
    [switch]$Start
)

# Default to starting the local Coinbase stack when no -Start value is supplied.
# This keeps the common Windows command simple: .\setup-coinbase-local-windows.ps1
if (-not $PSBoundParameters.ContainsKey("Start")) {
    $Start = $true
}

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Get-EnvValue([string]$Text, [string]$Key) {
    $m = [regex]::Match($Text, "(?m)^" + [regex]::Escape($Key) + "=(.*)$")
    if (-not $m.Success) { return "" }
    return $m.Groups[1].Value.Trim()
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

function New-Secret([int]$Bytes = 48) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function First-JsonValue($Object, [string[]]$Names) {
    foreach ($name in $Names) {
        $prop = $Object.PSObject.Properties[$name]
        if ($null -ne $prop -and -not [string]::IsNullOrWhiteSpace([string]$prop.Value)) {
            return [string]$prop.Value
        }
    }
    return ""
}

$branch = (& git branch --show-current 2>$null).Trim()
if ($branch -ne "coinbase-local") {
    throw "Open deze repository op branch 'coinbase-local' voordat je dit script uitvoert. Huidige branch: '$branch'"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI niet gevonden. Start/installeer Docker Desktop en probeer opnieuw."
}
& docker compose version | Out-Host

$EnvPath = Join-Path $RepoRoot ".env.coinbase.local"
$TemplatePath = Join-Path $RepoRoot ".env.coinbase.local.example"
if (-not (Test-Path $EnvPath)) {
    Copy-Item $TemplatePath $EnvPath
}

$text = [System.IO.File]::ReadAllText($EnvPath)

if ([string]::IsNullOrWhiteSpace((Get-EnvValue $text "PUBLIC_API_KEY"))) {
    $text = Set-EnvValue $text "PUBLIC_API_KEY" (New-Secret)
}
if ([string]::IsNullOrWhiteSpace((Get-EnvValue $text "AUTOTRADER_CONTROL_TOKEN"))) {
    $text = Set-EnvValue $text "AUTOTRADER_CONTROL_TOKEN" (New-Secret)
}
if ([string]::IsNullOrWhiteSpace((Get-EnvValue $text "PUBLIC_JWT_SECRET"))) {
    $text = Set-EnvValue $text "PUBLIC_JWT_SECRET" (New-Secret)
}

if (-not [string]::IsNullOrWhiteSpace($PortfolioId)) {
    $text = Set-EnvValue $text "COINBASE_AGENT_PORTFOLIO_ID" $PortfolioId.Trim()
}

if (-not [string]::IsNullOrWhiteSpace($CoinbaseKeyJson)) {
    $resolved = (Resolve-Path $CoinbaseKeyJson).Path
    $json = Get-Content -Raw -LiteralPath $resolved | ConvertFrom-Json
    $keyName = First-JsonValue $json @("name", "apiKeyName", "api_key_name", "keyName", "key_name")
    $privateKey = First-JsonValue $json @("privateKey", "private_key", "secret", "apiSecret", "api_secret")
    if ([string]::IsNullOrWhiteSpace($keyName) -or [string]::IsNullOrWhiteSpace($privateKey)) {
        throw "Coinbase JSON bevat geen herkenbare API Key Name en Private Key."
    }
    $privateKey = $privateKey.Replace([string][char]13 + [string][char]10, "\n")
    $privateKey = $privateKey.Replace([string][char]10, "\n").Replace([string][char]13, "\n")
    $text = Set-EnvValue $text "COINBASE_API_KEY" $keyName.Trim()
    $text = Set-EnvValue $text "COINBASE_API_SECRET" $privateKey.Trim()
}

Write-Utf8NoBom $EnvPath $text

try {
    & icacls $EnvPath /inheritance:r /grant:r "$($env:USERNAME):(F)" | Out-Null
} catch {
    Write-Warning "Kon Windows ACL op .env.coinbase.local niet aanscherpen; controleer bestandsrechten handmatig."
}

Write-Host "Lokale Coinbase-config staat klaar. Secrets zijn niet naar Git geschreven."

if ($Start) {
    $required = @("COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_AGENT_PORTFOLIO_ID", "PUBLIC_API_KEY", "AUTOTRADER_CONTROL_TOKEN")
    $current = [System.IO.File]::ReadAllText($EnvPath)
    foreach ($key in $required) {
        if ([string]::IsNullOrWhiteSpace((Get-EnvValue $current $key))) {
            throw "Kan niet starten: $key ontbreekt in .env.coinbase.local"
        }
    }

    & docker info | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker daemon is niet bereikbaar. Start Docker Desktop en probeer opnieuw."
    }

    & docker compose --env-file $EnvPath -f docker-compose.coinbase.local.yml up -d --build --force-recreate
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build/start is mislukt. De healthcheck wordt niet uitgevoerd."
    }

    & docker compose --env-file $EnvPath -f docker-compose.coinbase.local.yml ps

    $health = $null
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8787/api/health" -TimeoutSec 5
            if ($health.status -eq "ok" -and $health.coinbase_only) {
                break
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    if ($null -eq $health -or $health.status -ne "ok" -or -not $health.coinbase_only) {
        & docker compose --env-file $EnvPath -f docker-compose.coinbase.local.yml logs --tail 100
        throw "Container is gestart, maar de Coinbase-only healthcheck werd niet groen."
    }

    Write-Host "Coinbase RiskTrader draait lokaal en Coinbase-only op http://127.0.0.1:8787/"
    Write-Host "Live trading blijft disarmed totdat je het expliciet in het lokale dashboard activeert."
}
