"""Dependency-free portfolio and strategy performance metrics."""

from __future__ import annotations

import math
import statistics
from typing import Iterable, Sequence


def _finite(values: Iterable[float]) -> list[float]:
    output = []
    for raw in values:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            output.append(value)
    return output


def max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    values = _finite(equity_curve)
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst * 100.0


def performance_metrics(
    equity_curve: Sequence[float],
    period_returns: Sequence[float],
    trade_pnls: Sequence[float],
    *,
    periods_per_year: float,
) -> dict[str, float | int | None]:
    equity = _finite(equity_curve)
    returns = _finite(period_returns)
    pnls = _finite(trade_pnls)

    if not equity:
        return {
            "starting_equity": 0.0,
            "ending_equity": 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "profit_factor": None,
            "win_rate_pct": 0.0,
            "expected_return_pct_per_period": 0.0,
            "trade_count": 0,
        }

    start = equity[0]
    end = equity[-1]
    total_return = ((end / start) - 1.0) * 100.0 if start > 0 else 0.0

    sharpe = 0.0
    sortino = 0.0
    if len(returns) >= 2:
        mean_return = statistics.fmean(returns)
        std = statistics.stdev(returns)
        if std > 0 and periods_per_year > 0:
            sharpe = mean_return / std * math.sqrt(periods_per_year)

        downside = [min(0.0, value) for value in returns]
        downside_deviation = math.sqrt(statistics.fmean([value * value for value in downside]))
        if downside_deviation > 0 and periods_per_year > 0:
            sortino = mean_return / downside_deviation * math.sqrt(periods_per_year)

    positive = sum(value for value in pnls if value > 0)
    negative = abs(sum(value for value in pnls if value < 0))
    profit_factor = positive / negative if negative > 0 else (None if positive <= 0 else None)
    wins = sum(1 for value in pnls if value > 0)

    return {
        "starting_equity": round(start, 8),
        "ending_equity": round(end, 8),
        "total_return_pct": round(total_return, 8),
        "max_drawdown_pct": round(max_drawdown_pct(equity), 8),
        "sharpe_ratio": round(sharpe, 8),
        "sortino_ratio": round(sortino, 8),
        "profit_factor": round(profit_factor, 8) if profit_factor is not None else None,
        "win_rate_pct": round((wins / len(pnls) * 100.0) if pnls else 0.0, 8),
        "expected_return_pct_per_period": round(
            (statistics.fmean(returns) * 100.0) if returns else 0.0,
            10,
        ),
        "trade_count": len(pnls),
    }
