"""Performance analytics and Monte Carlo risk simulation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
import statistics
from typing import Sequence

from autotrader.fund.models import PerformanceMetrics


def _finite_returns(values: Sequence[float]) -> list[float]:
    result = [float(x) for x in values]
    if any(not math.isfinite(x) or x <= -1.0 for x in result):
        raise ValueError("returns must be finite decimal returns greater than -1.0")
    return result


def _max_drawdown(returns: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 1.0)
    return max_dd


def performance_metrics(returns: Sequence[float], periods_per_year: int = 365) -> PerformanceMetrics:
    r = _finite_returns(returns)
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    if not r:
        return PerformanceMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    growth = math.prod(1.0 + x for x in r)
    total_return = growth - 1.0
    years = len(r) / periods_per_year
    annualized_return = growth ** (1.0 / years) - 1.0 if growth > 0 and years > 0 else -1.0
    mean_r = statistics.fmean(r)
    stdev = statistics.stdev(r) if len(r) > 1 else 0.0
    annualized_vol = stdev * math.sqrt(periods_per_year)
    sharpe = mean_r / stdev * math.sqrt(periods_per_year) if stdev > 0 else 0.0
    downside = [min(0.0, x) for x in r]
    downside_dev = math.sqrt(statistics.fmean(x * x for x in downside)) if downside else 0.0
    sortino = mean_r / downside_dev * math.sqrt(periods_per_year) if downside_dev > 0 else 0.0
    positive = sum(x for x in r if x > 0)
    negative = abs(sum(x for x in r if x < 0))
    profit_factor = positive / negative if negative > 0 else (math.inf if positive > 0 else 0.0)
    wins = sum(1 for x in r if x > 0)

    return PerformanceMetrics(
        observations=len(r),
        total_return_pct=total_return * 100.0,
        annualized_return_pct=annualized_return * 100.0,
        annualized_volatility_pct=annualized_vol * 100.0,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        profit_factor=profit_factor,
        max_drawdown_pct=_max_drawdown(r) * 100.0,
        win_rate_pct=wins / len(r) * 100.0,
        expected_period_return_pct=mean_r * 100.0,
    )


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("cannot take percentile of empty data")
    q = max(0.0, min(1.0, q))
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


@dataclass(frozen=True)
class MonteCarloResult:
    simulations: int
    horizon_periods: int
    starting_equity_eur: float
    probability_profit_pct: float
    risk_of_ruin_pct: float
    probability_hard_drawdown_breach_pct: float
    expected_terminal_equity_eur: float
    terminal_equity_p01_eur: float
    terminal_equity_p05_eur: float
    terminal_equity_p50_eur: float
    terminal_equity_p95_eur: float
    terminal_equity_p99_eur: float
    confidence_interval_90_eur: tuple[float, float]
    worst_terminal_equity_eur: float
    worst_max_drawdown_pct: float

    def as_dict(self) -> dict:
        return asdict(self)


def run_monte_carlo(
    returns: Sequence[float],
    *,
    starting_equity_eur: float,
    simulations: int = 10_000,
    horizon_periods: int = 365,
    block_size: int = 5,
    ruin_loss_pct: float = 50.0,
    hard_drawdown_pct: float = 8.0,
    seed: int = 17,
) -> MonteCarloResult:
    source = _finite_returns(returns)
    if len(source) < 2:
        raise ValueError("at least two return observations are required")
    if starting_equity_eur <= 0:
        raise ValueError("starting_equity_eur must be positive")
    if horizon_periods <= 0:
        raise ValueError("horizon_periods must be positive")
    simulations = max(10_000, int(simulations))
    block_size = max(1, min(int(block_size), len(source)))
    ruin_floor = starting_equity_eur * (1.0 - max(0.0, min(100.0, ruin_loss_pct)) / 100.0)
    hard_dd = max(0.0, min(100.0, hard_drawdown_pct)) / 100.0
    rng = random.Random(seed)

    terminals: list[float] = []
    max_drawdowns: list[float] = []
    ruin_count = 0
    profit_count = 0
    hard_dd_count = 0
    max_start = len(source) - block_size

    for _ in range(simulations):
        equity = starting_equity_eur
        peak = equity
        max_drawdown = 0.0
        ruined = False
        generated = 0
        while generated < horizon_periods:
            start = rng.randint(0, max_start) if max_start > 0 else 0
            block = source[start:start + block_size]
            for period_return in block:
                equity *= 1.0 + period_return
                peak = max(peak, equity)
                dd = (peak - equity) / peak if peak > 0 else 1.0
                max_drawdown = max(max_drawdown, dd)
                if equity <= ruin_floor:
                    ruined = True
                generated += 1
                if generated >= horizon_periods:
                    break
        terminals.append(equity)
        max_drawdowns.append(max_drawdown)
        ruin_count += int(ruined)
        profit_count += int(equity > starting_equity_eur)
        hard_dd_count += int(max_drawdown >= hard_dd)

    terminals.sort()
    max_drawdowns.sort()
    return MonteCarloResult(
        simulations=simulations,
        horizon_periods=horizon_periods,
        starting_equity_eur=starting_equity_eur,
        probability_profit_pct=profit_count / simulations * 100.0,
        risk_of_ruin_pct=ruin_count / simulations * 100.0,
        probability_hard_drawdown_breach_pct=hard_dd_count / simulations * 100.0,
        expected_terminal_equity_eur=statistics.fmean(terminals),
        terminal_equity_p01_eur=_percentile(terminals, 0.01),
        terminal_equity_p05_eur=_percentile(terminals, 0.05),
        terminal_equity_p50_eur=_percentile(terminals, 0.50),
        terminal_equity_p95_eur=_percentile(terminals, 0.95),
        terminal_equity_p99_eur=_percentile(terminals, 0.99),
        confidence_interval_90_eur=(_percentile(terminals, 0.05), _percentile(terminals, 0.95)),
        worst_terminal_equity_eur=terminals[0],
        worst_max_drawdown_pct=max_drawdowns[-1] * 100.0,
    )
