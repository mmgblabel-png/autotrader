# Hourly Learning & Research Log

## 2026-10-01 — Research Pack v1

### Sources reviewed
- Hummingbot pure market making: `max_order_age`, `order_refresh_tolerance_pct`, `filled_order_delay`, ping-pong/inventory controls.
  - https://github.com/hummingbot/hummingbot/blob/master/hummingbot/strategy/pure_market_making/pure_market_making_config_map.py
  - https://github.com/hummingbot/hummingbot/search?q=filled_order_delay&type=code
- Bitvavo API order-book guidance: synchronized snapshots/updates, nonce/timestamp freshness and order-book depth.
  - https://docs.bitvavo.com/docs/manage-order-book/
  - https://docs.bitvavo.com/docs/rest-api/get-order-book/
- Freqtrade validation: lookahead-analysis and recursive-analysis patterns and documented false-positive caveats.
  - https://github.com/freqtrade/freqtrade/blob/develop/docs/lookahead-analysis.md
- NautilusTrader execution architecture: strategy -> risk -> execution -> reconciliation with standardized deny/reject paths.
  - https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/concepts/execution/index.md
- Bitvavo market universe/volume page used only as a research seed; runtime metadata/preflight remains authoritative.
  - https://www.bitvavo.com/nl/markets

### Implemented in this pack
1. Execution v2 remains advisory only. Added refresh-tolerance, max-age cancel recommendation and post-fill delay observability. No live cancel/replace path was enabled.
2. Opportunity Router now scores top-of-book imbalance, local snapshot freshness and a conservative top-depth slippage proxy in addition to spread/liquidity/volatility/momentum.
3. Shadow ML gained prefix-feature lookahead validation and recursive-history stability analysis. Warnings require review and are not automatic proof of strategy failure.
4. Daily exposure headroom calculation is centralized in ExecutionGateway; pending local BUY reservations remain deducted before autonomy permits new entries.
5. Added a distinct `GridRunnerETH` runtime for ETH-EUR. Existing `GridRunner` ownership remains unchanged so its SOL inventory/journal continuity is preserved.
6. Split the existing Grid allocation from EUR 15 into SOL EUR 8 + ETH EUR 7. Global live budget remains EUR 50 and total configured live allocation remains EUR 40.
7. Broadened the preferred research/router universe with NEAR, AVAX, HBAR, SUI, XLM, AAVE, ALGO, ONDO, FET, DOT, LTC, BCH, UNI, HYPE and QNT. These are research candidates, not automatically approved live markets.

### Acceptance criteria
- Full test suite green.
- Paper/staging healthcheck green.
- Both grid instances keep separate strategy ownership in allocator, risk, journal, PnL and adaptive learning.
- Live preflight validates ETH-EUR rules independently.
- Router continues to scan up to 60 EUR markets without sending orders.
- No new live cancel/replace capability is introduced by Execution v2.
- No increase to global budget, hard risk limits, leverage or martingale.


## 2026-10-02 07:00 CEST — Execution v3 runtime findings

- Overnight live fills confirmed positive realized GridRunner exits on DOGE-EUR and PEPE-EUR while SUI-EUR and AVNT-EUR inventory remained open.
- The main missed-opportunity failure mode was repeated `strategy per-order allocation exceeded` rejection followed by a 60-second GridRunner failure cooldown.
- Execution v3 now resizes BUY entries down to available strategy/global headroom instead of dropping a valid opportunity for a small cap overrun.
- Risk-reducing SELL exits are not trapped behind entry allocation, per-trade, daily-exposure, or daily-loss entry gates; price/slippage/live activation validation remains active.
- Grid allocation failures retry after a short allocation-specific cooldown instead of the generic 60-second failure cooldown.
- Strategy allocation now uses the existing EUR 50 global live budget more fully: MarketMaker EUR 18, GridRunner EUR 10, GridRunnerETH EUR 10, SniperBot EUR 12.
- Hard global live exposure remains EUR 50; leverage and martingale remain disabled.
