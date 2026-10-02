"""Autonomous fund hard-policy, scheduler and spot-protection tests."""

from __future__ import annotations

import time
from types import SimpleNamespace

from autotrader.core.order_manager import OrderManager, OrderSide, OrderType
from autotrader.core.profit_engine import ProfitEngine
from autotrader.core.risk_manager import RiskManager
from autotrader.core.spot_protection import (
    evaluate_spot_protection,
    mark_protection_order_pending,
    mark_protection_sell_fill,
)
from autotrader.fund.automation import AutonomousFundScheduler
from autotrader.fund.engine import HedgeFundEngine
from autotrader.fund.models import FundMandate
from autotrader.strategies.grid_runner import GridRunner


def _fund_config(tmp_path):
    return {
        "enabled": True,
        "fund_id": "autonomous-policy-test",
        "base_currency": "EUR",
        "initial_nav_eur": 50.0,
        "target_nav_eur": 50000.0,
        "protected_capital_floor_eur": 25000.0,
        "ledger_path": str(tmp_path / "fund.sqlite3"),
        "max_portfolio_drawdown_pct": 10.0,
        "max_daily_loss_pct": 3.0,
        "max_single_trade_pct": 20.0,
        "max_gross_exposure_pct": 80.0,
        "max_strategy_exposure_pct": 40.0,
        "max_asset_exposure_pct": 20.0,
        "min_cash_reserve_pct": 20.0,
    }


def test_hard_fund_policy_can_only_be_tightened_not_loosened():
    mandate = FundMandate.from_config({
        "max_portfolio_drawdown_pct": 99,
        "max_daily_loss_pct": 99,
        "max_single_trade_pct": 99,
        "max_gross_exposure_pct": 99,
        "max_strategy_exposure_pct": 99,
        "max_asset_exposure_pct": 99,
        "min_cash_reserve_pct": 0,
    })
    assert mandate.max_portfolio_drawdown_pct == 10.0
    assert mandate.max_daily_loss_pct == 3.0
    assert mandate.max_single_trade_pct == 20.0
    assert mandate.max_gross_exposure_pct == 80.0
    assert mandate.max_asset_exposure_pct == 20.0
    assert mandate.min_cash_reserve_pct == 20.0

    tighter = FundMandate.from_config({
        "max_portfolio_drawdown_pct": 6,
        "max_daily_loss_pct": 1,
        "max_single_trade_pct": 5,
        "max_gross_exposure_pct": 50,
        "max_asset_exposure_pct": 8,
        "min_cash_reserve_pct": 40,
    })
    assert tighter.max_portfolio_drawdown_pct == 6.0
    assert tighter.max_daily_loss_pct == 1.0
    assert tighter.max_single_trade_pct == 5.0
    assert tighter.max_gross_exposure_pct == 50.0
    assert tighter.max_asset_exposure_pct == 8.0
    assert tighter.min_cash_reserve_pct == 40.0


def test_spot_protection_stop_trailing_and_partial_profit():
    cfg = {
        "protection_stop_loss_pct": 2.0,
        "protection_trailing_activation_pct": 0.90,
        "protection_trailing_drawdown_pct": 1.25,
        "protection_partial_profit_trigger_pct": 0.75,
        "protection_partial_profit_fraction": 0.50,
    }

    stop = evaluate_spot_protection(
        cfg, entry_price=100.0, current_price=97.9, quantity=1.0
    )
    assert stop.action == "FULL_EXIT"
    assert stop.reason == "stop_loss"

    cfg = dict(cfg)
    evaluate_spot_protection(cfg, entry_price=100.0, current_price=103.0, quantity=1.0)
    trailing = evaluate_spot_protection(
        cfg, entry_price=100.0, current_price=101.6, quantity=1.0
    )
    assert trailing.action == "FULL_EXIT"
    assert trailing.reason == "trailing_protection"

    cfg = dict(cfg)
    partial = evaluate_spot_protection(
        cfg, entry_price=100.0, current_price=100.8, quantity=1.0
    )
    assert partial.action == "PARTIAL_EXIT"
    assert partial.fraction == 0.5
    mark_protection_order_pending(cfg, partial)
    mark_protection_sell_fill(cfg, remaining_quantity=0.5)
    assert cfg["_protection_partial_taken"] is True
    second = evaluate_spot_protection(
        cfg, entry_price=100.0, current_price=100.9, quantity=0.5
    )
    assert second.action == "HOLD"


