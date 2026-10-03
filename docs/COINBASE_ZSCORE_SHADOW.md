# Coinbase BTC Z-Score Shadow

## Purpose

This worker transfers the research idea behind a short-horizon binary Z-score model to Coinbase without pretending that a binary payout and spot trading are the same product.

Coinbase spot has linear P&L. Therefore the worker estimates short-horizon return drift from Coinbase BTC-EUR prices, volatility-scales the forecast, rejects statistically overextended entries, and only opens a hypothetical LONG when the expected move clears conservative fees, slippage and a safety margin.

## Safety properties

- Public Coinbase market data only for the shadow loop.
- No API key is required for shadow research.
- No order-create, order-cancel, transfer or withdrawal method is called.
- live_orders_sent is hard-coded false in persisted/status output.
- Spot shorting is disabled.
- Derivatives execution is disabled.
- Maximum aggregate shadow exposure is 20% of shadow equity.
- Automatic live promotion is disabled.
- Promotion evidence gate: at least 300 settled trades, positive realized P&L, profit factor >= 1.20 and max drawdown <= 8%.

## Persistent state

Production should use:

- /data/coinbase_zscore_shadow.json
- /data/coinbase_zscore_status.json

The main Railway service already mounts /data; this avoids a second always-on worker and keeps the evidence ledger across deploys/restarts.

## API credentials

Shadow mode does not need Coinbase credentials.

For later authenticated account checks or reviewed order execution, use Coinbase Developer Platform ECDSA credentials and store them only as Railway secrets:

- COINBASE_API_KEY = full CDP key name, normally organizations/<org-id>/apiKeys/<key-id>
- COINBASE_API_SECRET = the EC private key with newlines preserved

Do not commit keys to GitHub. Do not grant transfer/withdrawal permissions to a trading-only key. Use the narrowest portfolio and trading permissions available and an IP allowlist where operationally possible.

The authenticated connector generates a short-lived ES256 JWT per request. Shadow market data deliberately disables authenticated public requests, so bad or absent credentials cannot stop research collection.

## Dashboard API

Authenticated dashboard clients can read GET /api/research/coinbase-zscore.

The response exposes modeled costs, current public price, last decisions, settled-trade statistics, drawdown and the promotion gate. It never returns API credentials.
