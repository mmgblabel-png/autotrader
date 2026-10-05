"""Fund Core v1 tests: mandate, signal blending, ledger integrity and hard risk gates."""

from __future__ import annotations

import sqlite3
import time

from autotrader.agent import AutoTrader
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
        "live_nav_max_age_seconds": 120.0,
    }
    config.update(overrides)
    return config


def test_mandate_clamps_loose_gross_exposure_and_cash_reserve():
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 100,
            "max_gross_exposure_pct": 95,
            "min_cash_reserve_pct": 10,
        }
    )
    assert mandate.max_gross_exposure_pct == 80.0
    assert mandate.min_cash_reserve_pct == 20.0


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


def test_capital_floor_latches_at_target_and_allows_only_risk_reduction(tmp_path):
    fund = HedgeFundEngine(
        _fund_config(
            tmp_path,
            initial_nav_eur=100.0,
            target_nav_eur=250.0,
            protected_capital_floor_eur=250.0,
            capital_floor_buffer_pct=2.0,
            max_single_trade_pct=100.0,
            max_gross_exposure_pct=80.0,
            min_cash_reserve_pct=20.0,
        )
    )

    fund.refresh_nav(249.99, source="test", verified=True)
    before = fund.status()["risk"]
    assert before["capital_floor_armed"] is False

    fund.refresh_nav(250.0, source="test", verified=True)
    status = fund.status()["risk"]
    assert status["capital_floor_armed"] is True
    assert status["protected_capital_floor_eur"] == 250.0
    assert status["protected_zone_eur"] == 255.0
    assert status["risk_capital_available_eur"] == 0.0

    blocked = fund.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=1.0,
    )
    assert blocked.accepted is False
    assert "protected capital floor" in blocked.reason.lower()

    exit_order = fund.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=1.0,
        risk_reducing=True,
    )
    assert exit_order.accepted is True


def test_capital_floor_limits_total_exposure_to_surplus_only():
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 100.0,
            "target_nav_eur": 250.0,
            "protected_capital_floor_eur": 250.0,
            "capital_floor_buffer_pct": 2.0,
            "max_single_trade_pct": 100.0,
            "max_gross_exposure_pct": 80.0,
            "max_strategy_exposure_pct": 80.0,
            "max_asset_exposure_pct": 80.0,
            "min_cash_reserve_pct": 20.0,
        }
    )
    risk = FundRiskEngine(mandate)
    risk.record_nav(250.0, source="test", verified=True)
    risk.record_nav(300.0, source="test", verified=True)

    assert risk.status()["risk_capital_available_eur"] == 45.0
    assert risk.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=40.0,
    ).accepted is True

    risk.record_fill(
        strategy="GridRunner",
        symbol="ETH-EUR",
        side="BUY",
        notional_eur=40.0,
    )
    second = risk.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=10.0,
    )
    assert second.accepted is False
    assert "total exposure" in second.reason.lower()


def test_capital_floor_latch_survives_engine_restart(tmp_path):
    config = _fund_config(
        tmp_path,
        initial_nav_eur=100.0,
        target_nav_eur=250.0,
        protected_capital_floor_eur=250.0,
        capital_floor_buffer_pct=2.0,
    )
    first = HedgeFundEngine(config)
    first.refresh_nav(250.0, source="test", verified=True)

    assert first.ledger.has_event_type("capital_floor_armed") is True
    assert first.status()["risk"]["capital_floor_armed"] is True

    restarted = HedgeFundEngine(config)
    restarted.refresh_nav(100.0, source="restart-test")
    status = restarted.status()["risk"]
    assert status["capital_floor_armed"] is True
    assert status["target_reached"] is True
    assert status["peak_nav_eur"] >= 250.0
    assert status["risk_capital_available_eur"] == 0.0
    assert restarted.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=1.0,
    ).accepted is False


def test_unverified_nav_cannot_arm_capital_floor(tmp_path):
    fund = HedgeFundEngine(
        _fund_config(
            tmp_path,
            initial_nav_eur=100.0,
            target_nav_eur=250.0,
            protected_capital_floor_eur=250.0,
        )
    )
    fund.refresh_nav(1000.0, source="untrusted-test", verified=False)
    status = fund.status()["risk"]
    assert status["capital_floor_armed"] is False
    assert status["peak_nav_eur"] == 100.0
    assert status["nav_verified"] is False


