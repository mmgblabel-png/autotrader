from pathlib import Path

from autotrader.core.adaptive_learning import AdaptiveLearning
from autotrader.core.shadow_strategy_engine import ShadowStats, ShadowStrategyEngine
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
        "strategy_version": "v2",
        "symbol": "ETH-EUR",
        "shadow_order_eur": 6.0,
        "lookback": 12,
        "entry_z": 1.0,
        "entry_rebound_pct": 0.01,
        "max_downtrend_pct": 100.0,
        "exit_z": -0.1,
        "min_exit_net_pct": 0.75,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 2.0,
    }
    for price in [100] * 10 + [90, 91]:
        engine.update("mean_reversion", price, cfg)
    status = engine.status({"mean_reversion": cfg})
    assert status["live_orders_sent"] is False
    assert status["strategies"][0]["position_open"] is True
    assert status["strategies"][0]["strategy_version"] == "v2"

    engine.update("mean_reversion", 100, cfg)
    row = engine.status({"mean_reversion": cfg})["strategies"][0]
    assert row["completed_trades"] == 1
    assert row["realized_net_pnl_eur"] > 0
    assert row["promotable"] is False
    assert 0 <= row["score"] <= 100
    assert row["review_status"] == "KEEP"
    assert "position_qty" in row
    assert "entry_price" in row

    restored = ShadowStrategyEngine({"path": str(path)})
    restored_row = restored.status({"mean_reversion": cfg})["strategies"][0]
    assert restored_row["completed_trades"] == 1
    assert restored_row["realized_net_pnl_eur"] > 0


def test_mean_reversion_v2_waits_for_net_profit_hurdle(tmp_path: Path):
    engine = ShadowStrategyEngine({
        "path": str(tmp_path / "shadow.json"),
        "fee_pct_each_leg": 0.25,
        "slippage_pct_each_leg": 0.05,
    })
    state = ShadowStats(
        prices=[99.0] * 11 + [100.5],
        position_qty=0.06,
        entry_price=100.0,
        entry_cost_eur=6.0,
        strategy_version="v2",
    )
    cfg = {
        "lookback": 12,
        "exit_z": -0.1,
        "min_exit_net_pct": 0.75,
        "take_profit_pct": 1.35,
        "stop_loss_pct": 1.2,
    }
    engine._mean_reversion(state, 100.5, cfg)
    assert state.position_qty > 0
    assert state.completed_trades == 0


def test_shadow_outcome_updates_adaptive_learning(tmp_path: Path):
    learner = AdaptiveLearning({
        "path": str(tmp_path / "learning.json"),
        "min_samples": 6,
        "lookback": 12,
    })
    engine = ShadowStrategyEngine(
        {"path": str(tmp_path / "shadow.json")},
        learner=learner,
    )
    cfg = {
        "kind": "mean_reversion",
        "strategy_version": "v2",
        "symbol": "ETH-EUR",
        "shadow_order_eur": 6.0,
        "lookback": 12,
        "entry_z": 1.0,
        "entry_rebound_pct": 0.01,
        "max_downtrend_pct": 100.0,
        "exit_z": -0.1,
        "min_exit_net_pct": 0.75,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 2.0,
    }
    for price in [100] * 10 + [90, 91, 100]:
        engine.update("mean_reversion", price, cfg)
    snap = learner.snapshot()
    learned = snap["strategies"]["MeanReversionShadow"]
    assert learned["completed_exits"] == 1
    assert snap["policy"]["tunables"]["MeanReversionShadow"]["parameter"] == "entry_z"


def test_strategy_version_resets_shadow_scorekeeping(tmp_path: Path):
    path = tmp_path / "shadow.json"
    old = ShadowStats(
        prices=[100.0] * 20,
        completed_trades=20,
        losses=20,
        realized_net_pnl_eur=-1.0,
        strategy_version="v1",
    )
    engine = ShadowStrategyEngine({"path": str(path)})
    engine._states["mean_reversion"] = old
    cfg = {
        "kind": "mean_reversion",
        "strategy_version": "v2",
        "lookback": 40,
        "entry_z": 2.0,
    }
    engine.update("mean_reversion", 100.0, cfg)
    state = engine._states["mean_reversion"]
    assert state.strategy_version == "v2"
    assert state.completed_trades == 0
    assert state.realized_net_pnl_eur == 0.0
    assert state.prices


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
    assert "Shadow Fast Lane" in html
    assert "Shadow Strategy Scorecard" in html
    assert "<th>W/L</th>" in html
    assert "<th>Score</th>" in html
    assert "<th>Status</th>" in html
    assert "PROMOTE" in html
    assert "DROP" in html
    assert "Strategy Allocator v2" in html
    assert "/api/dashboard/snapshot" in html
    assert "Promise.allSettled" not in html
    assert "NO LIVE ORDERS" in html
    assert "Order Control Center" in html
    assert "section('orders')" in html
    assert 'id="orderactivity"' in html
    assert "setInterval(()=>{if(!$('app').classList.contains('hidden'))refresh()},15000)" in html
    assert "section('live_readiness')" in html
    assert "Profit Optimization v2" in html
    assert "section('execution_v2')" in html
    assert "section('opportunities')" in html
    assert "section('fee_efficiency')" in html
    assert 'id="execv2rows"' in html
    assert 'id="routerrows"' in html
    assert 'id="feerows"' in html
    assert "Gezamenlijk botdoel" in html
    assert "€25K TARGET" in html
    assert "section('portfolio_goal')" in html
    assert "section('binance_reference')" in html
    assert 'id="goalbar"' in html
    assert 'id="binanceprice"' in html
    assert "Autonomous Control Loop" in html
    assert "SET → EXECUTE → LEARN → REPEAT" in html
    assert "section('autonomy')" in html
    assert 'id="autonomyrows"' in html
    assert "Full Market Opportunity Router" in html
    assert 'id="routerconfigured"' in html
    assert 'id="routerscanned"' in html
    assert "section('risk_lab')" in html
    assert "Leverage + Capped Martingale Lab" in html
    assert 'id="risklabpnl"' in html
    assert "section('three_hour')" in html
    assert 'id="threehOrders"' in html
    assert 'id="threehOpportunities"' in html
    assert "Actieve bot-exposure" in html
    assert "Vrije exposure-headroom" in html
    assert "Entry-turnover vandaag" in html
    assert "60-market scanner" in html
    assert "LIVE MANAGER" in html
    assert "Fee & Margin Reality" in html
    assert "section('fees_live')" in html
    assert 'id="actualmakerfee"' in html
    assert 'id="feerealityrows"' in html


