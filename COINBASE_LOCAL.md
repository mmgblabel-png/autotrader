# Coinbase RiskTrader — lokaal op Windows met Docker

Deze runtime is bewust **Coinbase-only**. Hij start niet de algemene AutoTrader-server
en initialiseert geen Bitvavo-processen. De webinterface is alleen bereikbaar op
`127.0.0.1:8787`.

## 1. Docker Desktop installeren

Open PowerShell als administrator:

```powershell
winget install -e --id Docker.DockerDesktop
```

Start daarna Docker Desktop. Gebruik de WSL 2 backend wanneer Docker daarom vraagt.

Controle:

```powershell
docker version
docker compose version
```

## 2. Repository bijwerken

Open PowerShell in de AutoTrader-map en haal de nieuwste `production` branch op:

```powershell
git checkout production
git pull
```

## 3. Lokale secrets maken

Maak de lokale env-file:

```powershell
Copy-Item .env.coinbase.local.example .env.coinbase.local
notepad .env.coinbase.local
```

Vul lokaal in:

- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`
- `COINBASE_AGENT_PORTFOLIO_ID` — uitsluitend de aparte **AutoTrader Agent** portfolio
- `PUBLIC_API_KEY` — lange willekeurige lokale dashboard key
- `AUTOTRADER_CONTROL_TOKEN` — aparte lange willekeurige control key

Optioneel kun je ook username/password/JWT-login configureren. De echte
`.env.coinbase.local` staat in `.gitignore` en mag nooit worden gecommit.

## 4. Coinbase-only container starten

```powershell
docker compose -f docker-compose.coinbase.local.yml up -d --build
```

Controle:

```powershell
docker compose -f docker-compose.coinbase.local.yml ps
docker compose -f docker-compose.coinbase.local.yml logs -f --tail 100
```

Dashboard:

```text
http://127.0.0.1:8787/
```

Gebruik op het login-scherm de API-key uit `PUBLIC_API_KEY`, of configureer
username/password.

## 5. Live activeren

De container start fail-closed. Live orders vereisen in het dashboard:

1. geldige dashboard-auth;
2. de aparte `AUTOTRADER_CONTROL_TOKEN`;
3. de exacte Coinbase live-confirmatie;
4. een geldige geïsoleerde Coinbase Agent portfolio;
5. succesvolle Coinbase authentication en order-preview.

Na activering wordt de operator-intent in het Docker-volume bewaard. Een normale
containerrestart kan die intent herstellen wanneer de actuele Coinbase gates nog
steeds slagen.

## 6. Wat de lokale RiskTrader gebruikt

- Alleen assets in `COINBASE_AGENT_PORTFOLIO_ID`.
- EUR en USDC worden ondersteund als quote-capitaal.
- `BTC-EUR` en `BTC-USDC` worden op actuele preview fee, slippage, spread en
  forecast-edge vergeleken.
- `full_capacity: true`: binnen de geïsoleerde agent-portfolio is geen extra
  €5-cap of trust-fund reserve actief.
- Bestaand BTC buiten het agentportfolio wordt niet automatisch verkocht.
- Geen margin, leverage, futures, borrowing, transfers of withdrawals.
- Daily-loss stop: 3%.
- Drawdown stop: 10%.

## 7. Stoppen

```powershell
docker compose -f docker-compose.coinbase.local.yml down
```

De state blijft in het named volume `coinbase-risktrader-data` bewaard.

Volledig verwijderen inclusief state:

```powershell
docker compose -f docker-compose.coinbase.local.yml down -v
```

Gebruik `-v` alleen als je bewust alle lokale bot-state wilt wissen.
