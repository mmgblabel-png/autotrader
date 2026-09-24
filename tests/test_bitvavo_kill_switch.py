from decimal import Decimal

from autotrader.connectors.bitvavo import BitvavoAdapter
from autotrader.core.order_journal import OrderJournal


def test_kill_switch_shadow_cancels_without_orders(monkeypatch, tmp_path):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "true")
    adapter = BitvavoAdapter(journal=OrderJournal(str(tmp_path / "orders.sqlite3")))
    monkeypatch.setattr(adapter, "open_orders", lambda: [{"market": "BTC-EUR", "orderId": "o-1"}])
    monkeypatch.setattr(adapter, "balance", lambda: [{"symbol": "BTC", "available": "0.1"}])
    report = adapter.kill_switch_close_all()
    assert report["live_orders_sent"] is False
    assert report["orders_canceled"][0]["status"] == "SHADOW"
    assert report["position_close_status"] == "blocked_fail_closed"
    adapter.journal.close()


def test_kill_switch_requires_explicit_position_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "false")
    monkeypatch.setenv("EMERGENCY_STOP", "true")
    monkeypatch.setenv("LIVE_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("LIVE_EXECUTION_ADAPTER_INSTALLED", "true")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDERS")
    monkeypatch.delenv("KILL_SWITCH_CLOSE_POSITIONS", raising=False)
    adapter = BitvavoAdapter(journal=OrderJournal(str(tmp_path / "orders.sqlite3")))
    monkeypatch.setattr(adapter, "open_orders", lambda: [])
    monkeypatch.setattr(adapter, "balance", lambda: [{"symbol": "BTC", "available": "0.1"}])
    report = adapter.kill_switch_close_all()
    assert report["position_close_status"] == "blocked_fail_closed"
    assert report["positions_closed"] == []
    adapter.journal.close()


def test_kill_switch_live_path_is_allowlisted_and_capped(monkeypatch, tmp_path):
    for name, value in {
        "EXECUTION_MODE": "live",
        "BITVAVO_DRY_RUN": "false",
        "EMERGENCY_STOP": "true",
        "LIVE_EXECUTION_APPROVED": "true",
        "LIVE_EXECUTION_ADAPTER_INSTALLED": "true",
        "LIVE_TRADING_CONFIRMATION": "I_UNDERSTAND_LIVE_ORDERS",
        "KILL_SWITCH_CLOSE_POSITIONS": "true",
        "KILL_SWITCH_MAX_LIQUIDATION_EUR": "10",
    }.items():
        monkeypatch.setenv(name, value)
    adapter = BitvavoAdapter(journal=OrderJournal(str(tmp_path / "orders.sqlite3")))
    monkeypatch.setattr(adapter, "open_orders", lambda: [])
    monkeypatch.setattr(adapter, "balance", lambda: [{"symbol": "BTC", "available": "1"}, {"symbol": "ETH", "available": "1"}])
    monkeypatch.setattr(adapter, "ticker_price", lambda market: Decimal("50000") if market == "BTC-EUR" else Decimal("2000"))
    calls = []
    monkeypatch.setattr(adapter, "_private_request", lambda method, endpoint, body=None, query=None: calls.append((method, endpoint, body)) or {"orderId": "kill-1", "status": "accepted"})
    report = adapter.kill_switch_close_all(markets=["BTC-EUR"])
    assert report["position_close_status"] == "completed"
    assert len(report["positions_closed"]) == 1
    assert report["positions_closed"][0]["amount"] == "0.0002"
    assert len(calls) == 1
    adapter.journal.close()
