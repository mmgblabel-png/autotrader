from autotrader.core.profit_engine import ProfitEngine, Trade


def test_buy_sell_cycle_realizes_only_on_exit_and_keeps_fees_separate(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    buy_delta = pe.record_trade(Trade(
        strategy="GridRunner", symbol="SOL-EUR", side="BUY",
        quantity=1.0, price=100.0, fee=0.10, fee_currency="EUR",
        fill_key="buy-1",
    ))
    assert buy_delta == -0.10
    assert pe.summary()["GridRunner"]["realized_pnl"] == 0.0
    assert pe.position_state("GridRunner", "SOL-EUR")["quantity"] == 1.0

    sell_delta = pe.record_trade(Trade(
        strategy="GridRunner", symbol="SOL-EUR", side="SELL",
        quantity=1.0, price=110.0, fee=0.10, fee_currency="EUR",
        fill_key="sell-1",
    ))
    assert round(sell_delta, 8) == 9.9
    stats = pe.summary()["GridRunner"]
    assert round(stats["realized_pnl"], 8) == 10.0
    assert round(stats["total_fees"], 8) == 0.2
    assert round(stats["net_pnl"], 8) == 9.8
    assert stats["wins"] == 1
    assert pe.position_state("GridRunner", "SOL-EUR")["quantity"] == 0.0


def test_base_currency_buy_fee_reduces_owned_inventory_without_double_count(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_trade(Trade(
        strategy="MarketMaker", symbol="BTC-EUR", side="BUY",
        quantity=1.0, price=100.0, fee=0.01, fee_currency="BTC",
        fill_key="buy-base-fee",
    ))
    pos = pe.position_state("MarketMaker", "BTC-EUR")
    assert round(pos["quantity"], 8) == 0.99
    assert round(pos["average_price"], 8) == 100.0
    assert round(pe.summary()["MarketMaker"]["total_fees"], 8) == 1.0


def test_duplicate_fill_key_is_idempotent(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    trade = Trade(
        strategy="SniperBot", symbol="XRP-EUR", side="BUY",
        quantity=3.0, price=2.0, fee=0.01, fee_currency="EUR",
        fill_key="same-fill",
    )
    pe.record_trade(trade)
    assert pe.record_trade(trade) == 0.0
    assert pe.summary()["SniperBot"]["num_trades"] == 1


def test_mark_to_market_uses_owned_inventory(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_trade(Trade(
        strategy="GridRunner", symbol="SOL-EUR", side="BUY",
        quantity=2.0, price=100.0, fill_key="mark-buy",
    ))
    assert pe.mark_to_market("GridRunner", "SOL-EUR", 105.0) == 10.0
    assert pe.summary()["GridRunner"]["unrealized_pnl"] == 10.0


def test_unmatched_sell_does_not_fabricate_profit(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    delta = pe.record_trade(Trade(
        strategy="SniperBot", symbol="XRP-EUR", side="SELL",
        quantity=2.0, price=2.0, fee=0.01, fee_currency="EUR",
        fill_key="unmatched-sell",
    ))
    assert delta == -0.01
    assert pe.summary()["SniperBot"]["realized_pnl"] == 0.0
    assert any(e["kind"] == "accounting" for e in pe.events())


def test_base_currency_sell_fee_is_not_double_counted(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_trade(Trade(
        strategy="MarketMaker", symbol="BTC-EUR", side="BUY",
        quantity=1.0, price=100.0, fill_key="buy-before-base-sell-fee",
    ))
    delta = pe.record_trade(Trade(
        strategy="MarketMaker", symbol="BTC-EUR", side="SELL",
        quantity=0.99, price=110.0, fee=0.01, fee_currency="BTC",
        fill_key="sell-base-fee",
    ))
    assert round(pe.summary()["MarketMaker"]["realized_pnl"], 8) == 10.0
    assert round(pe.summary()["MarketMaker"]["total_fees"], 8) == 1.1
    assert round(pe.summary()["MarketMaker"]["net_pnl"], 8) == 8.9
    assert round(delta, 8) == 8.9
    assert pe.position_state("MarketMaker", "BTC-EUR")["quantity"] == 0.0
