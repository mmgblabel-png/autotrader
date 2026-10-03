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



def test_coinbase_spot_market_preview_payload(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    calls = []

    def fake_auth(method, path, payload=None):
        calls.append((method, path, payload))
        return {
            "preview_id": "preview-123",
            "commission_total": "0.01",
            "est_average_filled_price": "70000",
        }

    monkeypatch.setattr(client, "_auth_request", fake_auth)
    preview = client.preview_spot_market_order(
        product_id="btc/eur",
        side="BUY",
        quote_size="3.00",
    )
    assert preview["preview_id"] == "preview-123"
    method, path, payload = calls[0]
    assert method == "POST"
    assert path == client.ORDER_PREVIEW_PATH
    assert payload["product_id"] == "BTC-EUR"
    assert payload["side"] == "BUY"
    assert payload["order_configuration"]["market_market_ioc"]["quote_size"] == "3.00"


def test_coinbase_create_spot_market_order_requires_success(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    calls = []

    def fake_auth(method, path, payload=None):
        calls.append((method, path, payload))
        return {
            "success": True,
            "success_response": {"order_id": "oid-1"},
        }

    monkeypatch.setattr(client, "_auth_request", fake_auth)
    result = client.create_spot_market_order(
        client_order_id="cid-1",
        product_id="BTC-EUR",
        side="SELL",
        base_size="0.00002",
        preview_id="preview-1",
    )
    assert result["success"] is True
    payload = calls[0][2]
    assert payload["client_order_id"] == "cid-1"
    assert payload["preview_id"] == "preview-1"
    assert payload["order_configuration"]["market_market_ioc"]["base_size"] == "0.00002"
