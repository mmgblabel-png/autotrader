# AutoTrader Fund Core v1

## Purpose

Fund Core v1 converts AutoTrader from a collection of independent trading strategies into a single portfolio governed by a common mandate, deterministic fund-level risk controls and a tamper-evident track-record ledger.

The design borrows the useful separation used by professional systematic funds:

```text
Research / AI agents
        |
        v
Normalized AgentSignal contracts
        |
        v
Deterministic SignalBlender
        |
        v
Strategy pods
        |
        v
FundRiskEngine
        |
        v
Existing StrategyAllocator + ExecutionGateway
        |
        v
Bitvavo / future approved venues
        |
        v
Hash-chained FundLedger
```

AI output never has direct exchange credentials and never bypasses the existing execution gateway.

## Capital-preservation defaults

The branch ships with conservative small-account defaults for a EUR 50 fund:

- 8% maximum portfolio drawdown
- 2% maximum daily realized loss
- 20% maximum single-trade notional
- 85% maximum gross spot exposure
- 40% maximum strategy exposure
- 35% maximum single-asset exposure
- 15% minimum cash reserve
- 0.62 minimum accepted AI signal confidence

These are hard ceilings, not return targets. Risk-reducing exits remain allowed when entry gates are closed.

## Fund ledger

Every accepted live fill can be recorded in the SQLite ledger together with NAV snapshots. Events are chained with SHA-256 hashes. Each row contains the previous event hash, which makes later modification or reordering detectable by `FundLedger.verify()`.

For Railway, attach a persistent volume and set:

```text
FUND_LEDGER_PATH=/data/fund_ledger.sqlite3
```

Without a persistent volume, the ledger is still functional but will not constitute a durable long-term track record across ephemeral deployments.

## Research agent contract

Agents submit `AgentSignal` objects only:

- agent
- strategy
- symbol
- direction: -1.0 to +1.0
- confidence: 0.0 to 1.0
- score: 0 to 100
- horizon_seconds
- timestamp
- metadata

The deterministic signal blender filters low-confidence and stale signals and applies configured agent weights plus recency decay.

## Existing execution safety remains authoritative

Fund Core adds a stricter layer. It does not remove or weaken:

- strategy allocation caps
- Bitvavo order validation
- daily execution exposure limits
- slippage limits
- runtime live arm
- emergency stop
- explicit live confirmation
- durable exchange reconciliation

A trade must pass every applicable layer.

## Test

```bash
pip install -e ".[dev]"
pytest -q tests/test_fund_core.py
pytest -q tests
```

## Railway rollout

1. Deploy the `fund-core-v1` branch to a staging service.
2. Keep `EXECUTION_MODE=shadow` and `EMERGENCY_STOP=true`.
3. Attach a persistent volume and set `FUND_LEDGER_PATH=/data/fund_ledger.sqlite3`.
4. Verify the full test suite and API health.
5. Run shadow/paper evidence collection.
6. Only after the existing live preflight and profitability/evidence gates pass should a reviewed change be merged to `main`.

Do not use the target-equity goal as a reason to raise risk. The existing `portfolio_goal.goal_is_risk_input=false` and `increase_risk_to_catch_up=false` settings should remain unchanged.