def test_live_entries_require_verified_fresh_nav_but_exits_remain_allowed(monkeypatch):
    mandate = FundMandate.from_config(
        {
            "initial_nav_eur": 100.0,
            "live_nav_max_age_seconds": 10.0,
            "max_single_trade_pct": 100.0,
            "max_gross_exposure_pct": 80.0,
            "max_strategy_exposure_pct": 80.0,
            "max_asset_exposure_pct": 80.0,
            "min_cash_reserve_pct": 20.0,
        }
    )
    risk = FundRiskEngine(mandate)

    missing = risk.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=1.0,
        require_verified_nav=True,
    )
    assert missing.accepted is False
    assert "not verified" in missing.reason.lower()

    exit_order = risk.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=1.0,
        risk_reducing=True,
        require_verified_nav=True,
    )
    assert exit_order.accepted is True

    risk.record_nav(100.0, source="bitvavo", verified=True)
    assert risk.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=1.0,
        require_verified_nav=True,
    ).accepted is True

    assert risk.state.nav_updated_at is not None
    risk.state.nav_updated_at -= 11.0
    stale = risk.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=1.0,
        require_verified_nav=True,
    )
    assert stale.accepted is False
    assert "stale" in stale.reason.lower()


def test_risk_manager_requires_verified_nav_in_live_mode(tmp_path, monkeypatch):
    fund = HedgeFundEngine(_fund_config(tmp_path))
    manager = RiskManager()
    manager.set_fund_engine(fund)
    monkeypatch.setenv("EXECUTION_MODE", "live")

    assert manager.check_order("GridRunner", 1.0, symbol="ETH-EUR") is False
    fund.refresh_nav(100.0, source="bitvavo", verified=True)
    assert manager.check_order("GridRunner", 1.0, symbol="ETH-EUR") is True


def test_bitvavo_account_nav_uses_eur_bid_and_in_order_balance():
    valuation = AutoTrader.value_bitvavo_balances_eur(
        [
            {"symbol": "EUR", "available": "10", "inOrder": "5"},
            {"symbol": "BTC", "available": "0.001", "inOrder": "0.002"},
            {"symbol": "ETH", "available": "0", "inOrder": "0"},
        ],
        {
            "BTC-EUR": {"bid": "50000", "ask": "50100"},
            "ETH-EUR": {"bid": "2000", "ask": "2010"},
        },
    )
    assert valuation["verified"] is True
    assert valuation["unpriced_assets"] == []
    assert valuation["asset_values_eur"]["EUR"] == 15.0
    assert valuation["asset_values_eur"]["BTC"] == 150.0
    assert valuation["nav_eur"] == 165.0


def test_bitvavo_account_nav_fails_closed_for_unpriced_positive_asset():
    valuation = AutoTrader.value_bitvavo_balances_eur(
        [
            {"symbol": "EUR", "available": "50", "inOrder": "0"},
            {"symbol": "UNKNOWN", "available": "2", "inOrder": "0"},
        ],
        {},
    )
    assert valuation["verified"] is False
    assert valuation["nav_eur"] == 50.0
    assert valuation["unpriced_assets"] == ["UNKNOWN"]



def test_live_bitvavo_nav_recovers_missing_bulk_book_with_targeted_retry(tmp_path):
    class DummyGateway:
        def __init__(self):
            self.last_limits = None

        def set_verified_nav_limits(self, **kwargs):
            self.last_limits = kwargs

    class DummyBitvavo:
        def __init__(self):
            self.gateway = DummyGateway()
            self.requested = []

        def ticker_books(self):
            return {
                "BTC-EUR": {
                    "market": "BTC-EUR",
                    "bid": "50000",
                    "ask": "50100",
                    "bid_size": "1",
                    "ask_size": "1",
                }
            }

        def ticker_book(self, market):
            self.requested.append(market)
            if market == "ETH-EUR":
                return {
                    "market": "ETH-EUR",
                    "bid": "2000",
                    "ask": "2010",
                    "bid_size": "10",
                    "ask_size": "10",
                }
            raise RuntimeError("missing market")

    class DummyAllocator:
        def __init__(self):
            self.nav = None

        def set_verified_nav(self, nav):
            self.nav = nav

    agent = object.__new__(AutoTrader)
    agent._bitvavo = DummyBitvavo()
    agent._allocator = DummyAllocator()
    agent._fund = HedgeFundEngine(_fund_config(tmp_path))
    agent._live_fund_nav_eur = None
    agent._live_fund_nav_updated_at = 0.0
    agent._live_fund_nav_unpriced_assets = []

    valuation = agent.refresh_live_fund_nav_from_balances(
        [
            {"symbol": "EUR", "available": "50", "inOrder": "0"},
            {"symbol": "ETH", "available": "0.01", "inOrder": "0"},
        ]
    )

    assert valuation["verified"] is True
    assert valuation["unpriced_assets"] == []
    assert valuation["nav_eur"] == 70.0
    assert agent._bitvavo.requested == ["ETH-EUR"]
    assert agent._allocator.nav == 70.0
    assert agent._fund.status()["risk"]["nav_verified"] is True


