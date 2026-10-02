"""Fund Core v1 tests: mandate, signal blending, ledger integrity and hard risk gates."""

from __future__ import annotations

import sqlite3
import time

from autotrader.core.risk_manager import RiskManager
from autotrader.fund.engine import HedgeFundEngine
from autotrader.fund.ledger import FundLedger
from autotrader.fund.models import AgentSignal, FundMandate
from autotrader.fund.portfolio import SignalBlender
from autotrader.fund.risk import FundRiskEngine


def _fund_config(tmp_path, **overrides):
    config = {
        "enabled": True,
        "fund_id": "test-fund",
        "base_currency": "EUR",
        "initial_nav_eur": 100.0,
        "ledger_path": str(tmp_path / "fund.sqlite3"),
        "max_portfolio_drawdown_pct": 8.0,
        "max_daily_loss_pct": 2.0,
        "max_single_trade_pct": 10.0,
        "max_gross_exposure_pct": 80.0,
        "max_strategy_exposure_pct": 40.0,
        "max_asset_exposure_pct": 35.0,
        "min_cash_reserve_pct": 20.0,
        "min_signal_confidence": 0.60,
        "signal_half_life_seconds": 600.0,
    }
    config.update(overrides)
    return config


def test_mandate_rejects_gross_exposure_that_consumes_cash_reserve():
    try:
        FundMandate.from_config(
            {
                "initial_nav_eur": 100,
                "max_gross_exposure_pct": 95,
                "min_cash_reserve_pct": 10,
            }
        )
    except ValueError as exc:
        assert "cash" in str(exc).lower() or "capital" in str(exc).lower()
    else:
        raise AssertionError("invalid mandate was accepted")


def test_signal_blender_filters_low_confidence_and_blends_recency():
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 100,
            "max_gross_exposure_pct": 80,
            "min_cash_reserve_pct": 20,
            "min_signal_confidence": 0.60,
            "signal_half_life_seconds": 600,
        }
    )
    now = time.time()
    blender = SignalBlender(mandate, {"trend": 1.0, "sentiment": 0.5})
    rows = blender.blend(
        [
            AgentSignal(
                agent="trend",
                strategy="GridRunner",
                symbol="ETH-EUR",
                direction=0.8,
                confidence=0.9,
                score=82,
                horizon_seconds=3600,
                timestamp=now,
            ),
            AgentSignal(
                agent="sentiment",
                strategy="GridRunner",
                symbol="ETH-EUR",
                direction=-0.2,
                confidence=0.7,
                score=60,
                horizon_seconds=3600,
                timestamp=now,
            ),
            AgentSignal(
                agent="ignored",
                strategy="GridRunner",
                symbol="ETH-EUR",
                direction=1.0,
                confidence=0.2,
                score=99,
                horizon_seconds=3600,
                timestamp=now,
            ),
        ],
        now=now,
    )
    assert len(rows) == 1
    assert rows[0].source_count == 2
    assert 0.0 < rows[0].direction < 0.8
    assert 0.60 <= rows[0].confidence <= 0.90


def test_hash_chained_ledger_is_idempotent_and_detects_tampering(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = FundLedger(str(path))
    first = ledger.append("fill", {"amount": 5}, event_id="fill:1")
    duplicate = ledger.append("fill", {"amount": 999}, event_id="fill:1")
    ledger.append("nav_snapshot", {"nav_eur": 101.0}, event_id="nav:1")

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert ledger.verify()["valid"] is True

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE fund_events SET payload_json = ? WHERE event_id = ?",
            ('{"nav_eur":999}', "nav:1"),
        )
        conn.commit()

    verified = ledger.verify()
    assert verified["valid"] is False
    assert verified["reason"] == "event hash mismatch"


def test_fund_risk_blocks_single_trade_daily_loss_and_drawdown():
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 100,
            "max_portfolio_drawdown_pct": 8,
            "max_daily_loss_pct": 2,
            "max_single_trade_pct": 10,
            "max_gross_exposure_pct": 80,
            "max_strategy_exposure_pct": 40,
            "max_asset_exposure_pct": 35,
            "min_cash_reserve_pct": 20,
        }
    )
    risk = FundRiskEngine(mandate)

    assert risk.pretrade_check(strategy="A", notional_eur=10).accepted is True
    assert risk.pretrade_check(strategy="A", notional_eur=10.01).accepted is False

    risk.record_realized_pnl(-2.0)
    decision = risk.pretrade_check(strategy="A", notional_eur=1)
    assert decision.accepted is False
    assert "daily" in decision.reason.lower()

    risk = FundRiskEngine(mandate)
    risk.record_nav(91.9)
    decision = risk.pretrade_check(strategy="A", notional_eur=1)
    assert decision.accepted is False
    assert "drawdown" in decision.reason.lower()


def test_fill_exposure_is_rebuilt_and_reduced_for_spot_positions():
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 100,
            "max_gross_exposure_pct": 80,
            "min_cash_reserve_pct": 20,
        }
    )
    risk = FundRiskEngine(mandate)
    risk.record_fill(strategy="GridRunner", symbol="ETH-EUR", side="BUY", notional_eur=20)
    risk.record_fill(strategy="GridRunner", symbol="ETH-EUR", side="SELL", notional_eur=7)

    status = risk.status()
    assert status["gross_exposure_eur"] == 13.0
    assert status["strategy_exposure_eur"]["GridRunner"] == 13.0
    assert status["asset_exposure_eur"]["ETH-EUR"] == 13.0


def test_risk_manager_delegates_to_fund_gate(tmp_path):
    fund = HedgeFundEngine(_fund_config(tmp_path))
    manager = RiskManager()
    manager.set_fund_engine(fund)

    assert manager.check_order("GridRunner", 10.0) is True
    assert manager.check_order("GridRunner", 11.0) is False

    manager.record_pnl_delta("GridRunner", -2.0)
    assert manager.check_order("GridRunner", 1.0) is False


def test_fund_fill_recording_is_idempotent(tmp_path):
    fund = HedgeFundEngine(_fund_config(tmp_path))
    kwargs = {
        "strategy": "GridRunner",
        "symbol": "ETH-EUR",
        "side": "BUY",
        "notional_eur": 8.0,
        "realized_net_pnl_delta_eur": -0.02,
        "fill_id": "order-1:fill-1",
    }
    fund.record_fill(**kwargs)
    fund.record_fill(**kwargs)

    status = fund.status()
    assert status["risk"]["gross_exposure_eur"] == 8.0
    assert status["ledger"]["valid"] is True
