"""Fund growth ladder, dynamic allocation and track-record tests."""

from __future__ import annotations

from decimal import Decimal

from autotrader.core.strategy_allocator import StrategyAllocator
from autotrader.fund.engine import HedgeFundEngine
from autotrader.fund.growth import GrowthController
from autotrader.fund.ledger import FundLedger


def _growth_config() -> dict:
    return {
        "enabled": True,
        "auto_scale_live_budget": True,
        "minimum_live_order_eur": 5.0,
        "track_record": {
            "min_elapsed_days": 365,
            "min_observation_days": 250,
            "min_completed_exits": 200,
            "min_net_realized_pnl_eur": 0.01,
            "min_profit_factor": 1.10,
            "min_sharpe": 0.50,
            "max_drawdown_pct": 8.0,
        },
        "governance": {
            "investor_capital_enabled": False,
            "legal_structure_confirmed": False,
            "compliance_review_confirmed": False,
            "accounting_review_confirmed": False,
            "external_audit_confirmed": False,
        },
    }


def test_growth_stages_scale_budget_and_reduce_order_pct_with_capital():
    controller = GrowthController(_growth_config())

    seed = controller.status(
        nav_eur=50.0,
        risk_status={"drawdown_pct": 0, "gross_exposure_eur": 0, "nav_verified": True},
        track_metrics={},
        ledger_valid=True,
    )
    assert seed["active_stage"] == "seed"
    assert seed["policy"]["effective_live_budget_eur"] == 20.0
    assert seed["policy"]["effective_max_order_eur"] == 6.0
    assert seed["policy"]["max_open_orders"] == 2

    emerging = controller.status(
        nav_eur=500.0,
        risk_status={"drawdown_pct": 0, "gross_exposure_eur": 0, "nav_verified": True},
        track_metrics={},
        ledger_valid=True,
    )
    assert emerging["active_stage"] == "emerging"
    assert emerging["policy"]["effective_live_budget_eur"] == 250.0
    assert emerging["policy"]["effective_max_order_eur"] == 20.0

    scaled = controller.status(
        nav_eur=5000.0,
        risk_status={"drawdown_pct": 0, "gross_exposure_eur": 0, "nav_verified": True},
        track_metrics={},
        ledger_valid=True,
    )
    assert scaled["active_stage"] == "scaled"
    assert scaled["policy"]["effective_live_budget_eur"] == 3000.0
    assert scaled["policy"]["effective_max_order_eur"] == 100.0

    institutional = controller.status(
        nav_eur=50000.0,
        risk_status={"drawdown_pct": 0, "gross_exposure_eur": 0, "nav_verified": True},
        track_metrics={},
        ledger_valid=True,
    )
    assert institutional["active_stage"] == "institutional_personal"
    assert institutional["policy"]["effective_live_budget_eur"] == 32500.0
    assert institutional["policy"]["effective_max_order_eur"] == 250.0


def test_seed_growth_gate_caps_total_risk_and_single_order():
    controller = GrowthController(_growth_config())
    risk = {
        "drawdown_pct": 0.0,
        "daily_loss_pct": 0.0,
        "gross_exposure_eur": 0.0,
    }
    accepted, _ = controller.check_order(
        nav_eur=50.0,
        risk_status=risk,
        notional_eur=6.0,
        risk_reducing=False,
    )
    assert accepted is True

    rejected, reason = controller.check_order(
        nav_eur=50.0,
        risk_status=risk,
        notional_eur=6.01,
        risk_reducing=False,
    )
    assert rejected is False
    assert "per-order" in reason

    risk["gross_exposure_eur"] = 18.0
    rejected, reason = controller.check_order(
        nav_eur=50.0,
        risk_status=risk,
        notional_eur=5.0,
        risk_reducing=False,
    )
    assert rejected is False
    assert "live budget" in reason


def test_growth_allocator_scales_live_strategies_by_existing_weights():
    allocator = StrategyAllocator(
        {
            "portfolio": {
                "global_live_budget_eur": 50,
                "max_total_open_orders": 4,
            },
            "strategies": {
                "market_maker": {
                    "symbol": "BTC-EUR",
                    "live_capable": True,
                    "allocation_eur": 20,
                    "max_order_eur": 12,
                    "max_open_orders": 1,
                },
                "grid": {
                    "symbol": "SOL-EUR",
                    "live_capable": True,
                    "allocation_eur": 15,
                    "max_order_eur": 9,
                    "max_open_orders": 1,
                },
                "grid_eth": {
                    "symbol": "ETH-EUR",
                    "live_capable": True,
                    "allocation_eur": 15,
                    "max_order_eur": 9,
                    "max_open_orders": 1,
                },
                "sniper": {
                    "symbol": "XRP-EUR",
                    "live_capable": False,
                    "allocation_eur": 0,
                    "max_order_eur": 10,
                    "max_open_orders": 1,
                },
            },
        }
    )

    status = allocator.apply_growth_policy(
        {
            "effective_live_budget_eur": 20,
            "effective_max_order_eur": 6,
            "max_open_orders": 2,
        }
    )
    assert allocator.global_budget_eur == Decimal("20")
    assert allocator.max_total_open_orders == 2
    assert round(allocator.allocation_for("MarketMaker").allocation_eur, 6) == Decimal("8.000000")
    assert round(allocator.allocation_for("GridRunner").allocation_eur, 6) == Decimal("6.000000")
    assert round(allocator.allocation_for("GridRunnerETH").allocation_eur, 6) == Decimal("6.000000")
    assert allocator.allocation_for("MarketMaker").max_order_eur == Decimal("6")
    assert status["effective_global_budget_eur"] == 20.0


