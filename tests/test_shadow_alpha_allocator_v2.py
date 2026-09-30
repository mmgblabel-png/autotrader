from pathlib import Path

from autotrader.core.shadow_strategy_engine import ShadowStrategyEngine
from autotrader.core.strategy_allocator_v2 import StrategyAllocatorV2


def test_mean_reversion_shadow_round_trip_persists(tmp_path: Path):
    path = tmp_path / "shadow.json"
    engine = ShadowStrategyEngine({
        "path": str(path),
        "fee_pct_each_leg": 0.25,
        "slippage_pct_each_leg": 0.05,
        "promotion_min_completed_trades": 20,
    })
    cfg = {
        "kind": "mean_reversion",
        "symbol": "ETH-EUR",
        "shadow_order_eur": 6.0,
        "lookback": 8,
        "entry_z": 1.0,
        "exit_z": -0.1,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 2.0,
    }
    for price in [100, 100, 100, 100, 100, 100, 100, 90]:
        engine.update("mean_reversion", price, cfg)
    status = engine.status({"mean_reversion": cfg})
    assert status["live_orders_sent"] is False
    assert status["strategies"][0]["position_open"] is True

    engine.update("mean_reversion", 100, cfg)
    row = engine.status({"mean_reversion": cfg})["strategies"][0]
    assert row["completed_trades"] == 1
    assert row["realized_net_pnl_eur"] > 0
    assert row["promotable"] is False

    restored = ShadowStrategyEngine({"path": str(path)})
    restored_row = restored.status({"mean_reversion": cfg})["strategies"][0]
    assert restored_row["completed_trades"] == 1
    assert restored_row["realized_net_pnl_eur"] > 0


def test_breakout_shadow_round_trip_never_live(tmp_path: Path):
    engine = ShadowStrategyEngine({"path": str(tmp_path / "shadow.json")})
    cfg = {
        "kind": "volatility_breakout",
        "symbol": "ADA-EUR",
        "shadow_order_eur": 6.0,
        "lookback": 10,
        "breakout_buffer_pct": 0.05,
        "min_avg_move_pct": 0.0,
        "take_profit_pct": 0.5,
        "stop_loss_pct": 1.0,
        "trailing_exit_pct": 0.3,
    }
    for price in [1.0] * 11:
        engine.update("volatility_breakout", price, cfg)
    engine.update("volatility_breakout", 1.01, cfg)
    assert engine.status({"volatility_breakout": cfg})["strategies"][0]["position_open"]
    engine.update("volatility_breakout", 1.03, cfg)
    status = engine.status({"volatility_breakout": cfg})
    assert status["live_orders_sent"] is False
    assert status["strategies"][0]["completed_trades"] == 1


def test_allocator_v2_is_advisory_and_bounded():
    allocator = StrategyAllocatorV2({
        "enabled": True,
        "apply_live": False,
        "min_samples": 2,
        "max_shift_pct": 25,
        "min_allocation_eur": 5,
    })
    strategy_cfg = {
        "market_maker": {"enabled": True, "live_capable": True, "allocation_eur": 15},
        "grid": {"enabled": True, "live_capable": True, "allocation_eur": 15},
        "mean_reversion": {"enabled": True, "shadow_order_eur": 6},
    }
    live_stats = {
        "MarketMaker": {"net_pnl": 2.0, "wins": 3, "losses": 1, "winrate_pct": 75.0},
        "GridRunner": {"net_pnl": -1.0, "wins": 1, "losses": 3, "winrate_pct": 25.0},
    }
    shadow = [{
        "name": "mean_reversion",
        "completed_trades": 4,
        "realized_net_pnl_eur": 1.0,
        "winrate_pct": 75.0,
        "max_drawdown_pct": 2.0,
    }]
    result = allocator.recommendations(strategy_cfg, live_stats, shadow, 50.0)
    assert result["mode"] == "advisory"
    assert result["apply_live"] is False
    assert result["live_allocations_changed"] is False
    assert sum(x["recommended_allocation_eur"] for x in result["recommendations"]) <= 50.01


def test_dashboard_contains_shadow_lab_and_allocator():
    from autotrader.api.dashboard_html import dashboard_html
    html = dashboard_html()
    assert "Shadow Alpha Lab" in html
    assert "Strategy Allocator v2" in html
    assert "/api/shadow/strategies" in html
    assert "/api/allocator/v2" in html
    assert "NO LIVE ORDERS" in html
