from decimal import Decimal

import pytest

from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError


def test_bitvavo_defaults_to_shadow(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "true")
    adapter = BitvavoAdapter()
    monkeypatch.setattr(adapter, "ticker_price", lambda market: Decimal("60000"))
    monkeypatch.setattr(adapter, "markets", lambda market=None: [{"status": "trading", "orderTypes": ["limit", "market"], "quantityDecimals": 6, "tickSize": "0.01", "minOrderInBaseAsset": "0.00001", "minOrderInQuoteAsset": "5"}])
    result = adapter.place_limit_order("BTC-EUR", "buy", Decimal("0.0001"), Decimal("60000"), "2be7d0df-d8dc-7b93-a550-6f3b3f3b393e")
    assert result["status"] == "SHADOW"
    assert result["would_place"]["market"] == "BTC-EUR"


def test_bitvavo_live_gate_rejects(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "false")
    monkeypatch.setenv("EMERGENCY_STOP", "true")
    adapter = BitvavoAdapter()
    monkeypatch.setattr(adapter, "ticker_price", lambda market: Decimal("60000"))
    monkeypatch.setattr(adapter, "markets", lambda market=None: [{"status": "trading", "orderTypes": ["limit", "market"], "quantityDecimals": 6, "tickSize": "0.01", "minOrderInBaseAsset": "0.00001", "minOrderInQuoteAsset": "5"}])
    with pytest.raises(BitvavoError, match="adapter|gates"):
        adapter.place_market_order("BTC-EUR", "buy", Decimal("0.0001"), "2be7d0df-d8dc-7b93-a550-6f3b3f3b393e")


def test_signature_matches_bitvavo_documented_example():
    body = '{"market":"BTC-EUR","side":"buy","price":"5000","amount":"1.23","orderType":"limit"}'
    signature = BitvavoAdapter._create_signature(
        "bitvavo",
        "1548172481125",
        "POST",
        "/order",
        body,
    )
    assert signature == "44d022723a20973a18f7ee97398b9fdd405d2d019c8d39e24b8cc0dcb39ca016"


def test_signature_includes_private_get_query_parameters():
    signature = BitvavoAdapter._create_signature(
        "bitvavo",
        "1548172481125",
        "GET",
        "/balance?symbol=EUR",
        "",
    )
    assert signature == "353597189269861adae42e436d04f24b098fd6924d293dc49792af6590b539ee"


def test_markets_accepts_single_market_object(monkeypatch):
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    payload = {
        "market": "BTC-EUR",
        "status": "trading",
        "base": "BTC",
        "quote": "EUR",
        "minOrderInBaseAsset": "0.0001",
        "minOrderInQuoteAsset": "5",
        "quantityDecimals": "4",
        "notionalDecimals": "2",
        "tickSize": "0.01",
        "orderTypes": ["market", "limit"],
    }
    monkeypatch.setattr(adapter, "_public_request", lambda endpoint, query=None: payload)
    assert adapter.markets("BTC-EUR") == [payload]
    assert adapter._market_rules("BTC-EUR")["market"] == "BTC-EUR"


def test_ticker_price_accepts_list_response(monkeypatch):
    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'[{"market":"BTC-EUR","price":"73452.01"}]'

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: DummyResponse())
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    assert adapter.ticker_price("BTC-EUR") == Decimal("73452.01")


def test_get_order_uses_official_query_route(monkeypatch):
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    seen = {}
    def fake(method, endpoint, body=None, query=None):
        seen.update(method=method, endpoint=endpoint, query=query)
        return {"status": "filled", "fills": []}
    monkeypatch.setattr(adapter, "_private_request", fake)
    adapter.get_order("BTC-EUR", order_id="11111111-1111-1111-1111-111111111111")
    assert seen == {
        "method": "GET",
        "endpoint": "/order",
        "query": {
            "market": "BTC-EUR",
            "orderId": "11111111-1111-1111-1111-111111111111",
        },
    }


def test_cancel_order_uses_official_query_route(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "false")
    monkeypatch.setenv("BITVAVO_OPERATOR_ID", "1")
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    adapter.dry_run = False
    seen = {}
    def fake(method, endpoint, body=None, query=None):
        seen.update(method=method, endpoint=endpoint, query=query)
        return {"orderId": query["orderId"]}
    monkeypatch.setattr(adapter, "_private_request", fake)
    adapter.cancel_order("BTC-EUR", "11111111-1111-1111-1111-111111111111")
    assert seen == {
        "method": "DELETE",
        "endpoint": "/order",
        "query": {
            "market": "BTC-EUR",
            "orderId": "11111111-1111-1111-1111-111111111111",
            "operatorId": "1",
        },
    }
