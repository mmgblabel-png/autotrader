from __future__ import annotations

import time
from pathlib import Path

from autotrader.core.profit_optimization import (
    ExecutionV2Advisor,
    OpportunityRouter,
    fee_efficiency_rows,
)
from autotrader.core.shadow_strategy_engine import ShadowStrategyEngine
from autotrader.core.strategy_allocator_v2 import StrategyAllocatorV2


class FakeBookAdapter:
    def __init__(self):
        self.books = {
            "BTC-EUR": {"bid": 100.0, "ask": 100.1, "bid_size": 1.0, "ask_size": 1.0},
            "ETH-EUR": {"bid": 50.0, "ask": 50.02, "bid_size": 3.0, "ask_size": 3.0},
            "SOL-EUR": {"bid": 20.0, "ask": 20.03, "bid_size": 10.0, "ask_size": 10.0},
        }

    def ticker_book(self, market: str):
        row = self.books[market]
        return {
            "market": market,
            "bid": row["bid"],
            "ask": row["ask"],
            "bid_size": row["bid_size"],
            "ask_size": row["ask_size"],
        }


def test_opportunity_router_is_read_only_and_ranks_markets():
    router = OpportunityRouter(
        FakeBookAdapter(),
        {
            "markets": ["BTC-EUR", "ETH-EUR", "SOL-EUR"],
            "min_top_depth_eur": 25,
            "max_spread_bps": 40,
        },
    )
    for _ in range(8):
        router.refresh()
    payload = router.rankings()
    assert payload["mode"] == "read_only_shadow"
    assert payload["live_orders_sent"] is False
    assert payload["markets_scanned"] == 3
    assert payload["rankings"]["market_maker"][0]["eligible"] is True


def test_execution_v2_recommends_only_safe_advisory_reprice():
    advisor = ExecutionV2Advisor({
        "enabled": True,
        "apply_live": False,
        "stale_after_seconds": 30,
        "min_reprice_move_bps": 4,
    })
    activity = [{
        "strategy": "MarketMaker",
        "market": "BTC-EUR",
        "side": "buy",
        "price": 99.0,
        "status": "new",
        "created_at": time.time() - 120,
    }]
    result = advisor.evaluate(
        activity,
        {"BTC-EUR": {"bid": 100.0, "ask": 100.1}},
        {"MarketMaker": 0.0},
        {"MarketMaker": 0.80},
        required_entry_edge_pct=0.75,
    )
    assert result["mode"] == "advisory"
    assert result["apply_live"] is False
    assert result["live_orders_changed"] is False
    assert result["orders"][0]["recommend_reprice"] is True

    blocked = advisor.evaluate(
        activity,
        {"BTC-EUR": {"bid": 100.0, "ask": 100.1}},
        {"MarketMaker": 0.0},
        {"MarketMaker": 0.60},
        required_entry_edge_pct=0.75,
    )
    assert blocked["orders"][0]["recommend_reprice"] is False
    assert blocked["orders"][0]["reason"] == "profit_guard_blocks_reprice"


def test_fee_efficiency_flags_fee_heavy_strategy():
    payload = fee_efficiency_rows([{
        "strategy": "MarketMaker",
        "market": "BTC-EUR",
        "realized_net_pnl_eur": 0.05,
        "fees_quote_equivalent_eur": 0.06,
        "profitable_exits": 2,
        "losing_exits": 0,
    }])
    row = payload["rows"][0]
    assert row["completed_exits"] == 2
    assert row["fee_drag_pct"] > 50
    assert row["state"] == "fee_heavy"
    assert payload["live_changes"] is False


def test_allocator_v2_penalizes_fee_drag_and_keeps_shadow_out_of_live_budget():
    allocator = StrategyAllocatorV2({
        "apply_live": False,
        "min_samples": 2,
        "max_shift_pct": 25,
        "min_allocation_eur": 5,
        "fee_drag_penalty_pct": 50,
        "idle_budget_reuse_pct": 50,
    })
    cfg = {
        "market_maker": {
            "enabled": True,
            "live_capable": True,
            "allocation_eur": 15,
        },
        "grid": {
            "enabled": True,
            "live_capable": True,
            "allocation_eur": 15,
        },
        "mean_reversion": {
            "enabled": True,
            "shadow_order_eur": 6,
        },
    }
    stats = {
        "MarketMaker": {"net_pnl": 1.0, "wins": 4, "losses": 1, "winrate_pct": 80},
        "GridRunner": {"net_pnl": 1.0, "wins": 4, "losses": 1, "winrate_pct": 80},
    }
    fees = [
        {"strategy": "MarketMaker", "fee_drag_pct": 70.0},
        {"strategy": "GridRunner", "fee_drag_pct": 10.0},
    ]
    shadow = [{
        "name": "mean_reversion",
        "completed_trades": 10,
        "realized_net_pnl_eur": 1.0,
        "winrate_pct": 70.0,
        "max_drawdown_pct": 2.0,
    }]
    result = allocator.recommendations(cfg, stats, shadow, 50.0, fee_rows=fees)
    rows = {r["key"]: r for r in result["recommendations"]}
    assert result["mode"] == "advisory"
    assert result["apply_live"] is False
    assert rows["grid"]["recommended_allocation_eur"] >= rows["market_maker"]["recommended_allocation_eur"]
    assert rows["mean_reversion"]["mode"] == "shadow"
    live_total = sum(
        r["recommended_allocation_eur"]
        for r in result["recommendations"]
        if r["mode"] == "live"
    )
    assert live_total <= result["target_deployable_budget_eur"] + 0.01


def test_sniper_v2_shadow_completes_profitable_round_trip(tmp_path: Path):
    engine = ShadowStrategyEngine({
        "path": str(tmp_path / "shadow.json"),
        "fee_pct_each_leg": 0.25,
        "slippage_pct_each_leg": 0.05,
    })
    cfg = {
        "kind": "sniper_v2",
        "strategy_version": "v1",
        "symbol": "XRP-EUR",
        "shadow_order_eur": 6.0,
        "ema_fast": 3,
        "ema_slow": 5,
        "momentum_lookback": 2,
        "momentum_pct": 0.15,
        "max_entry_spike_pct": 1.0,
        "take_profit_pct": 0.9,
        "stop_loss_pct": 0.5,
        "trailing_exit_pct": 0.3,
        "min_exit_net_pct": 0.75,
    }
    for p in [100.0, 100.05, 100.10, 100.15, 100.20, 100.45]:
        engine.update("sniper_v2", p, cfg)
    row = engine.status({"sniper_v2": cfg})["strategies"][0]
    assert row["position_open"] is True

    engine.update("sniper_v2", 101.60, cfg)
    row = engine.status({"sniper_v2": cfg})["strategies"][0]
    assert row["completed_trades"] == 1
    assert row["realized_net_pnl_eur"] > 0
    assert row["live_capable"] is False
