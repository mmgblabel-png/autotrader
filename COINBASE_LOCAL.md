# Coinbase RiskTrader — lokaal op Windows met Docker

Deze runtime is bewust **Coinbase-only**. Hij start niet de algemene AutoTrader-server,
initialiseert geen Bitvavo-processen en gebruikt Railway niet. De webinterface wordt
alleen gepubliceerd op `127.0.0.1:8787`.

## 1. Windows / WSL / Docker controleren

Start Docker Desktop en gebruik de WSL 2 backend.

Open PowerShell:

```powershell
wsl --status
wsl --version
docker version
docker compose version
```

Docker Desktop moet bij `docker version` zowel een Client als Server tonen.

## 2. De lokale Coinbase-branch gebruiken

Open PowerShell in de AutoTrader-map:

```powershell
git fetch origin
git switch coinbase-local
git pull origin coinbase-local
```

Gebruik voor deze pc niet `production` en niet de algemene `docker-compose.yml`.

## 3. Dedicated Coinbase API-key

Maak in Coinbase Developer Platform een nieuwe CDP API-key die specifiek aan de
**AutoTrader Agent** portfolio is gekoppeld.

Gebruik alleen:

- View
- Trade

Laat **Transfer uit**. De lokale trader heeft geen transfer- of withdrawalfunctie nodig.
Bewaar de gedownloade Coinbase JSON-key alleen lokaal.

## 4. Lokale secrets en dashboard-tokens maken

De eenvoudigste route is het PowerShell-script:

```powershell
.\setup-coinbase-local-windows.ps1
```

Dit maakt `.env.coinbase.local`, genereert sterke lokale dashboard/control/JWT-tokens
en zet het bestand buiten Git.

Heb je de door Coinbase gedownloade JSON-key, dan kan het script de key veilig in de
lokale env-file zetten:

```powershell
.\setup-coinbase-local-windows.ps1 -CoinbaseKeyJson "$HOME\Downloads\cdp_api_key.json" -PortfolioId "<AUTO_TRADER_AGENT_PORTFOLIO_UUID>"
```

Het script print de geheimen niet terug naar het scherm.

Handmatig kan ook:

```powershell
notepad .env.coinbase.local
```

Vereist:

- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`
- `COINBASE_AGENT_PORTFOLIO_ID`
- `PUBLIC_API_KEY`
- `AUTOTRADER_CONTROL_TOKEN`

## 5. Coinbase-only container starten

Als de env-file compleet is:

```powershell
.\setup-coinbase-local-windows.ps1 -Start
```

Of handmatig:

```powershell
docker compose --env-file .env.coinbase.local -f docker-compose.coinbase.local.yml up -d --build
docker compose --env-file .env.coinbase.local -f docker-compose.coinbase.local.yml ps
docker compose --env-file .env.coinbase.local -f docker-compose.coinbase.local.yml logs -f --tail 100
```

Dashboard:

```text
http://127.0.0.1:8787/
```

De container is gehard met een read-only root filesystem, dropped Linux capabilities,
`no-new-privileges`, resource-limits, een aparte data-volume en alleen localhost
port-binding.

## 6. Live activeren

De runtime start met `live_armed = false`. Live orders vereisen daarna in het lokale
dashboard:

1. geldige dashboard-auth;
2. de aparte `AUTOTRADER_CONTROL_TOKEN`;
3. de exacte Coinbase live-confirmatie;
4. een geldige geïsoleerde AutoTrader Agent portfolio;
5. succesvolle Coinbase authentication en order-preview.

Een normale containerrestart kan eerder opgeslagen operator-intent alleen herstellen
als de actuele Coinbase readiness-gates nog steeds slagen.

## 7. RiskTrader-kapitaal

- Alleen assets uit `COINBASE_AGENT_PORTFOLIO_ID` worden beheerd.
- EUR en USDC worden als quote-capitaal ondersteund.
- `BTC-EUR` en `BTC-USDC` worden op actuele preview fee, slippage, spread en
  forecast-edge vergeleken.
- `full_capacity: true`: binnen de geïsoleerde agent-portfolio is geen extra
  €5-cap of trust-fund reserve actief.
- Geld in andere Coinbase-portfolio's blijft buiten deze runtime.
- Geen margin, leverage, futures, borrowing, transfers of withdrawals.
- Daily-loss stop: 3%.
- Drawdown stop: 10%.

## 8. Stoppen

```powershell
docker compose --env-file .env.coinbase.local -f docker-compose.coinbase.local.yml down
```

De state blijft in het named volume `coinbase-risktrader-data` bewaard.

Volledig verwijderen inclusief bot-state:

```powershell
docker compose --env-file .env.coinbase.local -f docker-compose.coinbase.local.yml down -v
```

Gebruik `-v` alleen als je bewust alle lokale bot-state wilt wissen.