def test_track_record_excludes_paper_and_counts_only_verified_live(tmp_path):
    ledger = FundLedger(str(tmp_path / "fund.sqlite3"))
    base = 1_700_000_000.0

    ledger.append(
        "nav_checkpoint",
        {
            "nav_eur": 100.0,
            "verified": True,
            "execution_mode": "paper",
        },
        event_id="paper-nav",
        timestamp=base,
    )
    ledger.append(
        "fill",
        {
            "side": "SELL",
            "realized_net_pnl_delta_eur": 50.0,
            "execution_mode": "paper",
        },
        event_id="paper-fill",
        timestamp=base + 10,
    )

    ledger.append(
        "nav_checkpoint",
        {
            "nav_eur": 100.0,
            "verified": True,
            "execution_mode": "live",
        },
        event_id="live-nav-1",
        timestamp=base + 86400,
    )
    ledger.append(
        "nav_checkpoint",
        {
            "nav_eur": 102.0,
            "verified": True,
            "execution_mode": "live",
        },
        event_id="live-nav-2",
        timestamp=base + 2 * 86400,
    )
    ledger.append(
        "fill",
        {
            "side": "SELL",
            "realized_net_pnl_delta_eur": 2.0,
            "execution_mode": "live",
        },
        event_id="live-fill",
        timestamp=base + 2 * 86400 + 10,
    )

    metrics = ledger.track_record_metrics()
    assert metrics["observation_days"] == 2
    assert metrics["live_fill_count"] == 1
    assert metrics["completed_exits"] == 1
    assert metrics["net_realized_pnl_eur"] == 2.0


def test_verified_track_record_does_not_unlock_external_capital_without_governance():
    controller = GrowthController(_growth_config())
    metrics = {
        "elapsed_days": 365,
        "observation_days": 250,
        "completed_exits": 250,
        "net_realized_pnl_eur": 500.0,
        "profit_factor": 1.5,
        "sharpe_ratio": 1.0,
        "max_drawdown_pct": 5.0,
    }
    status = controller.status(
        nav_eur=50000.0,
        risk_status={"drawdown_pct": 2.0, "gross_exposure_eur": 10000, "nav_verified": True},
        track_metrics=metrics,
        ledger_valid=True,
    )
    assert status["track_record"]["verified"] is True
    assert status["governance"]["ready"] is False
    assert status["governance"]["investor_outreach_ready"] is False
    assert status["governance"]["external_capital_acceptance_allowed"] is False


def test_fund_pretrade_uses_growth_stage_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    fund = HedgeFundEngine(
        {
            "enabled": True,
            "initial_nav_eur": 50.0,
            "ledger_path": str(tmp_path / "fund.sqlite3"),
            "max_portfolio_drawdown_pct": 8.0,
            "max_daily_loss_pct": 2.0,
            "max_single_trade_pct": 20.0,
            "max_gross_exposure_pct": 85.0,
            "max_strategy_exposure_pct": 40.0,
            "max_asset_exposure_pct": 35.0,
            "min_cash_reserve_pct": 15.0,
            "growth_plan": _growth_config(),
        }
    )
    fund.refresh_nav(50.0, source="bitvavo", verified=True)

    accepted = fund.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=6.0,
        require_verified_nav=True,
    )
    assert accepted.accepted is True

    blocked = fund.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=8.0,
        require_verified_nav=True,
    )
    assert blocked.accepted is False
    assert "growth-stage" in blocked.reason


def test_growth_stage_enforces_strategy_and_asset_exposure_caps():
    controller = GrowthController(_growth_config())
    risk = {
        "drawdown_pct": 0.0,
        "daily_loss_pct": 0.0,
        "gross_exposure_eur": 9.0,
        "strategy_exposure_eur": {"GridRunner": 9.0},
        "asset_exposure_eur": {"ETH-EUR": 9.0},
    }
    ok, reason = controller.check_order(
        nav_eur=50.0,
        risk_status=risk,
        notional_eur=2.0,
        risk_reducing=False,
        strategy="GridRunner",
        symbol="SOL-EUR",
    )
    assert ok is False
    assert "strategy exposure" in reason

    risk["strategy_exposure_eur"] = {"GridRunner": 0.0}
    risk["asset_exposure_eur"] = {"ETH-EUR": 9.0}
    ok, reason = controller.check_order(
        nav_eur=50.0,
        risk_status=risk,
        notional_eur=2.0,
        risk_reducing=False,
        strategy="GridRunner",
        symbol="ETH-EUR",
    )
    assert ok is False
    assert "asset exposure" in reason
