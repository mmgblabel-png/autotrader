# Futures + Trading AI Research Pack v1

This pack extends AutoTrader with a **read-only perpetual futures feed** and a
**long/short AI shadow engine**. It does not add futures credentials, wallet
signing, leverage execution or any live futures order path.

## Why these open-source projects

- **Hummingbot**: reference for maintained perpetual connector and market-making
  architecture. We reuse architecture ideas only; no Hummingbot runtime is
  embedded in this service.
- **Freqtrade**: reference for futures/short/leverage/liquidation semantics. Its
  code is GPL-3.0, so this repository does not copy or vendor Freqtrade code.
- **NautilusTrader**: reference for deterministic event-driven separation
  between market data, strategy logic and execution.
- **FinRL-Trading / FinRL-X**: reference for modular AI research pipelines and
  research-to-deployment discipline.

## What was implemented

1. `PerpetualPublicMarketData`
   - Hyperliquid public `metaAndAssetCtxs` is the primary source.
   - Binance USD-M public mark/funding endpoint is a fallback.
   - No API key or authenticated request is used.

2. `FuturesAIShadowEngine`
   - BTC, ETH, SOL and XRP perpetual research by default.
   - Long **and** short simulated positions.
   - Existing online-logistic model plus momentum, open interest, funding and
     basis overlay.
   - Configured fees/slippage and approximate funding are included in shadow PnL.
   - Persistent state on the existing Railway volume.
   - Hard `live_capable=false`, `live_orders_sent=false`, max live leverage 0.

3. Research promotion gates
   - Minimum completed trades.
   - Win rate, net PnL, max drawdown and walk-forward model accuracy.
   - `PROMOTE_REVIEW` means *review the research candidate*, not enable live
     futures.

## Cost policy

This pack runs inside the existing AutoTrader process and requires no new
Railway service and no paid model/API subscription.
