from __future__ import annotations

from autotrader.core.market_feed import BitpandaFusionMarketFeed


class FakeAdapter:
    def __init__(self, pairs, tickers):
        self.pairs = pairs
        self.tickers = tickers

    def get_pairs(self, *, pair=None):
        return self.pairs

    def get_tickers(self, *, pair=None):
        return self.tickers


def test_btc_eur_feed_validates_pair_and_ticker():
    feed = BitpandaFusionMarketFeed(
        FakeAdapter(
            [{"pair": "BTC-EUR"}],
            [{"pair": "BTC-EUR", "price": "61500.00", "high": "62000", "low": "60000", "volume": "250000"}],
        )
    )
    result = feed.fetch_once()
    assert result["status"] == "live"
    assert result["pair"] == "BTC-EUR"
    assert result["price"] == "61500.00"
    assert result["orders_enabled"] is False


def test_feed_fails_closed_when_pair_is_missing():
    feed = BitpandaFusionMarketFeed(FakeAdapter([], []))
    result = feed.fetch_once()
    assert result["status"] == "unavailable"
    assert result["stale"] is True
    assert result["price"] is None
    assert result["orders_enabled"] is False


def test_feed_rejects_non_positive_price():
    feed = BitpandaFusionMarketFeed(
        FakeAdapter([{"pair": "BTC-EUR"}], [{"pair": "BTC-EUR", "price": "0"}])
    )
    result = feed.fetch_once()
    assert result["status"] == "unavailable"
    assert result["error"] == "invalid_price"
