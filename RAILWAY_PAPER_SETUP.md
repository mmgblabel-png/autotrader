# Railway paper-only deployment

This repository is prepared for the existing Railway `autotrader` service. The service remains **paper-only**: no exchange credentials, wallet keys, signing, approvals, broadcasts, or live-order endpoints are added.

## Service settings

Use the repository root as the Railway source and keep the existing start command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Set these Railway variables:

```text
AUTOTRADER_CONFIG=config.yaml
AUTOTRADER_TICK_INTERVAL=1.0
PAPER_STARTING_BALANCE_USD=1000
USD_EUR_RATE=0.92
BTC_USD_PRICE=0
PAPER_EXPORT_DIR=exports
CORS_ORIGINS=https://YOUR-DASHBOARD-DOMAIN
AUTOTRADER_CONTROL_TOKEN=<long-random-secret>
MAINNET_EXECUTION_ENABLED=false
MAINNET_EMERGENCY_STOP=true
```

`BTC_USD_PRICE=0` means BTC conversion is shown as unavailable until a trusted BTC price source is wired. Do not put secrets in GitHub or the frontend.

## Health and API

- `GET /api/health` — Railway liveness and paper tick-loop status.
- `GET /api/paper/report` — USD/EUR/BTC balance and PnL, PnL percentage, drawdown.
- `GET /api/pnl/summary` — existing summary plus `paper_report`.
- `WS /ws/paper` — paper report every two seconds.
- `POST /api/paper/export` — writes a JSON and CSV export inside the Railway service filesystem.

Railway service files are ephemeral across redeploys. For durable exports, add a database/object-storage destination before relying on the files operationally.

## Daily midnight export

In Railway, open the `autotrader` service **Settings** and set its **Cron Schedule** to:

```text
0 0 * * *
```

A cron service should run an export command and exit. If the existing service is also the long-running API, prefer a separate Railway service connected to the same repository with start command:

```text
sh -c 'curl -fsS -X POST "$PAPER_EXPORT_URL"'
```

For the current codebase, the simplest safe option is to call the authenticated API export route from an external scheduler or a dedicated cron service. Do not make the long-running API process exit at midnight.

## First verification after deployment

```bash
curl -fsS https://YOUR-RAILWAY-DOMAIN/api/health
curl -fsS https://YOUR-RAILWAY-DOMAIN/api/paper/report
```

Confirm the response contains `"mode":"paper"`, `pnl_pct`, `drawdown_pct`, and EUR/BTC fields. Test WebSocket connectivity from the dashboard origin and confirm CORS is restricted to that origin.
