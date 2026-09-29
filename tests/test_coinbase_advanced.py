from decimal import Decimal

from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData


def test_coinbase_public_book_parser(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    monkeypatch.setattr(
        client,
        "_get",
        lambda path, params=None: {
            "pricebook": {
                "product_id": "BTC-EUR",
                "bids": [{"price": "70000.00", "size": "0.25"}],
                "asks": [{"price": "70010.00", "size": "0.30"}],
            }
        },
    )
    book = client.top_of_book("btc/eur")
    assert book.product_id == "BTC-EUR"
    assert book.bid_price == Decimal("70000.00")
    assert book.ask_price == Decimal("70010.00")
    assert book.bid_size == Decimal("0.25")
    assert book.ask_size == Decimal("0.30")
    assert book.mid_price == Decimal("70005.00")
