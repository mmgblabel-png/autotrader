# External repo research — 2026-10-04

Sources reviewed:
- https://github.com/neo4rm/bitvavo-ai-trading-agent
- https://github.com/latinvm/bender
- Bitvavo API rate-limit/error documentation

## Licensing decision

### neo4rm/bitvavo-ai-trading-agent
No repository-root LICENSE file was present at review time. Treat the implementation as
reference-only: do not copy code. Only independently implement general ideas.

Useful ideas:
- empirical/quantile lower-tail risk gates;
- champion/challenger promotion;
- multi-timeframe and regime-aware evaluation;
- order-book/trade-flow confirmation;
- drift and uncertainty gates;
- purged/embargo model validation where trained models create label overlap.

Existing AutoTrader overlap:
- fee/slippage-aware edge;
- live order-book imbalance and expected slippage;
- adaptive-learning rollback;
- backtest/walk-forward/stress/Monte-Carlo research;
- persistent shadow scorecards and promotion blockers.

Selected independent implementation:
- add empirical q10/q50/q90 outcome-return telemetry to shadow candidates;
- require a mature lower-tail sample and a bounded q10 result before full promotion.

### latinvm/bender
MIT-licensed at review time. Strongest relevant ideas are operational rather than alpha:
- trustworthy actual-fill accounting;
- Decimal conservative sizing;
- startup reconciliation / fail-closed behavior;
- market rotation and risk management;
- Bitvavo rate-limit robustness.

Existing AutoTrader overlap:
- durable order journal and reconciliation;
- Decimal/tick/quantity normalization;
- fail-closed preflight and live arming;
- explicit fee/slippage accounting;
- dynamic market universe.

Selected implementation:
- authenticated Bitvavo GETs may retry 429/5xx/network failures with bounded backoff;
- 429 timing honors `bitvavo-ratelimit-resetat` when the wait is short enough;
- each retry receives a fresh HMAC timestamp/signature;
- mutating POST/DELETE calls are never automatically replayed because an exchange timeout can be ambiguous.

## Safety properties

- No external strategy was made live-capable.
- No live order path was broadened.
- No leverage, margin, futures, borrowing or martingale was added.
- No POST/DELETE retry was added.
- Production is not modified by this research branch.
- Promotion remains operator-gated and shadow strategies remain non-live-capable.

## Acceptance criteria

1. Existing Bitvavo adapter tests stay green.
2. New tests prove private GET retry on transient 500.
3. New tests prove short 429 reset-header wait is honored.
4. New tests prove POST mutation is never automatically retried.
5. Existing shadow promotion test stays green.
6. New tests prove positive aggregate performance can still be blocked by a bad q10 lower tail.
7. New tests prove incomplete outcome history blocks promotion rather than passing silently.
8. No production deploy while real-money live trading is armed.
