"""Point-in-time spot backtesting with T+1 execution and explicit costs."""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Any, Mapping, Sequence

from autotrader.research.metrics import performance_metrics


_INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity_eur: float = 100.0
    allocation_pct: float = 25.0
    fee_pct_each_leg: float = 0.25
    slippage_pct_each_leg: float = 0.05
    min_history: int = 30
    trend_fast: int = 10
    trend_slow: int = 30
    momentum_lookback: int = 12
    mean_reversion_lookback: int = 20
    mean_reversion_entry_z: float = 1.5

    def validate(self) -> None:
        if self.initial_equity_eur <= 0:
            raise ValueError("initial_equity_eur must be positive")
        if not 0 < self.allocation_pct <= 100:
            raise ValueError("allocation_pct must be in (0, 100]")
        if self.fee_pct_each_leg < 0 or self.slippage_pct_each_leg < 0:
            raise ValueError("fees and slippage must be non-negative")
        if self.min_history < 5:
            raise ValueError("min_history must be at least 5")
        if self.trend_fast <= 1 or self.trend_slow <= self.trend_fast:
            raise ValueError("trend_slow must exceed trend_fast")


class BacktestEngine:
    """Long-only crypto research engine.

    Signals are calculated using candle T close and can only execute at candle
    T+1 open. This deliberately prevents same-bar look-ahead execution.
    """

    SUPPORTED_STRATEGIES = {"trend", "momentum", "mean_reversion", "multi_factor"}

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self.config.validate()

    @staticmethod
    def normalize_candles(candles: Sequence[Mapping[str, Any]]) -> list[dict[str, float | int]]:
        rows: list[dict[str, float | int]] = []
        for raw in candles:
            try:
                row = {
                    "timestamp": int(raw["timestamp"]),
                    "open": float(raw["open"]),
                    "high": float(raw["high"]),
                    "low": float(raw["low"]),
                    "close": float(raw["close"]),
                    "volume": float(raw.get("volume", 0.0)),
                }
            except (KeyError, TypeError, ValueError):
                continue
            prices = [row["open"], row["high"], row["low"], row["close"]]
            if any(not math.isfinite(float(value)) or float(value) <= 0 for value in prices):
                continue
            if not math.isfinite(float(row["volume"])) or float(row["volume"]) < 0:
                continue
            rows.append(row)
        rows.sort(key=lambda item: int(item["timestamp"]))
        deduped: list[dict[str, float | int]] = []
        for row in rows:
            if deduped and row["timestamp"] == deduped[-1]["timestamp"]:
                deduped[-1] = row
            else:
                deduped.append(row)
        return deduped

    @staticmethod
    def periods_per_year(interval: str) -> float:
        seconds = _INTERVAL_SECONDS.get(interval)
        if seconds is None:
            raise ValueError(f"unsupported interval: {interval}")
        return (365.25 * 24.0 * 3600.0) / seconds

    def run(
        self,
        candles: Sequence[Mapping[str, Any]],
        *,
        strategy: str,
        interval: str = "1h",
    ) -> dict[str, Any]:
        strategy_key = strategy.strip().lower()
        if strategy_key not in self.SUPPORTED_STRATEGIES:
            raise ValueError(f"unsupported strategy: {strategy}")

        rows = self.normalize_candles(candles)
        if len(rows) < self.config.min_history + 2:
            raise ValueError(
                f"at least {self.config.min_history + 2} valid candles are required"
            )

        cash = float(self.config.initial_equity_eur)
        quantity = 0.0
        entry_cash = 0.0
        entry_price = 0.0
        entry_time = 0
        pending_target: int | None = None

        equity_curve: list[float] = []
        timestamps: list[int] = []
        trades: list[dict[str, Any]] = []

        for i, row in enumerate(rows):
            open_price = float(row["open"])
            close_price = float(row["close"])

            if pending_target is not None:
                if pending_target == 1 and quantity <= 0:
                    current_equity = cash
                    budget = min(
                        cash,
                        current_equity * self.config.allocation_pct / 100.0,
                    )
                    if budget > 0:
                        fill_price = open_price * (
                            1.0 + self.config.slippage_pct_each_leg / 100.0
                        )
                        fee = budget * self.config.fee_pct_each_leg / 100.0
                        investable = max(0.0, budget - fee)
                        if fill_price > 0 and investable > 0:
                            quantity = investable / fill_price
                            cash -= budget
                            entry_cash = budget
                            entry_price = fill_price
                            entry_time = int(row["timestamp"])
                elif pending_target == 0 and quantity > 0:
                    fill_price = open_price * (
                        1.0 - self.config.slippage_pct_each_leg / 100.0
                    )
                    gross = quantity * fill_price
                    fee = gross * self.config.fee_pct_each_leg / 100.0
                    proceeds = max(0.0, gross - fee)
                    pnl = proceeds - entry_cash
                    cash += proceeds
                    trades.append(
                        {
                            "entry_timestamp": entry_time,
                            "exit_timestamp": int(row["timestamp"]),
                            "entry_price": round(entry_price, 12),
                            "exit_price": round(fill_price, 12),
                            "net_pnl_eur": round(pnl, 10),
                            "net_return_pct": round(
                                (pnl / entry_cash * 100.0) if entry_cash > 0 else 0.0,
                                10,
                            ),
                        }
                    )
                    quantity = 0.0
                    entry_cash = 0.0
                    entry_price = 0.0
                    entry_time = 0

            equity = cash + quantity * close_price
            equity_curve.append(max(0.0, equity))
            timestamps.append(int(row["timestamp"]))

            if i < len(rows) - 1:
                signal = self._desired_position(rows, i, strategy_key, quantity > 0)
                if signal is not None:
                    pending_target = signal

        if quantity > 0:
            final = rows[-1]
            fill_price = float(final["close"]) * (
                1.0 - self.config.slippage_pct_each_leg / 100.0
            )
            gross = quantity * fill_price
            fee = gross * self.config.fee_pct_each_leg / 100.0
            proceeds = max(0.0, gross - fee)
            pnl = proceeds - entry_cash
            cash += proceeds
            trades.append(
                {
                    "entry_timestamp": entry_time,
                    "exit_timestamp": int(final["timestamp"]),
                    "entry_price": round(entry_price, 12),
                    "exit_price": round(fill_price, 12),
                    "net_pnl_eur": round(pnl, 10),
                    "net_return_pct": round(
                        (pnl / entry_cash * 100.0) if entry_cash > 0 else 0.0,
                        10,
                    ),
                }
            )
            quantity = 0.0
            equity_curve[-1] = cash

        period_returns = []
        for previous, current in zip(equity_curve, equity_curve[1:]):
            period_returns.append((current / previous - 1.0) if previous > 0 else 0.0)

        metrics = performance_metrics(
            equity_curve,
            period_returns,
            [float(row["net_pnl_eur"]) for row in trades],
            periods_per_year=self.periods_per_year(interval),
        )
        return {
            "strategy": strategy_key,
            "interval": interval,
            "candle_count": len(rows),
            "first_timestamp": int(rows[0]["timestamp"]),
            "last_timestamp": int(rows[-1]["timestamp"]),
            "point_in_time_execution": "signal_on_close_T_execute_open_T_plus_1",
            "cost_model": {
                "fee_pct_each_leg": self.config.fee_pct_each_leg,
                "slippage_pct_each_leg": self.config.slippage_pct_each_leg,
                "allocation_pct": self.config.allocation_pct,
            },
            "metrics": metrics,
            "trades": trades,
            "equity_curve": [
                {"timestamp": ts, "equity_eur": round(value, 10)}
                for ts, value in zip(timestamps, equity_curve)
            ],
            "period_returns": period_returns,
        }

    def walk_forward(
        self,
        candles: Sequence[Mapping[str, Any]],
        *,
        strategy: str,
        interval: str = "1h",
        window_size: int = 180,
    ) -> dict[str, Any]:
        rows = self.normalize_candles(candles)
        minimum = self.config.min_history + 2
        size = max(minimum, int(window_size))
        windows = []
        for start in range(0, len(rows) - minimum + 1, size):
            chunk = rows[start : start + size]
            if len(chunk) < minimum:
                break
            result = self.run(chunk, strategy=strategy, interval=interval)
            windows.append(
                {
                    "start_timestamp": result["first_timestamp"],
                    "end_timestamp": result["last_timestamp"],
                    "metrics": result["metrics"],
                }
            )
        returns = [
            float(window["metrics"]["total_return_pct"])
            for window in windows
        ]
        drawdowns = [
            float(window["metrics"]["max_drawdown_pct"])
            for window in windows
        ]
        sharpes = [
            float(window["metrics"]["sharpe_ratio"])
            for window in windows
        ]
        return {
            "window_size": size,
            "window_count": len(windows),
            "windows": windows,
            "aggregate": {
                "mean_return_pct": round(statistics.fmean(returns), 8) if returns else 0.0,
                "median_return_pct": round(statistics.median(returns), 8) if returns else 0.0,
                "positive_window_pct": round(
                    (sum(1 for value in returns if value > 0) / len(returns) * 100.0)
                    if returns else 0.0,
                    8,
                ),
                "worst_drawdown_pct": round(max(drawdowns), 8) if drawdowns else 0.0,
                "median_sharpe": round(statistics.median(sharpes), 8) if sharpes else 0.0,
            },
        }

    def stress_suite(
        self,
        candles: Sequence[Mapping[str, Any]],
        *,
        strategy: str,
        interval: str = "1h",
    ) -> dict[str, Any]:
        rows = self.normalize_candles(candles)
        scenarios: dict[str, tuple[list[dict[str, float | int]], BacktestConfig]] = {
            "base": (rows, self.config),
            "double_costs": (
                rows,
                BacktestConfig(
                    **{
                        **self.config.__dict__,
                        "fee_pct_each_leg": self.config.fee_pct_each_leg * 2.0,
                        "slippage_pct_each_leg": self.config.slippage_pct_each_leg * 2.0,
                    }
                ),
            ),
            "triple_slippage": (
                rows,
                BacktestConfig(
                    **{
                        **self.config.__dict__,
                        "slippage_pct_each_leg": self.config.slippage_pct_each_leg * 3.0,
                    }
                ),
            ),
            "synthetic_crash_20pct": (self._shock_prices(rows, -0.20), self.config),
            "synthetic_bull_drift": (self._drift_prices(rows, 0.0005), self.config),
            "synthetic_bear_drift": (self._drift_prices(rows, -0.0005), self.config),
            "synthetic_sideways": (self._sideways_prices(rows), self.config),
        }
        output = {}
        for name, (scenario_rows, config) in scenarios.items():
            engine = BacktestEngine(config)
            result = engine.run(scenario_rows, strategy=strategy, interval=interval)
            output[name] = result["metrics"]
        return {
            "scenarios": output,
            "note": (
                "Synthetic scenarios are deterministic stress transformations, "
                "not forecasts or historical claims."
            ),
        }

    def _desired_position(
        self,
        rows: Sequence[Mapping[str, float | int]],
        index: int,
        strategy: str,
        invested: bool,
    ) -> int | None:
        closes = [float(row["close"]) for row in rows[: index + 1]]
        volumes = [float(row["volume"]) for row in rows[: index + 1]]
        if len(closes) < self.config.min_history:
            return None

        if strategy == "trend":
            fast = statistics.fmean(closes[-self.config.trend_fast :])
            slow = statistics.fmean(closes[-self.config.trend_slow :])
            return 1 if fast > slow * 1.001 else 0

        if strategy == "momentum":
            lookback = self.config.momentum_lookback
            if len(closes) <= lookback:
                return None
            momentum = closes[-1] / closes[-1 - lookback] - 1.0
            return 1 if momentum > 0.005 else 0

        lookback = self.config.mean_reversion_lookback
        window = closes[-lookback:]
        mean = statistics.fmean(window)
        std = statistics.pstdev(window)
        z = (closes[-1] - mean) / std if std > 0 else 0.0

        if strategy == "mean_reversion":
            if not invested and z <= -self.config.mean_reversion_entry_z:
                return 1
            if invested and z >= 0.0:
                return 0
            return None

        fast = statistics.fmean(closes[-self.config.trend_fast :])
        slow = statistics.fmean(closes[-self.config.trend_slow :])
        trend = max(-1.0, min(1.0, ((fast / slow) - 1.0) / 0.01)) if slow else 0.0
        mlook = self.config.momentum_lookback
        momentum_raw = closes[-1] / closes[-1 - mlook] - 1.0
        momentum = max(-1.0, min(1.0, momentum_raw / 0.02))
        reversion = max(-1.0, min(1.0, -z / 2.0))
        volume_window = volumes[-20:]
        volume_mean = statistics.fmean(volume_window) if volume_window else 0.0
        volume_factor = (
            max(-1.0, min(1.0, (volumes[-1] / volume_mean - 1.0)))
            if volume_mean > 0 else 0.0
        )
        score = (
            0.35 * trend
            + 0.35 * momentum
            + 0.20 * reversion
            + 0.10 * volume_factor
        )
        if not invested and score >= 0.30:
            return 1
        if invested and score <= -0.10:
            return 0
        return None

    @staticmethod
    def _shock_prices(
        rows: Sequence[Mapping[str, float | int]],
        shock: float,
    ) -> list[dict[str, float | int]]:
        pivot = max(1, int(len(rows) * 0.60))
        output = []
        for index, raw in enumerate(rows):
            row = dict(raw)
            factor = 1.0 + shock if index >= pivot else 1.0
            for key in ("open", "high", "low", "close"):
                row[key] = max(1e-12, float(row[key]) * factor)
            output.append(row)
        return output

    @staticmethod
    def _drift_prices(
        rows: Sequence[Mapping[str, float | int]],
        drift_per_bar: float,
    ) -> list[dict[str, float | int]]:
        output = []
        for index, raw in enumerate(rows):
            row = dict(raw)
            factor = (1.0 + drift_per_bar) ** index
            for key in ("open", "high", "low", "close"):
                row[key] = max(1e-12, float(row[key]) * factor)
            output.append(row)
        return output

    @staticmethod
    def _sideways_prices(
        rows: Sequence[Mapping[str, float | int]],
    ) -> list[dict[str, float | int]]:
        if not rows:
            return []
        anchor = float(rows[0]["close"])
        output = []
        for raw in rows:
            row = dict(raw)
            close = float(row["close"])
            factor = (anchor + (close - anchor) * 0.20) / close if close > 0 else 1.0
            for key in ("open", "high", "low", "close"):
                row[key] = max(1e-12, float(row[key]) * factor)
            output.append(row)
        return output
