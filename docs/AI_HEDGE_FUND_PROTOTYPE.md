# AI Hedge Fund Prototype

## Mission

AutoTrader is operated as one capital-preservation-first systematic fund, not
as independent bots. The operating path is:

~~~text
EUR 50
  -> EUR 500
  -> EUR 5,000
  -> EUR 50,000
  -> verified track record
  -> potential investor diligence
~~~

The growth objective never overrides the fund risk envelope.

## Runtime architecture

~~~text
Research Engine
    |
Market Scanner
    |
AI Research Department
    |
Signal Blender / Portfolio Allocation
    |
Independent Fund Risk Veto
    |
Execution Engine
    |
Bitvavo approved live route
    |
Reconciliation
    |
Hash-chained Fund Ledger
    |
Accounting / Performance / Governance
    |
Portfolio Dashboard + Fund Report API
~~~

Coinbase and other venues remain research/shadow unless their execution,
accounting and reconciliation paths are separately validated.

## AI Research Department

The prototype exposes nine formal agent roles:

1. Market Research Agent
2. Trend Detection Agent
3. On-Chain Analysis Agent
4. Whale Tracking Agent
5. Sentiment Agent
6. Risk Agent
7. Portfolio Allocation Agent
8. Execution Agent
9. Performance Review Agent

Each role publishes responsibilities, inputs, outputs, decision process and
KPIs. Signal-producing agents additionally expose signal count, mean confidence,
mean score and freshness state.

AI research never has direct exchange-order authority. An order still has to
pass portfolio, fund risk, profit, exchange-rule, reconciliation and runtime-arm
gates.

## Growth stages

| Stage | NAV | Max new trade | Max gross | Max strategy | Max asset | Min cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bootstrap | < EUR 500 | 16% | 65% | 30% | 30% | 35% |
| developing | EUR 500-5,000 | 12% | 70% | 30% | 25% | 30% |
| professional | EUR 5,000-50,000 | 8% | 75% | 25% | 20% | 25% |
| track_record | >= EUR 50,000 | 5% | 70% | 20% | 15% | 30% |

At EUR 50 the maximum new order allowed by the growth layer is EUR 8.

## Capital preservation

The growth target is EUR 50,000.

The permanent protected-capital floor remains EUR 25,000. It arms only from a
verified exchange-backed NAV high-water mark. After it arms, protected capital
cannot be deliberately reused for risk-increasing orders; only surplus above the
protected zone can support new exposure.

Risk-reducing exits remain allowed when entry risk is blocked.

## Verified track record

Infrastructure uptime is not counted as performance history.

The track-record clock starts with the first durable recorded fill. The default
investor-readiness evidence gate requires all of:

- NAV >= EUR 50,000;
- valid hash-chained Fund Ledger;
- verified live NAV;
- at least 365 days since the first recorded fill;
- at least 100 recorded fills.

Passing this gate means only that internal diligence evidence is ready. It does
not enable third-party capital acceptance.

## Accounting

Fund accounting is derived from immutable recorded fills and reports:

- fill count;
- profitable/loss/flat fill counts;
- positive-fill rate;
- realized net PnL;
- gross profit;
- gross loss;
- profit factor;
- turnover;
- 24-hour realized PnL;
- 7-day realized PnL;
- 30-day realized PnL.

These are recorded-fill metrics. They must not be confused with externally
audited financial statements.

## Governance and compliance controls

The prototype policy is fail-closed:

- automated withdrawals: disabled;
- private-key export: forbidden;
- transfers to unknown wallets: forbidden;
- bridges without owner approval: forbidden;
- third-party capital acceptance: disabled;
- explicit operator live arm: required.

The compliance state is therefore an internal personal-fund control state, not
a claim that an external regulated fund vehicle already exists.

## Investor reporting

The runtime exposes:

~~~text
GET /api/fund/status
GET /api/fund/report
~~~

Both endpoints are protected by the existing dashboard API authentication.

The report contains:

- verified NAV and drawdown;
- growth stage;
- track-record evidence;
- recorded-fill performance;
- research-department health;
- internal compliance checks;
- investor-diligence readiness;
- ledger integrity.

No secret, API key, private key or withdrawal credential is included.

## Dashboard

The Hedge Fund Command Center shows:

