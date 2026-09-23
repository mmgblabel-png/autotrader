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
LIVE_RATES_ENABLED=true
BTC_USD_PRICE_URL=https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT
USD_EUR_RATE_URL=https://api.frankfurter.app/latest?from=USD&to=EUR
PAPER_EXPORT_DIR=exports
CORS_ORIGINS=https://YOUR-DASHBOARD-DOMAIN
AUTOTRADER_CONTROL_TOKEN=<long-random-secret>
PUBLIC_API_KEY=<long-random-secret-for-dashboard>
PUBLIC_JWT_SECRET=<different-long-random-secret-if-JWT-is-used>
MAINNET_EXECUTION_ENABLED=false
MAINNET_EMERGENCY_STOP=true
```

With `LIVE_RATES_ENABLED=true`, the report uses public Binance BTCUSDT and Frankfurter/ECB USD→EUR data with a four-second timeout and 30-second process cache. If a request fails, the configured numeric fallback values are used. Do not put secrets in GitHub or the frontend.

## Health and API

- `GET /api/health` — Railway liveness and paper tick-loop status.
- `GET /api/paper/report` — USD/EUR/BTC balance and PnL, PnL percentage, drawdown.
- `GET /api/pnl/summary` — existing summary plus `paper_report`.
- `WS /ws/paper` — paper report every two seconds.
- `POST /api/paper/export` — writes a JSON and CSV export inside the Railway service filesystem.

All `/api/*` routes except `/api/health`, plus `/strategies/*`, require either
`X-API-Key: $PUBLIC_API_KEY` or `Authorization: Bearer <HS256 JWT>`. The
WebSocket accepts the same headers; browser clients may use
`wss://YOUR-DOMAIN/ws/paper?api_key=...` when custom headers are unavailable.
Keep the query-string form out of shared links and browser history where
possible. `PUBLIC_API_KEY` and `PUBLIC_JWT_SECRET` are fail-closed secrets;
when neither is configured, protected routes return HTTP 503.

Railway service files are ephemeral across redeploys. For durable exports, add a database/object-storage destination before relying on the files operationally.

## Daily midnight export

In Railway, open the `autotrader` service **Settings** and set its **Cron Schedule** to:

```text
0 0 * * *
```

A cron service should run an export command and exit. If the existing service is also the long-running API, prefer a separate Railway service connected to the same repository with start command:

```text
sh -c 'curl -fsS -H "X-API-Key: $PUBLIC_API_KEY" -X POST "$PAPER_EXPORT_URL"'
```

For the current codebase, the dedicated `paper-pnl-midnight-export` service
calls the authenticated API export route and exits. Give that service the same
`PUBLIC_API_KEY` value as the web service. Do not make the long-running API
process exit at midnight.

## Telegram or e-mail notifications

Notifications are opt-in and are triggered only after a successful paper
export. They never place orders. For Telegram, create a bot with BotFather,
add it to the target channel, grant permission to post, and set:

```text
PAPER_NOTIFY_TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<Railway secret>
TELEGRAM_CHAT_ID=<channel id, commonly -100...>
```

For e-mail, use an SMTP provider or app password and set:

```text
PAPER_NOTIFY_EMAIL_ENABLED=true
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=<smtp username>
SMTP_PASSWORD=<smtp app password>
SMTP_FROM=bot@example.com
PAPER_NOTIFY_EMAIL_TO=you@example.com
```

Do not commit any of these values. Add them as Railway service variables. If
both channels are enabled, one report is attempted on each channel; a failed
notification is logged and does not invalidate the exported report.

## First verification after deployment

```bash
curl -fsS https://YOUR-RAILWAY-DOMAIN/api/health
curl -fsS https://YOUR-RAILWAY-DOMAIN/api/paper/report
```

Confirm the response contains `"mode":"paper"`, `pnl_pct`, `drawdown_pct`, and EUR/BTC fields. Test WebSocket connectivity from the dashboard origin and confirm CORS is restricted to that origin.