def test_shadow_trailing_peak_survives_fresh_runtime_config_and_restart(tmp_path: Path):
    path = tmp_path / "shadow.json"
    engine = ShadowStrategyEngine({
        "path": str(path),
        "fee_pct_each_leg": 0.0,
        "slippage_pct_each_leg": 0.0,
    })
    state = ShadowStats(
        prices=[100.0] * 20,
        position_qty=0.06,
        entry_price=100.0,
        entry_cost_eur=6.0,
        position_peak_price=100.0,
        strategy_version="v1",
    )
    engine._states["sniper_v2@TEST-EUR"] = state
    cfg = {
        "kind": "sniper_v2",
        "symbol": "TEST-EUR",
        "ema_fast": 3,
        "ema_slow": 6,
        "momentum_lookback": 2,
        "take_profit_pct": 10.0,
        "stop_loss_pct": 10.0,
        "trailing_exit_pct": 0.5,
        "min_exit_net_pct": 0.75,
    }

    engine.update("sniper_v2@TEST-EUR", 102.0, dict(cfg))
    assert engine._states["sniper_v2@TEST-EUR"].position_peak_price == 102.0
    engine.flush()

    restored = ShadowStrategyEngine({
        "path": str(path),
        "fee_pct_each_leg": 0.0,
        "slippage_pct_each_leg": 0.0,
    })
    restored.update("sniper_v2@TEST-EUR", 101.0, dict(cfg))
    restored_state = restored._states["sniper_v2@TEST-EUR"]
    assert restored_state.completed_trades == 1
    assert restored_state.position_qty == 0.0
    assert restored_state.last_signal == "trailing_profit_exit"


def test_dynamic_shadow_candidate_maps_to_family_adaptive_learner(tmp_path: Path):
    learner = AdaptiveLearning({
        "path": str(tmp_path / "learning.json"),
        "min_samples": 6,
        "lookback": 12,
    })
    engine = ShadowStrategyEngine({"path": str(tmp_path / "shadow.json")}, learner=learner)
    assert engine._learner_name("mean_reversion@ADA-EUR") == "MeanReversionShadow"
    assert engine._learner_name("volatility_breakout@ETH-EUR") == "VolatilityBreakoutShadow"
    assert engine._learner_name("sniper_v2@XRP-EUR") == "SniperV2Shadow"


def test_shadow_promotion_requires_profit_factor_and_cost_stress(tmp_path: Path):
    engine = ShadowStrategyEngine({
        "path": str(tmp_path / "shadow.json"),
        "fee_pct_each_leg": 0.25,
        "slippage_pct_each_leg": 0.05,
        "promotion_min_completed_trades": 4,
        "promotion_min_winrate_pct": 50.0,
        "promotion_min_net_pnl_eur": 0.10,
        "promotion_min_profit_factor": 1.10,
        "promotion_cost_stress_multiplier": 1.25,
        "promotion_max_drawdown_pct": 6.0,
    })
    cfg = {"kind": "mean_reversion", "shadow_order_eur": 6.0}
    engine._states["mean_reversion"] = ShadowStats(
        completed_trades=4,
        wins=3,
        losses=1,
        realized_net_pnl_eur=0.50,
        outcomes=[0.20, 0.20, 0.20, -0.10],
    )
    row = engine.status({"mean_reversion": cfg})["strategies"][0]
    assert row["profit_factor"] >= 1.10
    assert row["stressed_net_pnl_eur"] > 0
    assert row["promotion_ready"] is True

    engine._states["mean_reversion"].outcomes = [0.10, 0.10, 0.10, -0.30]
    engine._states["mean_reversion"].realized_net_pnl_eur = 0.20
    row = engine.status({"mean_reversion": cfg})["strategies"][0]
    assert row["profit_factor"] < 1.10
    assert row["promotion_ready"] is False
