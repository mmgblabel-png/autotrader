"""Research Lab orchestration using public historical Bitvavo candles."""

from __future__ import annotations

from typing import Any, Mapping

from autotrader.research.backtest import BacktestConfig, BacktestEngine
from autotrader.research.monte_carlo import MonteCarloEngine


class ResearchLab:
    """Read-only research layer. It cannot create or submit exchange orders."""

    def __init__(
        self,
        market_adapter,
        config: Mapping[str, Any] | None = None,
        profit_policy: Mapping[str, Any] | None = None,
    ) -> None:
        self.market_adapter = market_adapter
        self.config = dict(config or {})
        policy = dict(profit_policy or {})
        fee = float(
            self.config.get(
                "fee_pct_each_leg",
                max(
                    float(policy.get("estimated_entry_fee_pct", 0.25)),
                    float(policy.get("estimated_exit_fee_pct", 0.25)),
                ),
            )
        )
        slippage = float(
            self.config.get(
                "slippage_pct_each_leg",
                policy.get("estimated_slippage_each_leg_pct", 0.05),
            )
        )
        self.backtest_config = BacktestConfig(
            initial_equity_eur=float(self.config.get("initial_equity_eur", 100.0)),
            allocation_pct=float(self.config.get("allocation_pct", 25.0)),
            fee_pct_each_leg=fee,
            slippage_pct_each_leg=slippage,
            min_history=int(self.config.get("min_history", 30)),
            trend_fast=int(self.config.get("trend_fast", 10)),
            trend_slow=int(self.config.get("trend_slow", 30)),
            momentum_lookback=int(self.config.get("momentum_lookback", 12)),
            mean_reversion_lookback=int(self.config.get("mean_reversion_lookback", 20)),
            mean_reversion_entry_z=float(self.config.get("mean_reversion_entry_z", 1.5)),
        )
        self.backtester = BacktestEngine(self.backtest_config)
        self.monte_carlo = MonteCarloEngine()

    def candles(self, market: str, interval: str, limit: int) -> list[dict[str, Any]]:
        safe_limit = max(64, min(int(self.config.get("max_candles", 1440)), int(limit)))
        return self.market_adapter.candles(
            market.upper(),
            interval=interval,
            limit=safe_limit,
        )

    def backtest_market(
        self,
        market: str,
        *,
        interval: str = "1h",
        strategy: str = "multi_factor",
        limit: int = 720,
    ) -> dict[str, Any]:
        candles = self.candles(market, interval, limit)
        result = self.backtester.run(candles, strategy=strategy, interval=interval)
        result["market"] = market.upper()
        return result

    def monte_carlo_market(
        self,
        market: str,
        *,
        interval: str = "1h",
        strategy: str = "multi_factor",
        limit: int = 720,
        simulations: int = 10000,
        horizon_periods: int = 365,
    ) -> dict[str, Any]:
        backtest = self.backtest_market(
            market,
            interval=interval,
            strategy=strategy,
            limit=limit,
        )
        monte = self.monte_carlo.run(
            backtest["period_returns"],
            initial_capital=float(backtest["metrics"]["starting_equity"]),
            simulations=max(10000, int(simulations)),
            horizon_periods=horizon_periods,
            ruin_drawdown_pct=float(self.config.get("ruin_drawdown_pct", 30.0)),
            block_size=int(self.config.get("monte_carlo_block_size", 5)),
            seed=int(self.config.get("monte_carlo_seed", 42)),
        )
        return {
            "market": market.upper(),
            "strategy": strategy,
            "interval": interval,
            "backtest_metrics": backtest["metrics"],
            "monte_carlo": monte,
        }

    def full_report(
        self,
        market: str,
        *,
        interval: str = "1h",
        strategy: str = "multi_factor",
        limit: int = 720,
        simulations: int = 10000,
    ) -> dict[str, Any]:
        candles = self.candles(market, interval, limit)
        backtest = self.backtester.run(candles, strategy=strategy, interval=interval)
        walk_forward = self.backtester.walk_forward(
            candles,
            strategy=strategy,
            interval=interval,
            window_size=int(self.config.get("walk_forward_window", 180)),
        )
        stress = self.backtester.stress_suite(
            candles,
            strategy=strategy,
            interval=interval,
        )
        horizon = min(
            int(self.config.get("monte_carlo_horizon_periods", 365)),
            max(1, len(backtest["period_returns"])),
        )
        monte = self.monte_carlo.run(
            backtest["period_returns"],
            initial_capital=float(backtest["metrics"]["starting_equity"]),
            simulations=max(10000, int(simulations)),
            horizon_periods=horizon,
            ruin_drawdown_pct=float(self.config.get("ruin_drawdown_pct", 30.0)),
            block_size=int(self.config.get("monte_carlo_block_size", 5)),
            seed=int(self.config.get("monte_carlo_seed", 42)),
        )
        return {
            "market": market.upper(),
            "strategy": strategy,
            "interval": interval,
            "backtest": {
                key: value
                for key, value in backtest.items()
                if key != "period_returns"
            },
            "walk_forward": walk_forward,
            "stress": stress,
            "monte_carlo": monte,
            "research_only": True,
            "live_orders_sent": False,
        }
