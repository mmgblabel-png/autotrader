# Polymarket BTC Z-Score Shadow Research

## Purpose

This subsystem tests a falsifiable version of the BTC Up/Down Z-score concept seen in social-media trading posts. It is **shadow-only**. It has no code path that can sign, submit, cancel or replace a Polymarket order.

## Contract truth source

For the current Polymarket BTC 5-minute and 15-minute Up/Down products, the worker accepts only markets whose contract text explicitly references Chainlink BTC/USD TWAP. It consumes Polymarket's public 60-second Chainlink TWAP stream. If the contract changes to another resolution source, market discovery rejects it rather than silently substituting another feed.

The existing AutoTrader Binance BTCUSDT feed remains useful as a secondary latency/research signal, but it is not used as settlement truth in this first implementation.

## Model

For current TWAP price `S`, captured opening strike `K`, annualized realized log-return volatility `sigma` and effective time to expiry `T`, the model uses:

`z = (ln(S / K) + mu_log * T) / (sigma * sqrt(T))`

`P(Up) = Phi(z)`

The default log drift is zero. The 60-second TWAP window reduces the effective horizon by half a TWAP window. This is an approximation, not a claim that terminal lognormal dynamics perfectly describe the contract.

An entry is recorded only when the larger of the Up/Down model edges remains above the configured threshold after:

- observed ask price;
- assumed venue fee;
- assumed slippage;
- an additional safety margin.

Sizing uses fractional Kelly but is bounded by both an absolute stake cap and a percentage-of-bankroll cap.

## Strike integrity

The price-to-beat is captured only near the start of a new 5m/15m epoch from the settlement-source TWAP stream. If the worker starts too late, it skips that window. It never invents or back-fills a strike from a different venue.

## Persistence gate

The dedicated Railway service must have persistent storage mounted at `/data`. Until that has been verified, `persistent_state_confirmed` remains `false` and the worker forcibly reports `promotion_ready=false` with `promotion_blocker=persistent_state_not_confirmed`. This prevents ephemeral redeploys from producing misleading promotion evidence.

## Promotion gate

`promotion_ready` is evidence only; there is no automatic promotion to live trading. Defaults require:

- at least 200 settled shadow trades;
- positive realized PnL after modeled fees;
- profit factor >= 1.20;
- max drawdown <= 8%.

A production decision should additionally require walk-forward analysis, fee/slippage stress, restart tests and reconciliation with actual Polymarket fee schedules.

## Run

Install the official current Polymarket SDK through the project live extra:

```bash
python -m pip install -e '.[live]'
python -m autotrader.prediction.worker --config config.polymarket-shadow.yaml
```

Docker:

```bash
docker build -f Dockerfile.polymarket-shadow -t autotrader-polymarket-shadow .
docker run --rm -v autotrader-polymarket-data:/data autotrader-polymarket-shadow
```

The persistent state is written to `/data/polymarket_zscore_shadow.json` and a compact status snapshot to `/data/polymarket_zscore_status.json`.

## Security properties

- Public market-data reads only.
- No private key or wallet address required.
- No execution-adapter import.
- No order endpoint calls.
- No leverage, borrowing or martingale.
- Atomic persistent ledger writes.
- Missing/mismatched resolution source fails closed.