def test_grid_runner_creates_risk_reducing_market_stop_exit():
    om = OrderManager()
    rm = RiskManager()
    pe = ProfitEngine()
    cfg = {
        "enabled": True,
        "symbol": "SOL-EUR",
        "exchange": "bitvavo",
        "order_value_eur": 8.0,
        "entry_offset_pct": 0.60,
        "exit_markup_pct": 0.80,
        "_current_price": 97.0,
        "_live_balance_snapshot_ready": True,
        "_exchange_open_orders_snapshot_ready": True,
        "_exchange_open_order_count": 0,
        "_available_base": 0.10,
        "_available_quote": 0.0,
        "_bot_base_inventory": 0.10,
        "_bot_average_entry_price": 100.0,
        "protection_stop_loss_pct": 2.0,
        "protection_trailing_activation_pct": 0.90,
        "protection_trailing_drawdown_pct": 1.25,
        "protection_partial_profit_trigger_pct": 0.75,
        "protection_partial_profit_fraction": 0.50,
    }
    strategy = GridRunner(om, rm, pe, cfg)
    strategy.start()
    strategy.tick()
    orders = om.open_orders("GridRunner")
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].order_type is OrderType.MARKET
    assert cfg["_protection_pending_action"] == "stop_loss"


class _ResearchLab:
    def __init__(self):
        self.calls = []

    def full_report(self, market, **kwargs):
        self.calls.append((market, kwargs))
        return {
            "market": market,
            "strategy": kwargs["strategy"],
            "interval": kwargs["interval"],
            "backtest": {"metrics": {"sharpe_ratio": 1.1}},
            "walk_forward": {"windows": 3},
            "stress": {"scenarios": []},
            "monte_carlo": {
                "simulations": kwargs["simulations"],
                "risk_of_ruin_pct": 2.0,
                "probability_of_profit_pct": 60.0,
                "terminal_capital": {"p50": 110.0},
            },
        }


def test_autonomous_scheduler_runs_10k_mc_and_reports_idempotently(tmp_path):
    fund = HedgeFundEngine(_fund_config(tmp_path))
    fund.refresh_nav(50.0, source="test", verified=True)
    lab = _ResearchLab()
    agent = SimpleNamespace(fund=fund, research_lab=lab)
    scheduler = AutonomousFundScheduler({
        "enabled": True,
        "research_interval_seconds": 3600,
        "research_top_markets": 1,
        "monte_carlo_simulations": 10000,
        "report_daily": True,
        "report_weekly": True,
        "report_monthly": True,
    })
    router = {
        "rankings": {
            "grid": [
                {
                    "market": "BTC-EUR",
                    "score": 91.0,
                    "eligible": True,
                }
            ]
        }
    }
    now = time.time()
    first = scheduler.run_once(agent=agent, router_payload=router, now=now)
    assert first["research_result"]["ran"] is True
    assert lab.calls[0][1]["simulations"] == 10000
    assert len(first["last_report_events"]) == 3
    assert first["live_orders_sent"] is False

    second = scheduler.run_once(agent=agent, router_payload=router, now=now + 10)
    assert second["research_result"]["ran"] is False
    assert second["research_result"]["reason"] == "slot_already_complete"
    assert len(lab.calls) == 1

    events = fund.ledger.tail(100)
    assert sum(row["event_type"] == "fund_report_daily" for row in events) == 1
    assert sum(row["event_type"] == "fund_report_weekly" for row in events) == 1
    assert sum(row["event_type"] == "fund_report_monthly" for row in events) == 1
    assert sum(row["event_type"] == "autonomous_research_report" for row in events) == 1


def test_scheduler_does_not_freeze_empty_research_slot(tmp_path):
    fund = HedgeFundEngine(_fund_config(tmp_path))
    fund.refresh_nav(50.0, source="test", verified=True)
    lab = _ResearchLab()
    agent = SimpleNamespace(fund=fund, research_lab=lab)
    scheduler = AutonomousFundScheduler({"research_interval_seconds": 3600})
    now = time.time()

    empty = scheduler.run_once(agent=agent, router_payload={"rankings": {}}, now=now)
    assert empty["research_result"]["reason"] == "no_eligible_markets_yet"

    router = {
        "rankings": {
            "grid": [{"market": "ETH-EUR", "score": 90, "eligible": True}]
        }
    }
    retried = scheduler.run_once(agent=agent, router_payload=router, now=now + 10)
    assert retried["research_result"]["ran"] is True
    assert lab.calls