def test_live_bitvavo_nav_still_fails_closed_when_targeted_retry_cannot_price_asset(tmp_path):
    class DummyGateway:
        def set_verified_nav_limits(self, **_kwargs):
            raise AssertionError("must not set verified NAV limits")

    class DummyBitvavo:
        gateway = DummyGateway()

        def ticker_books(self):
            return {
                "BTC-EUR": {
                    "market": "BTC-EUR",
                    "bid": "50000",
                    "ask": "50100",
                    "bid_size": "1",
                    "ask_size": "1",
                }
            }

        def ticker_book(self, _market):
            raise RuntimeError("still unavailable")

    class DummyAllocator:
        def set_verified_nav(self, _nav):
            raise AssertionError("must not accept unverified NAV")

    agent = object.__new__(AutoTrader)
    agent._bitvavo = DummyBitvavo()
    agent._allocator = DummyAllocator()
    agent._fund = HedgeFundEngine(_fund_config(tmp_path))
    agent._live_fund_nav_eur = None
    agent._live_fund_nav_updated_at = 0.0
    agent._live_fund_nav_unpriced_assets = []

    valuation = agent.refresh_live_fund_nav_from_balances(
        [
            {"symbol": "EUR", "available": "50", "inOrder": "0"},
            {"symbol": "UNKNOWN", "available": "2", "inOrder": "0"},
        ]
    )

    assert valuation["verified"] is False
    assert valuation["unpriced_assets"] == ["UNKNOWN"]
    assert agent._fund.status()["risk"]["nav_verified"] is False


def test_verified_high_water_survives_restart_and_preserves_drawdown_gate(tmp_path):
    config = _fund_config(
        tmp_path,
        initial_nav_eur=100.0,
        max_portfolio_drawdown_pct=8.0,
    )
    first = HedgeFundEngine(config)
    first.refresh_nav(120.0, source="bitvavo", verified=True)

    assert first.ledger.has_event_type("nav_high_water") is True
    assert first.ledger.max_verified_nav_eur() == 120.0

    restarted = HedgeFundEngine(config)
    assert restarted.status()["risk"]["peak_nav_eur"] == 120.0
    restarted.refresh_nav(110.0, source="bitvavo", verified=True)

    status = restarted.status()["risk"]
    assert status["drawdown_pct"] > 8.0
    decision = restarted.pretrade_check(
        strategy="GridRunner",
        symbol="ETH-EUR",
        notional_eur=1.0,
    )
    assert decision.accepted is False
    assert "drawdown" in decision.reason.lower()


def test_unverified_nav_is_not_restored_as_high_water(tmp_path):
    config = _fund_config(tmp_path, initial_nav_eur=100.0)
    first = HedgeFundEngine(config)
    first.refresh_nav(1000.0, source="local-estimate", verified=False)

    assert first.ledger.max_verified_nav_eur() == 0.0

    restarted = HedgeFundEngine(config)
    assert restarted.status()["risk"]["peak_nav_eur"] == 100.0


def test_verified_exposure_snapshot_replaces_stale_fill_exposure(tmp_path):
    fund = HedgeFundEngine(_fund_config(tmp_path, initial_nav_eur=80.0))
    fund.refresh_nav(80.0, source="test", verified=True)
    fund.restore_fill(
        strategy="GridRunner",
        symbol="MANA-EUR",
        side="BUY",
        notional_eur=12.0,
    )
    assert fund.risk.gross_exposure_eur == 12.0

    result = fund.reconcile_exposure_snapshot(
        [("GridRunner", "MANA-EUR", 5.0)]
    )
    assert result["previous_gross_exposure_eur"] == 12.0
    assert result["gross_exposure_eur"] == 5.0
    assert fund.risk.state.strategy_exposure_eur["GridRunner"] == 5.0
    assert fund.risk.state.asset_exposure_eur["MANA-EUR"] == 5.0

    result = fund.reconcile_exposure_snapshot([])
    assert result["gross_exposure_eur"] == 0.0
    assert fund.risk.state.strategy_exposure_eur == {}
    assert fund.risk.state.asset_exposure_eur == {}


