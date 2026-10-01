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



def test_daily_entry_turnover_ignores_risk_reducing_sells(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    buy = "55555555-5555-5555-5555-555555555555"
    sell = "66666666-6666-6666-6666-666666666666"
    journal.record_intent(
        client_order_id=buy, market="SOL-EUR", side="buy",
        order_type="limit", amount="0.06", price="100",
    )
    journal.record_execution_acceptance(buy, "6")
    journal.record_intent(
        client_order_id=sell, market="SOL-EUR", side="sell",
        order_type="limit", amount="0.06", price="101",
    )
    # Legacy data may contain sells in the ledger; turnover must still count BUYs only.
    journal.record_execution_acceptance(sell, "6.06")
    assert journal.daily_execution_exposure_utc() == Decimal("6")
    journal.close()


def test_completed_round_trip_releases_current_exposure(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    buy = "77777777-7777-7777-7777-777777777777"
    sell = "88888888-8888-8888-8888-888888888888"
    journal.record_intent(
        client_order_id=buy, market="SOL-EUR", side="buy",
        order_type="limit", amount="0.06", price="100",
    )
    journal.set_strategy(buy, "GridRunner")
    journal.record_execution_acceptance(buy, "6")
    journal.update(buy, "filled")
    journal.record_fill(buy, {
        "id": "buy-fill",
        "amount": "0.06",
        "price": "100",
        "fee": "0",
        "feeCurrency": "EUR",
    })
    assert journal.current_execution_exposure_eur() == Decimal("6")

    journal.record_intent(
        client_order_id=sell, market="SOL-EUR", side="sell",
        order_type="limit", amount="0.06", price="101",
    )
    journal.set_strategy(sell, "GridRunner")
    journal.update(sell, "filled")
    journal.record_fill(sell, {
        "id": "sell-fill",
        "amount": "0.06",
        "price": "101",
        "fee": "0",
        "feeCurrency": "EUR",
    })

    assert journal.current_execution_exposure_eur() == Decimal("0")
    assert journal.daily_execution_exposure_utc() == Decimal("6")
    journal.close()


def test_canceled_buy_releases_current_exposure_but_keeps_turnover(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    cid = "99999999-9999-9999-9999-999999999999"
    journal.record_intent(
        client_order_id=cid, market="ETH-EUR", side="buy",
        order_type="limit", amount="0.0025", price="2400",
    )
    journal.set_strategy(cid, "GridRunnerETH")
    journal.record_execution_acceptance(cid, "6")
    assert journal.current_execution_exposure_eur() == Decimal("6.0000")
    journal.update(cid, "canceled")
    assert journal.current_execution_exposure_eur() == Decimal("0")
    assert journal.daily_execution_exposure_utc() == Decimal("6")
    journal.close()
