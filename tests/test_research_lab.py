"""Research Lab tests for point-in-time execution and Monte Carlo."""

from __future__ import annotations

import math

from autotrader.research.backtest import BacktestConfig, BacktestEngine
from autotrader.research.monte_carlo import MonteCarloEngine


def _trend_candles(count: int = 240):
    rows = []
    price = 100.0
    for index in range(count):
        open_price = price
        close = price * (1.0015 if index % 7 else 0.999)
        high = max(open_price, close) * 1.002
        low = min(open_price, close) * 0.998
        rows.append(
            {
                "timestamp": 1_700_000_000_000 + index * 3_600_000,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000.0 + index,
            }
        )
        price = close
    return rows


def test_backtest_uses_t_plus_one_execution_and_returns_finite_metrics():
    engine = BacktestEngine(
        BacktestConfig(
            initial_equity_eur=100,
            allocation_pct=25,
            fee_pct_each_leg=0.10,
            slippage_pct_each_leg=0.02,
        )
    )
    result = engine.run(_trend_candles(), strategy="trend", interval="1h")

    assert result["point_in_time_execution"] == "signal_on_close_T_execute_open_T_plus_1"
    assert result["candle_count"] == 240
    assert result["metrics"]["starting_equity"] > 0
    assert math.isfinite(result["metrics"]["sharpe_ratio"])
    for trade in result["trades"]:
        assert trade["exit_timestamp"] >= trade["entry_timestamp"]


def test_walk_forward_and_stress_suite_cover_required_regimes():
    engine = BacktestEngine()
    candles = _trend_candles(420)
    walk = engine.walk_forward(candles, strategy="multi_factor", interval="1h", window_size=120)
    stress = engine.stress_suite(candles, strategy="multi_factor", interval="1h")

    assert walk["window_count"] >= 3
    assert "synthetic_bull_drift" in stress["scenarios"]
    assert "synthetic_bear_drift" in stress["scenarios"]
    assert "synthetic_sideways" in stress["scenarios"]
    assert "synthetic_crash_20pct" in stress["scenarios"]
    assert "double_costs" in stress["scenarios"]


def test_monte_carlo_enforces_at_least_10000_simulations_and_is_reproducible():
    engine = MonteCarloEngine()
    returns = [0.01, -0.006, 0.004, -0.002, 0.008, 0.001] * 10

    first = engine.run(
        returns,
        initial_capital=100,
        simulations=100,
        horizon_periods=60,
        seed=7,
    )
    second = engine.run(
        returns,
        initial_capital=100,
        simulations=10000,
        horizon_periods=60,
        seed=7,
    )

    assert first["simulations"] == 10000
    assert first == second
    assert 0 <= first["risk_of_ruin_pct"] <= 100
    assert 0 <= first["probability_of_profit_pct"] <= 100
    assert len(first["confidence_interval_90_terminal_capital"]) == 2
