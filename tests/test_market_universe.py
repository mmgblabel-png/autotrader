from decimal import Decimal

from autotrader.connectors.coinbase_advanced import CoinbaseTopOfBook
from autotrader.core.market_universe import MultiExchangeMarketUniverse, quote_kind


class FakeBitvavo:
    def markets(self):
        return [
            {"market": "BTC-EUR", "base": "BTC", "quote": "EUR", "status": "trading", "orderTypes": ["limit"], "minOrderInBaseAsset": "0.0001", "minOrderInQuoteAsset": "5"},
            {"market": "ETH-BTC", "base": "ETH", "quote": "BTC", "status": "trading", "orderTypes": ["limit"], "minOrderInBaseAsset": "0.001", "minOrderInQuoteAsset": "0.0001"},
            {"market": "SOL-USDC", "base": "SOL", "quote": "USDC", "status": "trading", "orderTypes": ["limit"], "minOrderInBaseAsset": "0.1", "minOrderInQuoteAsset": "5"},
            {"market": "USDC-EUR", "base": "USDC", "quote": "EUR", "status": "trading", "orderTypes": ["limit"], "minOrderInBaseAsset": "5", "minOrderInQuoteAsset": "5"},
        ]

    def ticker_books(self):
        return {
            "BTC-EUR": {"market": "BTC-EUR", "bid": Decimal("70000"), "ask": Decimal("70010"), "bid_size": Decimal("1"), "ask_size": Decimal("1")},
            "ETH-BTC": {"market": "ETH-BTC", "bid": Decimal("0.05"), "ask": Decimal("0.0501"), "bid_size": Decimal("10"), "ask_size": Decimal("10")},
            "SOL-USDC": {"market": "SOL-USDC", "bid": Decimal("100"), "ask": Decimal("100.1"), "bid_size": Decimal("100"), "ask_size": Decimal("100")},
            "USDC-EUR": {"market": "USDC-EUR", "bid": Decimal("0.99"), "ask": Decimal("1.00"), "bid_size": Decimal("10000"), "ask_size": Decimal("10000")},
        }


class FakeCoinbase:
    def list_spot_products(self):
        return [
            {"product_id": "BTC-EUR", "base": "BTC", "quote": "EUR", "tradable": True, "product_type": "SPOT", "price": "70005", "volume_24h": "50"},
            {"product_id": "ETH-BTC", "base": "ETH", "quote": "BTC", "tradable": True, "product_type": "SPOT", "price": "0.05005", "volume_24h": "1000"},
            {"product_id": "SOL-USDC", "base": "SOL", "quote": "USDC", "tradable": True, "product_type": "SPOT", "price": "100.05", "volume_24h": "5000"},
        ]

    def top_of_book(self, market):
        rows = {
            "BTC-EUR": CoinbaseTopOfBook("BTC-EUR", Decimal("70000"), Decimal("1"), Decimal("70010"), Decimal("1")),
            "ETH-BTC": CoinbaseTopOfBook("ETH-BTC", Decimal("0.05"), Decimal("10"), Decimal("0.0501"), Decimal("10")),
            "SOL-USDC": CoinbaseTopOfBook("SOL-USDC", Decimal("100"), Decimal("100"), Decimal("100.1"), Decimal("100")),
        }
        return rows[market]


def test_quote_kind_classifies_crypto_and_stable_quotes():
    assert quote_kind("EUR") == "fiat"
    assert quote_kind("USDC") == "stablecoin"
    assert quote_kind("BTC") == "crypto"


def test_full_universe_includes_crypto_crypto_and_bridges_to_eur():
    universe = MultiExchangeMarketUniverse(
        FakeBitvavo(),
        FakeCoinbase(),
        {
            "coinbase_book_batch_size": 10,
            "max_bridge_hops": 3,
            "min_top_depth_eur": 25,
            "max_spread_bps": 50,
        },
    )
    universe.refresh()

    status = universe.status()
    assert status["read_only"] is True
    assert status["live_orders_sent"] is False
    assert status["bitvavo"]["all"] == 4
    assert status["coinbase"]["all"] == 3
    assert status["bitvavo"]["crypto_crypto"] == 2
    assert status["coinbase"]["crypto_crypto"] == 2
    assert status["exact_cross_venue_overlap"] == 3
    assert status["overlap_crypto_crypto"] == 2

    crypto = universe.markets(pair_type="crypto_crypto", tradable_only=True, limit=20)
    names = {(row["venue"], row["market"]) for row in crypto["rows"]}
    assert ("bitvavo", "ETH-BTC") in names
    assert ("coinbase", "ETH-BTC") in names
    eth_btc = next(
        row for row in crypto["rows"]
        if row["venue"] == "bitvavo" and row["market"] == "ETH-BTC"
    )
    assert eth_btc["quote_to_eur"] is not None
    assert eth_btc["top_depth_eur"] is not None
    assert eth_btc["pair_type"] == "crypto_crypto"
    assert eth_btc["live_execution_supported_now"] is False


def test_universe_overlap_includes_non_eur_pairs():
    universe = MultiExchangeMarketUniverse(FakeBitvavo(), FakeCoinbase(), {"coinbase_book_batch_size": 10})
    universe.refresh()
    overlap = universe.overlaps(limit=20)
    markets = {row["market"] for row in overlap["rows"]}
    assert {"BTC-EUR", "ETH-BTC", "SOL-USDC"} <= markets
    assert overlap["live_orders_sent"] is False


class BrokenCoinbase(FakeCoinbase):
    def list_spot_products(self):
        raise RuntimeError("coinbase unavailable")


class BrokenBitvavo(FakeBitvavo):
    def markets(self):
        raise RuntimeError("bitvavo unavailable")


def test_coinbase_failure_does_not_zero_bitvavo_universe():
    universe = MultiExchangeMarketUniverse(
        FakeBitvavo(),
        BrokenCoinbase(),
        {"coinbase_book_batch_size": 10},
    )
    universe.refresh()
    status = universe.status()
    assert status["bitvavo"]["tradable"] == 4
    assert status["coinbase"]["tradable"] == 0
    assert "coinbase" in status["venue_errors"]
    assert status["live_orders_sent"] is False


def test_bitvavo_failure_does_not_zero_coinbase_catalogue():
    universe = MultiExchangeMarketUniverse(
        BrokenBitvavo(),
        FakeCoinbase(),
        {"coinbase_book_batch_size": 10},
    )
    universe.refresh()
    status = universe.status()
    assert status["bitvavo"]["tradable"] == 0
    assert status["coinbase"]["tradable"] == 3
    assert "bitvavo" in status["venue_errors"]
    # Without the Bitvavo conversion graph, crypto-quoted rows remain
    # discoverable but are not falsely valued as EUR.
    eth_btc = next(
        row for row in universe.markets(venue="coinbase")["rows"]
        if row["market"] == "ETH-BTC"
    )
    assert eth_btc["quote_to_eur"] is None
    assert eth_btc["live_execution_supported_now"] is False
