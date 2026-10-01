from decimal import Decimal

import pytest

from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError
from autotrader.core.order_journal import OrderJournal


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
    with pytest.raises(BitvavoError, match="armed|adapter|gates"):
        adapter.place_market_order("BTC-EUR", "buy", Decimal("0.0001"), "9b83bc1e-177f-4b87-82f3-cbd0fbca5ef1")


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


def test_live_rule_normalization_is_side_conservative(monkeypatch, tmp_path):
    adapter = BitvavoAdapter(journal=OrderJournal(str(tmp_path / "journal.sqlite3")))
    monkeypatch.setattr(
        adapter,
        "markets",
        lambda market=None: [{
            "status": "trading",
            "orderTypes": ["limit"],
            "quantityDecimals": 4,
            "tickSize": "0.05",
            "minOrderInBaseAsset": "0.0001",
            "minOrderInQuoteAsset": "5",
        }],
    )
    monkeypatch.setattr(adapter, "ticker_price", lambda market: Decimal("74100"))

    amount_buy, price_buy = adapter._validate_order_rules(
        "BTC-EUR", Decimal("0.00019999"), Decimal("74289.63"), "limit", "buy"
    )
    amount_sell, price_sell = adapter._validate_order_rules(
        "BTC-EUR", Decimal("0.00019999"), Decimal("74289.63"), "limit", "sell"
    )

    assert amount_buy == Decimal("0.0001")
    assert amount_sell == Decimal("0.0001")
    assert price_buy == Decimal("74289.60")
    assert price_sell == Decimal("74289.65")


def test_ticker_books_parses_bulk_market_books(monkeypatch):
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    monkeypatch.setattr(
        adapter,
        "_public_request",
        lambda endpoint, query=None: [
            {"market": "BTC-EUR", "bid": "73000", "ask": "73010", "bidSize": "1.2", "askSize": "1.1"},
            {"market": "ETH-BTC", "bid": "0.032", "ask": "0.0321", "bidSize": "20", "askSize": "18"},
        ],
    )
    books = adapter.ticker_books()
    assert books["BTC-EUR"]["bid"] == Decimal("73000")
    assert books["ETH-BTC"]["ask"] == Decimal("0.0321")
    assert books["ETH-BTC"]["bid_size"] == Decimal("20")


def test_ticker_books_skips_invalid_decimal_rows(monkeypatch):
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    monkeypatch.setattr(
        adapter,
        "_public_request",
        lambda endpoint, query=None: [
            {"market": "BROKEN-EUR", "bid": "", "ask": "1", "bidSize": "1", "askSize": "1"},
            {"market": "NONE-EUR", "bid": None, "ask": "1", "bidSize": "1", "askSize": "1"},
            {"market": "NAN-EUR", "bid": "NaN", "ask": "1", "bidSize": "1", "askSize": "1"},
            {"market": "BTC-EUR", "bid": "73000", "ask": "73010", "bidSize": "1.2", "askSize": "1.1"},
        ],
    )
    books = adapter.ticker_books()
    assert list(books) == ["BTC-EUR"]
    assert books["BTC-EUR"]["bid"] == Decimal("73000")


def test_public_candles_are_normalized_and_sorted(monkeypatch):
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    calls = []

    def fake_public(endpoint, query=None):
        calls.append((endpoint, dict(query or {})))
        return [
            [2000, "2", "3", "1", "2.5", "10"],
            [1000, "1", "2", "0.5", "1.5", "20"],
            [3000, "", "3", "1", "2", "10"],
        ]

    monkeypatch.setattr(adapter, "_public_request", fake_public)
    rows = adapter.candles("ETH-BTC", interval="1m", limit=120)
    assert calls == [("/ETH-BTC/candles", {"interval": "1m", "limit": "120"})]
    assert [row["timestamp"] for row in rows] == [1000, 2000]
    assert rows[0]["close"] == Decimal("1.5")
