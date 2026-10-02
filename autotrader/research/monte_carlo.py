"""Bootstrap Monte Carlo for empirical strategy return paths."""

from __future__ import annotations

import math
import random
from typing import Sequence


class MonteCarloEngine:
    """Run block-bootstrap simulations without assuming normal returns."""

    @staticmethod
    def _percentile(sorted_values: Sequence[float], pct: float) -> float:
        if not sorted_values:
            return 0.0
        p = max(0.0, min(100.0, float(pct)))
        position = (len(sorted_values) - 1) * p / 100.0
        low = int(math.floor(position))
        high = int(math.ceil(position))
        if low == high:
            return float(sorted_values[low])
        fraction = position - low
        return float(sorted_values[low] * (1.0 - fraction) + sorted_values[high] * fraction)

    def run(
        self,
        period_returns: Sequence[float],
        *,
        initial_capital: float = 100.0,
        simulations: int = 10000,
        horizon_periods: int = 365,
        ruin_drawdown_pct: float = 30.0,
        block_size: int = 5,
        seed: int = 42,
    ) -> dict[str, object]:
        returns = []
        for raw in period_returns:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > -1.0:
                returns.append(value)
        if not returns:
            returns = [0.0]

        count = max(10000, min(50000, int(simulations)))
        horizon = max(1, min(5000, int(horizon_periods)))
        block = max(1, min(len(returns), int(block_size)))
        capital0 = float(initial_capital)
        if not math.isfinite(capital0) or capital0 <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 < ruin_drawdown_pct < 100:
            raise ValueError("ruin_drawdown_pct must be between 0 and 100")

        rng = random.Random(int(seed))
        ruin_floor = capital0 * (1.0 - ruin_drawdown_pct / 100.0)
        terminal: list[float] = []
        drawdowns: list[float] = []
        ruined_count = 0
        profitable_count = 0

        for _ in range(count):
            capital = capital0
            peak = capital0
            worst_dd = 0.0
            ruined = False
            path_index = 0
            block_returns: list[float] = []

            for step in range(horizon):
                if path_index >= len(block_returns):
                    start = rng.randrange(0, len(returns))
                    block_returns = [
                        returns[(start + offset) % len(returns)]
                        for offset in range(block)
                    ]
                    path_index = 0

                capital *= 1.0 + block_returns[path_index]
                path_index += 1
                capital = max(0.0, capital)
                peak = max(peak, capital)
                if peak > 0:
                    worst_dd = max(worst_dd, (peak - capital) / peak)
                if capital <= ruin_floor:
                    ruined = True

            terminal.append(capital)
            drawdowns.append(worst_dd * 100.0)
            ruined_count += int(ruined)
            profitable_count += int(capital > capital0)

        terminal.sort()
        drawdowns.sort()
        return {
            "simulations": count,
            "horizon_periods": horizon,
            "block_size": block,
            "initial_capital": round(capital0, 8),
            "risk_of_ruin_pct": round(ruined_count / count * 100.0, 6),
            "probability_of_profit_pct": round(profitable_count / count * 100.0, 6),
            "terminal_capital": {
                "p01": round(self._percentile(terminal, 1), 8),
                "p05": round(self._percentile(terminal, 5), 8),
                "p50": round(self._percentile(terminal, 50), 8),
                "p95": round(self._percentile(terminal, 95), 8),
                "p99": round(self._percentile(terminal, 99), 8),
                "worst": round(terminal[0], 8),
                "best": round(terminal[-1], 8),
            },
            "max_drawdown_pct": {
                "p50": round(self._percentile(drawdowns, 50), 8),
                "p95": round(self._percentile(drawdowns, 95), 8),
                "p99": round(self._percentile(drawdowns, 99), 8),
                "worst": round(drawdowns[-1], 8),
            },
            "confidence_interval_90_terminal_capital": [
                round(self._percentile(terminal, 5), 8),
                round(self._percentile(terminal, 95), 8),
            ],
            "ruin_definition": (
                f"capital at or below {100.0 - ruin_drawdown_pct:.2f}% "
                "of starting capital at any point"
            ),
            "method": "empirical circular block bootstrap",
            "warning": "Monte Carlo summarizes sampled historical strategy returns; it is not a profit forecast.",
        }
