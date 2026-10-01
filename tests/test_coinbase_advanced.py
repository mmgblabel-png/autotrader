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


def test_coinbase_lists_all_spot_products_with_pagination(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    calls = []
    pages = {
        None: {
            "products": [
                {"product_id": "BTC-USD", "product_type": "SPOT"},
                {"product_id": "ETH-BTC", "product_type": "SPOT"},
            ],
            "cursor": "next-1",
            "has_next": True,
        },
        "next-1": {
            "products": [
                {"product_id": "SOL-USDC", "product_type": "SPOT"},
                {"product_id": "BTC-USD", "product_type": "SPOT"},
                {"product_id": "BTC-PERP", "product_type": "FUTURE"},
            ],
            "has_next": False,
        },
    }

    def fake_get(path, params=None):
        calls.append((path, dict(params or {})))
        return pages[(params or {}).get("cursor")]

    monkeypatch.setattr(client, "_get", fake_get)
    rows = client.list_spot_products(page_size=2, max_pages=5)

    assert [row["product_id"] for row in rows] == ["BTC-USD", "ETH-BTC", "SOL-USDC"]
    assert any(row["quote"] == "BTC" for row in rows)
    assert any(row["quote"] == "USDC" for row in rows)
    assert calls[0][1]["product_type"] == "SPOT"
    assert calls[1][1]["cursor"] == "next-1"
