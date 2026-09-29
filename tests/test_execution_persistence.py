from decimal import Decimal

import pytest

from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError
from autotrader.core.execution_gateway import ExecutionGateway
from autotrader.core.order_journal import OrderJournal


def test_execution_ledger_persists_daily_exposure(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    cid = "11111111-1111-1111-1111-111111111111"
    journal.record_intent(
        client_order_id=cid, market="BTC-EUR", side="buy",
        order_type="limit", amount="0.0001", price="70000",
    )
    assert journal.record_execution_acceptance(cid, "7") is True
    assert journal.record_execution_acceptance(cid, "7") is False
    assert journal.daily_execution_exposure_utc() == Decimal("7")
    journal.close()


def test_adapter_restores_daily_exposure_from_journal(tmp_path):
    path = str(tmp_path / "orders.sqlite3")
    journal = OrderJournal(path)
    cid = "22222222-2222-2222-2222-222222222222"
    journal.record_intent(
        client_order_id=cid, market="BTC-EUR", side="buy",
        order_type="limit", amount="0.0001", price="70000",
    )
    journal.record_execution_acceptance(cid, "7")
    gateway = ExecutionGateway()
    adapter = BitvavoAdapter(journal=journal, gateway=gateway)
    assert adapter.gateway.daily_exposure_eur == Decimal("7")
    journal.close()


def test_duplicate_client_order_id_never_reposts(monkeypatch, tmp_path):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "true")
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    adapter = BitvavoAdapter(journal=journal)
    monkeypatch.setattr(adapter, "ticker_price", lambda market: Decimal("70000"))
    monkeypatch.setattr(
        adapter,
        "markets",
        lambda market=None: [{
            "status": "trading", "orderTypes": ["limit"],
            "quantityDecimals": 4, "tickSize": "0.01",
            "minOrderInBaseAsset": "0.0001",
            "minOrderInQuoteAsset": "5",
        }],
    )
    cid = "33333333-3333-3333-3333-333333333333"
    first = adapter.place_limit_order(
        "BTC-EUR", "buy", Decimal("0.0001"), Decimal("70000"), cid
    )
    assert first["status"] == "SHADOW"
    with pytest.raises(BitvavoError, match="duplicate"):
        adapter.place_limit_order(
            "BTC-EUR", "buy", Decimal("0.0001"), Decimal("70000"), cid
        )
    journal.close()


def test_error_without_exchange_id_remains_reconcilable(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    cid = "44444444-4444-4444-4444-444444444444"
    journal.record_intent(
        client_order_id=cid, market="BTC-EUR", side="buy",
        order_type="limit", amount="0.0001", price="70000",
    )
    journal.update(cid, "error", {"category": "network_error"}, error="network_error")
    rows = journal.reconcile_candidates()
    assert any(row["client_order_id"] == cid for row in rows)
    journal.close()
