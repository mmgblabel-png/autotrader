from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader.api.server import _sync_shadow_canary
from autotrader.core.order_manager import OrderManager, OrderSide
from autotrader.core.shadow_strategy_engine import ShadowStats, ShadowStrategyEngine
from autotrader.strategies.shadow_canary import ShadowCanaryStrategy


class AllowRisk:
    def is_killed(self, _name):
        return False

    def max_entry_notional(self, _name, *, symbol=""):
        return 100.0

    def check_order(self, _name, notional, *, risk_reducing=False, **_kwargs):
        return bool(risk_reducing or float(notional) <= 100.0)


class DummyProfit:
    pass


def _canary_config(path: Path) -> dict:
    return {
        "enabled": True,
        "live_capable": True,
        "allocation_eur": 6.0,
        "max_order_eur": 6.0,
        "max_open_orders": 1,
        "symbol": "BTC-EUR",
        "exchange": "bitvavo",
        "canary_order_eur": 6.0,
        "runtime_state_path": str(path),
        "estimated_fee_pct": 0.25,
        "estimated_slippage_pct": 0.05,
        "_live_balance_snapshot_ready": True,
        "_exchange_open_orders_snapshot_ready": True,
        "_exchange_open_order_count": 0,
        "_available_quote": 20.0,
        "_available_base": 0.0,
        "_quote_to_eur": 1.0,
        "_min_order_base": 0.0,
        "_min_order_quote": 5.0,
    }


def _candidate() -> dict:
    return {
        "enabled": True,
        "kind": "volatility_breakout",
        "strategy_version": "v3",
        "symbol": "STRK-EUR",
        "exchange": "bitvavo",
        "lookback": 10,
        "breakout_buffer_pct": 0.10,
        "min_avg_move_pct": 0.0,
        "min_vol_expansion_ratio": 0.0,
        "max_entry_spike_pct": 1.25,
        "min_exit_net_pct": 0.75,
        "take_profit_pct": 1.50,
        "stop_loss_pct": 0.75,
        "trailing_exit_pct": 0.45,
    }


def test_shadow_status_exposes_canary_ready_and_blockers(tmp_path: Path):
    engine = ShadowStrategyEngine(
        {
            "path": str(tmp_path / "shadow.json"),
            "fee_pct_each_leg": 0.25,
            "slippage_pct_each_leg": 0.05,
            "promotion_min_completed_trades": 24,
            "promotion_min_winrate_pct": 55.0,
            "promotion_min_net_pnl_eur": 0.15,
            "promotion_min_profit_factor": 1.10,
            "promotion_max_drawdown_pct": 6.0,
            "canary_min_completed_trades": 12,
            "canary_min_winrate_pct": 52.0,
            "canary_min_net_pnl_eur": 0.10,
            "canary_min_profit_factor": 1.05,
            "canary_max_drawdown_pct": 5.0,
        }
    )
    engine._states["volatility_breakout@STRK-EUR"] = ShadowStats(
        completed_trades=12,
        wins=8,
        losses=4,
        realized_net_pnl_eur=0.50,
        outcomes=[0.10] * 8 + [-0.075] * 4,
        max_drawdown_eur=0.06,
        strategy_version="v3",
    )
    row = engine.status(
        {"volatility_breakout@STRK-EUR": {**_candidate(), "shadow_order_eur": 6.0}}
    )["strategies"][0]

    assert row["canary_ready"] is True
    assert row["canary_blockers"] == []
    assert row["promotion_ready"] is False
    assert "completed_trades" in row["promotion_blockers"]


def test_canary_configure_persists_candidate_across_restart(tmp_path: Path):
    state = tmp_path / "canary.json"
    first = ShadowCanaryStrategy(
        OrderManager(), AllowRisk(), DummyProfit(), _canary_config(state)
    )
    assert first.configure_candidate(
        "volatility_breakout@STRK-EUR",
        _candidate(),
        {"canary_ready": True, "score": 80.4, "realized_net_pnl_eur": 0.37},
    )
    assert first.candidate_locked is True
    assert first.candidate_name == "volatility_breakout@STRK-EUR"

    second = ShadowCanaryStrategy(
        OrderManager(), AllowRisk(), DummyProfit(), _canary_config(state)
    )
    assert second.candidate_locked is True
    assert second.candidate_name == "volatility_breakout@STRK-EUR"
    assert second._config["symbol"] == "STRK-EUR"
    assert second._config["kind"] == "volatility_breakout"


def test_canary_places_at_most_six_eur_entry(tmp_path: Path):
    om = OrderManager()
    strategy = ShadowCanaryStrategy(
        om, AllowRisk(), DummyProfit(), _canary_config(tmp_path / "canary.json")
    )
    assert strategy.configure_candidate(
        "volatility_breakout@STRK-EUR",
        _candidate(),
        {"canary_ready": True, "score": 80.4, "realized_net_pnl_eur": 0.37},
    )
    strategy._config.update(
        {
            "_live_balance_snapshot_ready": True,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
            "_available_quote": 20.0,
            "_available_base": 0.0,
            "_quote_to_eur": 1.0,
            "_min_order_base": 0.0,
            "_min_order_quote": 5.0,
            "_current_price": 1.002,
            "_autonomous_entry_allowed": True,
            "_evidence_entry_blocked": False,
        }
    )
    strategy._prices = [1.0] * 10
    strategy.start()
    strategy.tick()

    orders = list(om._orders.values())
    assert len(orders) == 1
    order = orders[0]
    assert order.side is OrderSide.BUY
    assert order.symbol == "STRK-EUR"
    assert order.strategy == "ShadowCanary"
    assert order.quantity * order.price * order.quote_to_eur <= 6.0 + 1e-6
    assert order.quantity * order.price * order.quote_to_eur >= 5.0


def test_sync_shadow_canary_locks_highest_ready_flat_candidate(tmp_path: Path):
    canary = ShadowCanaryStrategy(
        OrderManager(), AllowRisk(), DummyProfit(), _canary_config(tmp_path / "canary.json")
    )
    agent = SimpleNamespace(_strategies={"shadow_canary": canary})
    configs = {
        "mean_reversion@ADA-EUR": {
            **_candidate(),
            "kind": "mean_reversion",
            "symbol": "ADA-EUR",
        },
        "volatility_breakout@STRK-EUR": _candidate(),
    }
    status = {
        "strategies": [
            {
                "name": "mean_reversion@ADA-EUR",
                "canary_ready": True,
                "position_open": False,
                "score": 72.0,
                "stressed_net_pnl_eur": 0.15,
                "completed_trades": 14,
                "realized_net_pnl_eur": 0.20,
            },
            {
                "name": "volatility_breakout@STRK-EUR",
                "canary_ready": True,
                "position_open": False,
                "score": 80.4,
                "stressed_net_pnl_eur": 0.31,
                "completed_trades": 13,
                "realized_net_pnl_eur": 0.37,
            },
        ]
    }

    result = _sync_shadow_canary(agent, status, configs)
    assert result["locked"] is True
    assert result["candidate"] == "volatility_breakout@STRK-EUR"
    assert canary._config["symbol"] == "STRK-EUR"
