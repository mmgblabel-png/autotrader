from decimal import Decimal
import io
import urllib.error

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


def test_private_delete_with_query_signs_empty_body(monkeypatch):
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    captured = {}

    def fake_signature(secret, timestamp, method, endpoint, body_text):
        captured.update(
            secret=secret,
            timestamp=timestamp,
            method=method,
            endpoint=endpoint,
            body_text=body_text,
        )
        return "signature"

    class DummyResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"orderId":"11111111-1111-1111-1111-111111111111"}'

    def fake_urlopen(request, timeout=None):
        captured["request_data"] = request.data
        captured["url"] = request.full_url
        return DummyResponse()

    monkeypatch.setattr(adapter, "_create_signature", fake_signature)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter._private_request(
        "DELETE",
        "/order",
        query={
            "market": "BTC-EUR",
            "orderId": "11111111-1111-1111-1111-111111111111",
            "operatorId": "1",
        },
    )

    assert captured["method"] == "DELETE"
    assert captured["body_text"] == ""
    assert captured["request_data"] is None
    assert captured["endpoint"].startswith("/order?market=BTC-EUR&orderId=")
    assert captured["url"].startswith("https://api.bitvavo.com/v2/order?market=BTC-EUR&orderId=")


def test_bitvavo_error_309_is_classified_as_invalid_signature(monkeypatch):
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    payload = b'{"errorCode":309,"error":"Your signature is invalid."}'

    def fake_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://api.bitvavo.com/v2/order",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(BitvavoError) as exc:
        adapter._private_request(
            "DELETE",
            "/order",
            query={"market": "BTC-EUR", "orderId": "11111111-1111-1111-1111-111111111111", "operatorId": "1"},
        )
    assert exc.value.error_code == 309
    assert exc.value.category == "invalid_signature"


def test_public_request_retries_transient_network_failure(monkeypatch):
    monkeypatch.setenv("BITVAVO_PUBLIC_READ_ATTEMPTS", "2")
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    calls = {"count": 0}

    class DummyResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"market":"BTC-EUR","price":"73452.01"}'

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError("transient ssl failure")
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    assert adapter.ticker_price("BTC-EUR") == Decimal("73452.01")
    assert calls["count"] == 2


def test_ioc_limit_order_sends_non_post_only_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "false")
    monkeypatch.setenv("LIVE_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("LIVE_EXECUTION_ADAPTER_INSTALLED", "true")
    monkeypatch.setenv("BITVAVO_LIVE_TRADING", "true")
    monkeypatch.setenv("EMERGENCY_STOP", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDERS")
    adapter = BitvavoAdapter(
        api_key="key",
        api_secret="secret",
        journal=OrderJournal(str(tmp_path / "ioc.sqlite3")),
        is_armed=lambda: True,
    )
    adapter.dry_run = False
    monkeypatch.setattr(
        adapter,
        "markets",
        lambda market=None: [{
            "market": market or "AXS-EUR",
            "status": "trading",
            "orderTypes": ["limit", "market"],
            "quantityDecimals": 8,
            "tickSize": "0.0001",
            "minOrderInBaseAsset": "0.1",
            "minOrderInQuoteAsset": "5",
        }],
    )
    monkeypatch.setattr(adapter, "ticker_price", lambda market: Decimal("1.1110"))
    seen = {}

    def fake_private(method, endpoint, body=None, query=None):
        seen.update(method=method, endpoint=endpoint, body=body, query=query)
        return {
            "orderId": "11111111-1111-1111-1111-111111111111",
            "clientOrderId": body["clientOrderId"],
            "status": "canceled",
            "filledAmount": "0",
            "fills": [],
        }

    monkeypatch.setattr(adapter, "_private_request", fake_private)
    result = adapter.place_limit_order(
        "AXS-EUR",
        "buy",
        Decimal("5.39"),
        Decimal("1.1123"),
        "22222222-2222-2222-2222-222222222222",
        time_in_force="IOC",
        post_only=False,
    )

    assert result["status"] == "canceled"
    assert seen["method"] == "POST"
    assert seen["endpoint"] == "/order"
    assert seen["body"]["orderType"] == "limit"
    assert seen["body"]["timeInForce"] == "IOC"
    assert seen["body"]["postOnly"] is False


def test_ioc_limit_rejects_post_only_combination(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "true")
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    with pytest.raises(BitvavoError, match="cannot be post-only"):
        adapter._place(
            "AXS-EUR",
            "buy",
            Decimal("5.4"),
            Decimal("1.11"),
            "33333333-3333-3333-3333-333333333333",
            1,
            "limit",
            time_in_force="IOC",
            post_only=True,
        )


def test_private_get_retries_transient_500(monkeypatch):
    monkeypatch.setenv("BITVAVO_PRIVATE_READ_ATTEMPTS", "2")
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    calls = {"count": 0}
    sleeps = []

    class DummyResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"balances":[],"fees":{}}'

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                url="https://api.bitvavo.com/v2/account",
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=io.BytesIO(b'{"errorCode":500,"error":"temporary"}'),
            )
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    result = adapter._private_request("GET", "/account")
    assert result == {"balances": [], "fees": {}}
    assert calls["count"] == 2
    assert sleeps == [0.5]


def test_private_get_429_respects_short_reset_header(monkeypatch):
    monkeypatch.setenv("BITVAVO_PRIVATE_READ_ATTEMPTS", "2")
    monkeypatch.setenv("BITVAVO_PRIVATE_READ_MAX_WAIT_SECONDS", "5")
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    calls = {"count": 0}
    sleeps = []
    now = 1_000.0

    class DummyResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'[]'

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                url="https://api.bitvavo.com/v2/ordersOpen",
                code=429,
                msg="Too Many Requests",
                hdrs={"bitvavo-ratelimit-resetat": str(int((now + 0.75) * 1000))},
                fp=io.BytesIO(b'{"errorCode":105,"error":"rate limit"}'),
            )
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.time", lambda: now)
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    result = adapter._private_request("GET", "/ordersOpen")
    assert result == []
    assert calls["count"] == 2
    assert sleeps == [0.75]


def test_private_mutation_is_never_retried_after_5xx(monkeypatch):
    monkeypatch.setenv("BITVAVO_PRIVATE_READ_ATTEMPTS", "4")
    adapter = BitvavoAdapter(api_key="key", api_secret="secret")
    calls = {"count": 0}

    def failing(*args, **kwargs):
        calls["count"] += 1
        raise urllib.error.HTTPError(
            url="https://api.bitvavo.com/v2/order",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=io.BytesIO(b'{"errorCode":109,"error":"timeout"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", failing)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: pytest.fail("mutation retry attempted"))

    with pytest.raises(BitvavoError):
        adapter._private_request(
            "POST",
            "/order",
            {"market": "BTC-EUR", "side": "buy", "orderType": "market", "amount": "0.0001"},
        )
    assert calls["count"] == 1
