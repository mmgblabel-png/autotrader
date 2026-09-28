from autotrader.core.order_journal import OrderJournal


def test_order_journal_survives_and_deduplicates_fills(tmp_path):
    db = tmp_path / "orders.sqlite3"
    journal = OrderJournal(str(db))

    assert journal.record_intent(
        client_order_id="cid-1",
        market="BTC-EUR",
        side="buy",
        order_type="limit",
        amount="0.001",
        price="50000",
    )
    assert not journal.record_intent(
        client_order_id="cid-1",
        market="BTC-EUR",
        side="buy",
        order_type="limit",
        amount="0.001",
        price="50000",
    )

    journal.update("cid-1", "partiallyFilled", {"status": "partiallyFilled"}, exchange_order_id="exchange-1")
    fill = {"tradeId": "trade-1", "amount": "0.0004", "price": "50000", "fee": "0.01"}
    assert journal.record_fill("cid-1", fill)
    assert not journal.record_fill("cid-1", fill)

    restarted = OrderJournal(str(db))
    record = restarted.get("cid-1")
    assert record["exchange_order_id"] == "exchange-1"
    assert record["status"] == "partiallyFilled"
    assert restarted.fills("cid-1") == [fill]
    assert restarted.inflight()[0]["client_order_id"] == "cid-1"


def test_order_journal_terminal_orders_are_not_inflight(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    journal.record_intent(
        client_order_id="cid-2",
        market="BTC-EUR",
        side="sell",
        order_type="market",
        amount="0.001",
        price=None,
    )
    journal.update("cid-2", "filled", {"status": "filled"})
    assert journal.inflight() == []