- verified Fund NAV;
- EUR 50,000 growth target;
- EUR 25,000 protected floor;
- current drawdown and exposure;
- active growth stage;
- next milestone;
- track-record days/fills;
- research-agent roster and health;
- research coverage;
- recorded-fill net PnL;
- 24h/7d/30d realized PnL;
- profit factor;
- internal compliance state;
- investor-reporting state.

## Deployment

The release process is:

~~~text
feature branch
  -> full pytest suite in Docker build
  -> Railway staging
  -> /api/health
  -> shadow scanners confirm live_orders_sent=false
  -> merge to main
  -> production Docker test gate
  -> production health
  -> live readiness
  -> operator may arm only when ready=true
~~~

A deployment never arms live trading automatically.

## Run

Local development:

~~~bash
python -m pip install -e ".[dev]"
python -m pytest -q tests
uvicorn autotrader.api.server:app --host 0.0.0.0 --port 8000
~~~

The production Dockerfile performs the full test suite before building the
runtime image.

## Safety invariant

The system may research, simulate, submit approved live trades and manage
existing positions. It may never automatically withdraw funds, export private
keys, send capital to unknown wallets, bridge assets without owner approval or
accept investor capital merely because an internal diligence gate becomes
green.


## Autonomous Fund Policy

The production fund operates with an immutable safety envelope. Runtime
configuration may make these limits stricter, but may not loosen them:

- maximum portfolio drawdown: 10%;
- maximum daily loss: 3%;
- maximum single position/asset exposure: 20% of verified NAV;
- minimum cash reserve: 20%;
- live entry market-quality score must be strictly greater than 85/100;
- spot only;
- leverage disabled;
- margin disabled;
- futures disabled;
- borrowing disabled.

The growth-stage controller can remain stricter. For example, the EUR 50
bootstrap stage keeps a 35% cash reserve and a 16% maximum new trade even
though the immutable outer envelope permits 20%.

### Autonomous decision cycle

~~~text
continuous market scanner
  -> trend / momentum / liquidity / volume / volatility features
  -> regime + execution-quality scoring
  -> score must be > 85
  -> performance-aware risk sizing
  -> high-volatility size haircut
  -> Fund Core risk veto
  -> profitability / fee gate
  -> exchange rules / balance gate
  -> reconciled spot execution
~~~

No setup is forced. If no market clears the quality, risk, cost and execution
gates, new entry capital stays in cash.

Existing spot inventory is protected independently from new-entry quality:

- stop-loss exits are risk reducing;
- trailing protection tracks the local position peak;
- the first qualifying profit can reduce the position partially;
- a protective exit has cancellation priority over an older managed BUY or
  profit-limit SELL;
- protective exits never open a short position.

### Autonomous research

A read-only research scheduler runs independently from execution. By default it:

- evaluates the strongest eligible research markets every six hours;
- runs historical backtest, walk-forward validation and stress scenarios;
- runs at least 10,000 empirical block-bootstrap Monte Carlo simulations per
  selected market;
- writes compact research results to the hash-chained Fund Ledger;
- never places, cancels or modifies a live order.

Research slot IDs are durable, so a Railway restart does not repeat an already
completed expensive run. If market data is not ready, the scheduler does not
mark the slot complete and retries safely.

### Automatic reporting

When verified NAV is available, the runtime writes idempotent immutable:

- daily fund reports;
- weekly fund reports;
- monthly fund reports.

Reports contain risk state, growth stage, recorded-fill performance,
governance controls and ledger integrity. Unverified NAV is never frozen into
an official periodic report.

### Dashboard telemetry

The Command Center exposes:

- current verified portfolio NAV and drawdown;
- active risk exposure and cash-preservation limits;
- strict >85 live-entry policy;
- current router-derived market regime;
- latest autonomous research markets and time;
- Monte Carlo risk-of-ruin and probability-of-profit statistics when a run is
  available;
- a durable realized-equity curve based on starting capital plus recorded
  realized PnL;
- open positions and managed orders;
- autonomous trade rationale and confidence;
- agent health and performance analytics.

Monte Carlo values are research statistics from sampled historical strategy
returns, not forecasts or profit guarantees.

### Operator arm boundary

Analysis, scoring, market rotation planning, sizing, paper trading, research,
backtesting, Monte Carlo, reporting and portfolio optimization operate without
per-decision user approval.

The production live-arm remains a deliberate runtime security boundary. A
deployment never arms itself, and no live order can be submitted until the
existing security, NAV, risk, profitability, allocation, exchange and
reconciliation readiness gates all pass.
