# AutoTrader Fund Operating Model v4

## Mandate

AutoTrader operates as a personal systematic crypto fund control plane. Capital
preservation is senior to return maximization. Growth targets are milestones,
not risk inputs. The runtime never arms itself and never gains withdrawal,
private-key export, arbitrary transfer, or bridge authority.

The growth path is:

```text
€50
→ €500
→ €5,000
→ €50,000
→ verified live track record
→ potential investor outreach
```

External capital acceptance remains disabled until legal, compliance,
accounting and audit gates are explicitly completed outside the trading runtime.

## Operating architecture

```text
Research Engine
    ↓
Market Scanner
    ↓
Specialized AI / Quant Agents
    ↓
Signal Blender
    ↓
Portfolio Allocation Engine
    ↓
Independent Risk Manager
    ↓
Execution Coordinator / Gateway
    ↓
Bitvavo live execution
    ↓
Reconciliation
    ↓
Verified NAV + Fund Ledger
    ↓
Performance Review / Reporting
    ↓
Portfolio Dashboard
```

Research agents cannot send exchange orders. The Risk Manager has veto
authority. The execution layer can execute only intents that pass portfolio,
fund, growth-stage, exchange, profit, security and runtime-arm gates.

## Fund departments

### Fund Manager

Owns the mandate, growth stage, capital allocation, protected capital and final
portfolio state.

### Research

Owns scanner data, normalized AgentSignal evidence, backtests, walk-forward
testing, stress tests, Monte Carlo and research-agent KPIs.

### Operations

Owns live preflight, execution, order ownership, durable reconciliation,
incident handling and restart safety.

### Compliance

Owns exchange permissions, withdrawal prohibition, governance evidence and the
technical lock on external capital. The runtime does not claim that internal
controls replace professional legal advice or regulatory authorization.

### Accounting

Owns verified NAV provenance, realized PnL, fees, high-water marks, drawdowns
and the append-only hash-chained FundLedger.

### Investors

Remains LOCKED until both:
1. the verified live track record passes its evidence thresholds; and
2. legal, compliance, accounting and external-audit governance checks are
   confirmed.

Even after both conditions are met, external capital acceptance requires
`investor_capital_enabled: true`, which defaults to false.

## Nine-agent control plane

### Market Research Agent

Responsibilities:
- rank liquid markets;
- include spread, fees and expected slippage;
- reject stale or ineligible opportunities.

Inputs:
- OpportunityRouter score;
- liquidity;
- spread;
- slippage;
- fee estimates;
- signal strength and direction.

Output:
- normalized AgentSignal.

KPIs:
- forward information coefficient;
- net edge after costs;
- false-positive opportunity rate.

### Trend Detection Agent

Responsibilities:
- detect directional persistence;
- separate trend/range behavior;
- penalize momentum disagreement and stale evidence.

Inputs:
- trend feature;
- momentum;
- volatility;
- freshness.

Output:
- normalized AgentSignal.

KPIs:
- trend hit rate;
- forward-return IC;
- whipsaw rate.

### On-Chain Analysis Agent

Responsibilities:
- exchange-flow pressure;
- activity acceleration;
- supply/staking pressure.

The engine exists as a deterministic evidence transformer. It becomes active
only when an approved, point-in-time on-chain data source supplies observations.
It has no exchange credentials.

### Whale Tracking Agent

Responsibilities:
- accumulation/distribution evidence;
- exchange-deposit pressure;
- large-transaction classification.

It requires classified wallet observations. Unknown/self-transfer activity must
not be treated as a trade signal without data-quality evidence.

### Sentiment Agent

Responsibilities:
- source-weighted sentiment;
- novelty filtering;
- signal time decay.

It requires approved sentiment/news observations and has no execution authority.

### Risk Agent

Implementation:
- FundRiskEngine;
- GrowthController;
- sector concentration veto.

Outputs:
- APPROVE;
- RESIZE;
- BLOCK.

KPI:
- zero hard-risk breaches.

### Portfolio Allocation Agent

Implementation:
- SignalBlender;
- PortfolioAllocationEngine.

Responsibilities:
- combine evidence;
- preserve cash;
- enforce asset/sector concentration;
- produce target notionals.

### Execution Agent

Implementation:
- StrategyAllocator;
- ExecutionCoordinator;
- ExecutionGateway;
- BitvavoAdapter.

Responsibilities:
- maker-first execution;
- exchange-rule validation;
- idempotent order ownership;
- fill/reconciliation handling.

The execution agent cannot arm itself.

### Performance Review Agent

Implementation:
- FundLedger;
- ShadowStrategyEngine;
- ResearchLab;
- GrowthController.

Outputs:
- PROMOTE;
- KEEP;
- DROP / QUARANTINE;
- verified-track-record status.

## Growth stages

### Seed — €50 → €500

