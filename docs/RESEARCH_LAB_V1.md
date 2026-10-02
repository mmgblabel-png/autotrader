# Research Lab v1

Research Lab is a read-only validation layer for Fund Core.

## Guarantees

- Signals use candle T information only.
- Orders in a backtest execute no earlier than candle T+1 open.
- Fees and slippage are deducted on every leg.
- Backtests never call the live execution coordinator.
- Monte Carlo uses empirical block bootstrapping rather than a Gaussian-return assumption.
- Monte Carlo always runs at least 10,000 simulations.
- Synthetic bull, bear, sideways and crash scenarios are explicitly labelled as synthetic stress tests.

## API

Authenticated routes:

- `GET /api/research/backtest`
- `GET /api/research/monte-carlo`
- `GET /api/research/full-report`

Supported research strategies are `trend`, `momentum`, `mean_reversion`, and `multi_factor`.

The output includes total return, Sharpe, Sortino, profit factor when defined, win rate, max drawdown, expected period return, walk-forward windows, stress results, risk of ruin, probability of profit and terminal-capital confidence intervals.

These statistics describe the supplied historical sample and simulated resamples. They are not a guarantee or forecast of future profit.
