from decimal import Decimal

from autotrader.core.order_journal import OrderJournal


def _fill(journal, cid, strategy, market, side, amount, price, fee="0", fee_currency="EUR"):
    journal.record_intent(
        client_order_id=cid,
        market=market,
        side=side,
        order_type="limit",
        amount=str(amount),
        price=str(price),
    )
    journal.set_strategy(cid, strategy)
    journal.update(cid, "filled", {"status": "filled"})
    journal.record_fill(
        cid,
        {
            "fillId": cid + "-fill",
            "amount": str(amount),
            "price": str(price),
            "fee": str(fee),
            "feeCurrency": fee_currency,
        },
    )


def test_verified_inventory_reconciliation_clears_only_old_bot_ownership(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    _fill(
        journal,
        "rsr-buy-old",
        "GridRunner",
        "RSR-EUR",
        "buy",
        "5845.4476",
        "0.0014",
    )

    before = journal.inventory_cost_basis("RSR-EUR", "GridRunner")
    assert before["quantity"] == Decimal("5845.4476")

    recorded = journal.record_inventory_reconciliation(
        "RSR-EUR",
        "GridRunner",
        exchange_total=Decimal("0"),
        reason="verified_exchange_zero_balance",
    )
    assert recorded is True

    after = journal.inventory_cost_basis("RSR-EUR", "GridRunner")
    assert after["quantity"] == Decimal("0")
    assert after["average_entry_price"] == Decimal("0")
    assert journal.net_base_inventory("RSR-EUR", "GridRunner") == Decimal("0")
    assert journal.strategy_active_markets("GridRunner") == []

    reconciliation = journal.latest_inventory_reconciliation(
        "RSR-EUR", "GridRunner"
    )
    assert reconciliation is not None
    assert reconciliation["reason"] == "verified_exchange_zero_balance"
    assert Decimal(reconciliation["journal_quantity"]) == Decimal("5845.4476")

    # Historical evidence stays present; only current ownership is reset.
    performance = journal.strategy_performance("RSR-EUR", "GridRunner")
    assert performance["quantity"] == Decimal("0")
    assert performance["buy_cash_out_eur"] == Decimal("8.18362664")
    journal.close()


def test_new_fill_after_reconciliation_becomes_new_inventory(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    _fill(
        journal,
        "rsr-buy-old",
        "GridRunner",
        "RSR-EUR",
        "buy",
        "5000",
        "0.0014",
    )
    assert journal.record_inventory_reconciliation(
        "RSR-EUR",
        "GridRunner",
        exchange_total=Decimal("0"),
        reason="verified_exchange_zero_balance",
    )

    _fill(
        journal,
        "rsr-buy-new",
        "GridRunner",
        "RSR-EUR",
        "buy",
        "4000",
        "0.0015",
    )

    inventory = journal.inventory_cost_basis("RSR-EUR", "GridRunner")
    assert inventory["quantity"] == Decimal("4000")
    assert inventory["average_entry_price"] == Decimal("0.0015")

    performance = journal.strategy_performance("RSR-EUR", "GridRunner")
    assert performance["quantity"] == Decimal("4000")
    assert performance["inventory_cost_eur"] == Decimal("6.0000")
    journal.close()


def test_reconciliation_is_idempotent_for_same_fill_cutoff(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    _fill(
        journal,
        "rsr-buy-old",
        "GridRunner",
        "RSR-EUR",
        "buy",
        "5000",
        "0.0014",
    )

    assert journal.record_inventory_reconciliation(
        "RSR-EUR",
        "GridRunner",
        exchange_total=Decimal("0"),
        reason="verified_exchange_zero_balance",
    ) is True
    assert journal.record_inventory_reconciliation(
        "RSR-EUR",
        "GridRunner",
        exchange_total=Decimal("0"),
        reason="verified_exchange_zero_balance",
    ) is False
    journal.close()