Policy:
- maximum 40% deployable;
- at least 60% reserve;
- €6 maximum order;
- 2 maximum concurrent open orders;
- 6% portfolio drawdown ceiling;
- 1.5% daily loss ceiling;
- 12% maximum single-trade notional;
- 40% maximum gross exposure;
- 20% strategy and asset caps;
- 30% stage sector ceiling, with stricter category overrides.

Purpose:
- prove execution economics;
- avoid fee churn;
- gather real fill evidence.

### Emerging — €500 → €5,000

Policy:
- maximum 50% deployable;
- €20 maximum order;
- 4 open orders;
- 6.5% drawdown ceiling;
- 1.5% daily loss ceiling;
- 4% maximum single-trade notional;
- 50% gross exposure ceiling.

Purpose:
- diversify strategies and assets;
- build statistically useful samples.

### Scaled — €5,000 → €50,000

Policy:
- maximum 60% deployable;
- €100 maximum order;
- 6 open orders;
- 7% drawdown ceiling;
- 2% maximum single-trade notional;
- tighter 15% asset and 25% sector ceilings.

Purpose:
- portfolio optimization;
- stronger diversification;
- execution-quality measurement.

### Institutional Personal — €50,000+

Policy:
- maximum 65% deployable;
- €250 maximum order;
- 8 open orders;
- 8% hard drawdown ceiling;
- 1.25% daily loss ceiling;
- 0.5% maximum single-trade notional;
- 12.5% maximum asset exposure;
- 20% stage sector ceiling.

Purpose:
- build durable audited personal track record;
- prepare operations and reporting for professional review.

The €25,000 protected-capital latch remains a separate permanent capital
preservation control. Reaching later growth stages does not remove it.

## Sector allocation

The portfolio layer classifies holdings into:
- bitcoin;
- layer1;
- payments;
- oracle/infrastructure;
- DeFi;
- RWA;
- AI/data;
- gaming/metaverse;
- meme/speculative;
- trading infrastructure;
- other.

Unknown assets default to the restrictive `other` bucket. Meme/speculative
assets have a stricter concentration limit than the generic sector cap.

Ten correlated coins are not treated as ten independent sources of
diversification.

## Verified live track record

A verified track record uses only:
- authenticated, verified live NAV checkpoints;
- live fill events;
- hash-valid FundLedger records.

Paper and shadow results do not count.

Default evidence requirements:
- at least 365 elapsed days;
- at least 250 NAV observation days;
- at least 200 completed live SELL exits;
- positive realized net PnL;
- profit factor >= 1.10;
- Sharpe >= 0.50;
- maximum drawdown <= 8%;
- valid ledger chain.

The system reports incomplete metrics as incomplete. It never fabricates a
Sharpe ratio, probability of profit or investor-ready status.

## Backtesting and Monte Carlo

ResearchLab remains research-only and provides:
- historical backtest;
- walk-forward testing;
- bull/bear/sideways stress scenarios;
- fee/slippage-aware results;
- Monte Carlo with at least 10,000 simulations.

Research output can support strategy promotion but cannot directly place an
order or raise live risk limits.

## Live activation rule

The application must never tell the operator to press Live unless
`/api/live/readiness` returns:

```json
{
  "ready_to_arm": true,
  "ready": true,
  "armed": false
}
```

and every gate is true, including:
- live execution environment;
- approved live adapter;
- emergency stop off;
- explicit confirmation;
- Bitvavo live mode with dry-run off;
- credentials present;
- Bitvavo security pass;
- live market preflight pass;
- exchange/journal reconciliation safe;
- profit policy satisfied;
- fresh verified Fund NAV;
- valid FundLedger;
- growth-stage risk clear;
- growth-stage budget supports the exchange minimum;
- at least one approved running live strategy;
- control token present.

The software never presses or simulates pressing Live itself.

## Security invariants

The trading runtime may:
- analyze;
- simulate;
- place approved trades after operator arm;
- manage/reduce positions;
- reconcile owned orders.

The trading runtime may never:
- withdraw;
- export private keys;
- transfer to unknown wallets;
- bridge without owner authorization;
- enable leverage/martingale by itself;
- raise hard limits to chase a target;
- enable investor capital automatically.

## Deployment

Source of truth:
- GitHub `main`.

Runtime:
- Railway production.

Persistent state:
- Railway `/data`;
- FundLedger SQLite WAL/FULL synchronous;
- order journal;
- shadow/adaptive-learning state.

Build gate:
1. install dependencies;
2. execute complete pytest suite;
3. build wheel;
4. build runtime image;
5. start non-root application after minimal volume-permission initialization;
6. healthcheck;
7. verify startup preflight;
8. leave runtime arm false after deployment.

## Operator runbook

Normal deployment requires no trading action.

When deployment is healthy:
1. open the authenticated dashboard;
2. check Fund Growth Ladder;
3. check NAV verification;
4. check ledger integrity;
5. check Track Record/Operations status;
6. wait for Live Readiness to show all gates green.

Only when the system explicitly reports `ready_to_arm=true` should the
operator press Live.

If any gate is false, do not arm.