def test_bitvavo_exposure_reconciliation_clears_exchange_absent_ghost_inventory(tmp_path):
    class DummyOrderManager:
        def open_orders(self):
            return []

    class DummyJournal:
        def inflight(self):
            return []

        def strategy_active_markets(self, strategy, *, min_inventory_quote_value):
            assert strategy == "GridRunner"
            return [
                {
                    "market": "MANA-EUR",
                    "inventory_quantity": "100",
                    "inventory_quote_value": "10",
                    "average_entry_price": "0.10",
                    "open_orders": 0,
                }
            ]

    class DummyBitvavo:
        def __init__(self):
            self.journal = DummyJournal()

        def ticker_books(self):
            return {"MANA-EUR": {"market": "MANA-EUR", "bid": "0.10"}}

        def ticker_book(self, market):
            return {"market": market, "bid": "0.10"}

        def quote_to_eur_rate(self, _market):
            return 1.0

    class DummyStrategy:
        name = "GridRunner"

    fund = HedgeFundEngine(_fund_config(tmp_path, initial_nav_eur=80.0))
    fund.refresh_nav(80.0, source="test", verified=True)
    fund.restore_fill(
        strategy="GridRunner",
        symbol="MANA-EUR",
        side="BUY",
        notional_eur=12.0,
    )
    assert fund.risk.gross_exposure_eur == 12.0

    agent = object.__new__(AutoTrader)
    agent._fund = fund
    agent._om = DummyOrderManager()
    agent._bitvavo = DummyBitvavo()
    agent._strategies = {"grid": DummyStrategy()}

    status = agent.reconcile_live_fund_exposure_from_balances(
        [{"symbol": "EUR", "available": "20.45", "inOrder": "0"}],
        exchange_open_order_count=0,
    )

    assert status["reconciled"] is True
    assert status["journal_candidate_count"] == 1
    assert status["entry_count"] == 0
    assert fund.risk.gross_exposure_eur == 0.0
    assert fund.max_entry_notional_eur(
        strategy="GridRunner",
        symbol="MANA-EUR",
        require_verified_nav=True,
    ) > 0.0


def test_bitvavo_exposure_reconciliation_caps_journal_inventory_to_exchange_balance(tmp_path):
    class DummyOrderManager:
        def open_orders(self):
            return []

    class DummyJournal:
        def inflight(self):
            return []

        def strategy_active_markets(self, strategy, *, min_inventory_quote_value):
            return [
                {
                    "market": "MANA-EUR",
                    "inventory_quantity": "100",
                    "inventory_quote_value": "10",
                    "average_entry_price": "0.10",
                    "open_orders": 0,
                }
            ]

    class DummyBitvavo:
        def __init__(self):
            self.journal = DummyJournal()

        def ticker_books(self):
            return {"MANA-EUR": {"market": "MANA-EUR", "bid": "0.10"}}

        def ticker_book(self, market):
            return {"market": market, "bid": "0.10"}

        def quote_to_eur_rate(self, _market):
            return 1.0

    class DummyStrategy:
        name = "GridRunner"

    fund = HedgeFundEngine(_fund_config(tmp_path, initial_nav_eur=80.0))
    fund.refresh_nav(80.0, source="test", verified=True)
    agent = object.__new__(AutoTrader)
    agent._fund = fund
    agent._om = DummyOrderManager()
    agent._bitvavo = DummyBitvavo()
    agent._strategies = {"grid": DummyStrategy()}

    status = agent.reconcile_live_fund_exposure_from_balances(
        [
            {"symbol": "EUR", "available": "20.45", "inOrder": "0"},
            {"symbol": "MANA", "available": "50", "inOrder": "0"},
        ],
        exchange_open_order_count=0,
    )

    assert status["reconciled"] is True
    assert status["entry_count"] == 1
    assert fund.risk.gross_exposure_eur == 5.0
