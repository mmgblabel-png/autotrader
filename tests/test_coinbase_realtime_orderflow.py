from autotrader.core.coinbase_realtime_orderflow import CoinbaseRealtimeOrderflowEngine


def test_realtime_orderflow_builds_depth_and_trade_metrics():
    engine = CoinbaseRealtimeOrderflowEngine(
        {
            "max_products": 5,
            "depth_levels": 2,
            "trade_window_seconds": 60,
            "stale_after_seconds": 15,
        }
    )
    engine.set_products(["BTC-EUR"])

    engine.process_message(
        {
            "channel": "l2_data",
            "events": [
                {
                    "type": "snapshot",
                    "product_id": "BTC-EUR",
                    "updates": [
                        {"side": "bid", "price_level": "100", "new_quantity": "2"},
                        {"side": "bid", "price_level": "99", "new_quantity": "3"},
                        {"side": "offer", "price_level": "101", "new_quantity": "1"},
                        {"side": "offer", "price_level": "102", "new_quantity": "2"},
                    ],
                }
            ],
        },
        received_at=100.0,
    )
    engine.process_message(
        {
            "channel": "market_trades",
            "events": [
                {
                    "type": "update",
                    "trades": [
                        {"product_id": "BTC-EUR", "price": "100.5", "size": "2", "side": "BUY"},
                        {"product_id": "BTC-EUR", "price": "100.5", "size": "0.5", "side": "SELL"},
                    ],
                }
            ],
        },
        received_at=101.0,
    )

    row = engine.snapshot("BTC-EUR", now=102.0)
    assert row["subscribed"] is True
    assert row["fresh"] is True
    assert row["best_bid"] == 100.0
    assert row["best_ask"] == 101.0
    assert row["spread_bps"] > 0
    assert row["book_imbalance"] > 0
    assert row["microprice_edge_bps"] > 0
    assert row["trade_flow_imbalance"] > 0
    assert row["trade_count"] == 2


def test_realtime_orderflow_applies_l2_zero_quantity_delete():
    engine = CoinbaseRealtimeOrderflowEngine({"depth_levels": 3})
    engine.set_products(["ETH-EUR"])
    engine.process_message(
        {
            "channel": "l2_data",
            "events": [
                {
                    "type": "snapshot",
                    "product_id": "ETH-EUR",
                    "updates": [
                        {"side": "bid", "price_level": "3000", "new_quantity": "1"},
                        {"side": "bid", "price_level": "2999", "new_quantity": "2"},
                        {"side": "offer", "price_level": "3001", "new_quantity": "1"},
                    ],
                }
            ],
        },
        received_at=200.0,
    )
    engine.process_message(
        {
            "channel": "l2_data",
            "events": [
                {
                    "type": "update",
                    "product_id": "ETH-EUR",
                    "updates": [
                        {"side": "bid", "price_level": "3000", "new_quantity": "0"},
                        {"side": "bid", "price_level": "2998", "new_quantity": "4"},
                    ],
                }
            ],
        },
        received_at=201.0,
    )
    row = engine.snapshot("ETH-EUR", now=202.0)
    assert row["best_bid"] == 2999.0
    assert row["best_ask"] == 3001.0


def test_realtime_orderflow_marks_stale_data():
    engine = CoinbaseRealtimeOrderflowEngine({"stale_after_seconds": 5})
    engine.set_products(["XRP-EUR"])
    engine.process_message(
        {
            "channel": "ticker",
            "events": [
                {
                    "type": "update",
                    "tickers": [
                        {
                            "product_id": "XRP-EUR",
                            "price": "1",
                            "best_bid": "0.999",
                            "best_ask": "1.001",
                            "best_bid_quantity": "100",
                            "best_ask_quantity": "100",
                        }
                    ],
                }
            ],
        },
        received_at=300.0,
    )
    assert engine.snapshot("XRP-EUR", now=304.0)["fresh"] is True
    assert engine.snapshot("XRP-EUR", now=306.0)["fresh"] is False
