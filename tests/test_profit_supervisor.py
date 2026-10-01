from decimal import Decimal

from autotrader.core.order_journal import OrderJournal
from autotrader.core.profit_supervisor import ProfitPolicy, ProfitSupervisor


def _fill(journal, cid, strategy, side, amount, price, fee="0", fee_currency="EUR"):
    journal.record_intent(
        client_order_id=cid,
        market="SOL-EUR",
        side=side,
        order_type="limit",
        amount=str(amount),
        price=str(price),
    )
    journal.set_strategy(cid, strategy)
    journal.update(cid, "filled", {"status": "filled"})
    journal.record_fill(cid, {
        "fillId": cid + "-fill",
        "amount": str(amount),
        "price": str(price),
        "fee": str(fee),
        "feeCurrency": fee_currency,
    })


def test_durable_performance_embeds_buy_fee_and_estimates_exit_cost(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    _fill(journal, "buy-1", "GridRunner", "buy", "1", "100", "0.25", "EUR")

    perf = journal.strategy_performance(
        "SOL-EUR",
        "GridRunner",
        mark_price=Decimal("101"),
        estimated_exit_cost_pct=Decimal("0.30"),
    )

    assert perf["quantity"] == Decimal("1")
    assert perf["inventory_cost_eur"] == Decimal("100.25")
    assert perf["average_entry_price"] == Decimal("100.25")
    assert perf["estimated_exit_proceeds_eur"] == Decimal("100.697")
    assert perf["unrealized_net_pnl_eur"] == Decimal("0.447")
    assert perf["break_even_exit_price"] > Decimal("100.55")
    journal.close()


def test_durable_performance_realizes_net_cash_profit(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    _fill(journal, "buy-1", "GridRunner", "buy", "1", "100", "0.25", "EUR")
    _fill(journal, "sell-1", "GridRunner", "sell", "1", "101", "0.2525", "EUR")

    perf = journal.strategy_performance("SOL-EUR", "GridRunner")

    assert perf["quantity"] == Decimal("0")
    assert perf["realized_net_pnl_eur"] == Decimal("0.4975")
    assert perf["fees_quote_equivalent_eur"] == Decimal("0.5025")
    assert perf["profitable_exits"] == 1
    assert perf["losing_exits"] == 0
    journal.close()


def test_profit_policy_requires_costs_plus_minimum_net_edge(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    supervisor = ProfitSupervisor(journal, {
        "estimated_entry_fee_pct": 0.25,
        "estimated_exit_fee_pct": 0.25,
        "estimated_slippage_each_leg_pct": 0.05,
        "min_expected_net_edge_pct": 0.15,
    })

    assert supervisor.policy.required_entry_edge_pct == Decimal("0.75")
    assert supervisor.policy.required_exit_markup_from_cost_pct == Decimal("0.45")
    assert supervisor.entry_has_edge(0.80) is True
    assert supervisor.entry_has_edge(0.70) is False
    journal.close()


def test_profit_snapshot_reports_fee_aware_minimum_exit(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    _fill(journal, "buy-1", "GridRunner", "buy", "1", "100", "0.25", "EUR")
    supervisor = ProfitSupervisor(journal, {})

    snapshot = supervisor.strategy_snapshot("SOL-EUR", "GridRunner", 101)

    assert snapshot["state"] == "profitable_if_exited"
    assert snapshot["required_entry_edge_pct"] == 0.75
    assert snapshot["min_profit_exit_price"] > snapshot["break_even_exit_price"]
    journal.close()


def test_profit_snapshot_can_use_route_specific_fee_tier(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    supervisor = ProfitSupervisor(journal, {
        "estimated_entry_fee_pct": 0.25,
        "estimated_exit_fee_pct": 0.25,
        "estimated_slippage_each_leg_pct": 0.05,
        "min_expected_net_edge_pct": 0.15,
    })
    maker = supervisor.strategy_snapshot(
        "SOL-EUR", "GridRunner", 100,
        entry_fee_pct=0.15,
        exit_fee_pct=0.15,
        fee_policy_source="bitvavo_account_maker_post_only",
    )
    assert maker["required_entry_edge_pct"] == 0.55
    assert maker["required_exit_markup_from_cost_pct"] == 0.35
    assert maker["fee_policy_source"] == "bitvavo_account_maker_post_only"
    fallback = supervisor.strategy_snapshot("SOL-EUR", "GridRunner", 100)
    assert fallback["required_entry_edge_pct"] == 0.75
    assert fallback["fee_policy_source"] == "configured_conservative"
    journal.close()


def test_crypto_quote_round_trip_reports_eur_pnl(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    journal.record_intent(
        client_order_id="eth-btc-buy",
        market="ETH-BTC",
        side="buy",
        order_type="limit",
        amount="0.002",
        price="0.05",
        quote_to_eur="70000",
    )
    journal.set_strategy("eth-btc-buy", "GridRunner")
    journal.update("eth-btc-buy", "filled", {"status": "filled"})
    journal.record_fill("eth-btc-buy", {
        "fillId": "eth-btc-buy-fill",
        "amount": "0.002",
        "price": "0.05",
        "fee": "0.00000025",
        "feeCurrency": "BTC",
    })

    journal.record_intent(
        client_order_id="eth-btc-sell",
        market="ETH-BTC",
        side="sell",
        order_type="limit",
        amount="0.002",
        price="0.051",
        quote_to_eur="71000",
    )
    journal.set_strategy("eth-btc-sell", "GridRunner")
    journal.update("eth-btc-sell", "filled", {"status": "filled"})
    journal.record_fill("eth-btc-sell", {
        "fillId": "eth-btc-sell-fill",
        "amount": "0.002",
        "price": "0.051",
        "fee": "0.000000255",
        "feeCurrency": "BTC",
    })

    perf = journal.strategy_performance(
        "ETH-BTC",
        "GridRunner",
        quote_to_eur=Decimal("71000"),
    )
    assert perf["quantity"] == Decimal("0")
    assert perf["realized_net_pnl_eur"] > Decimal("0")
    assert perf["fees_quote_equivalent_eur"] > Decimal("0")
    assert perf["buy_cash_out_eur"] > Decimal("6")
    assert perf["sell_cash_in_eur"] > perf["buy_cash_out_eur"]
    journal.close()


def test_crypto_quote_open_inventory_counts_as_eur_exposure(tmp_path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    journal.record_intent(
        client_order_id="eth-btc-buy-open",
        market="ETH-BTC",
        side="buy",
        order_type="limit",
        amount="0.002",
        price="0.05",
        quote_to_eur="70000",
    )
    journal.set_strategy("eth-btc-buy-open", "GridRunner")
    journal.update("eth-btc-buy-open", "filled", {"status": "filled"})
    journal.record_fill("eth-btc-buy-open", {
        "fillId": "eth-btc-open-fill",
        "amount": "0.002",
        "price": "0.05",
        "fee": "0",
        "feeCurrency": "BTC",
    })
    exposure = journal.current_execution_exposure_eur()
    assert exposure == Decimal("7.00000")
    journal.close()
