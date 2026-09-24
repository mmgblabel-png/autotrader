from __future__ import annotations

import json
from decimal import Decimal

import pytest

from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter, BitpandaFusionError


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def fake_opener(captured, payload):
    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(payload)
    return opener


def test_authenticate_uses_documented_header_and_redacts_key():
    captured = {}
    adapter = BitpandaFusionAdapter(
        api_key="secret-value",
        opener=fake_opener(captured, [{"asset": "EUR", "available": "10"}]),
    )
    result = adapter.authenticate()
    assert result["authenticated"] is True
    assert result["balance_entries"] == 1
    request = captured["request"]
    assert request.full_url == "https://api.fusion.bitpanda.com/v1/account/balances"
    assert request.get_header("X-api-key") == "secret-value"
    assert "secret-value" not in json.dumps(result)
    assert "10" not in json.dumps(result)


def test_missing_key_fails_closed_without_network_call():
    called = False

    def opener(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be called")

    adapter = BitpandaFusionAdapter(api_key="", opener=opener)
    with pytest.raises(BitpandaFusionError) as exc:
        adapter.authenticate()
    assert exc.value.category == "credentials_missing"
    assert called is False


def test_shadow_validate_builds_official_limit_payload():
    adapter = BitpandaFusionAdapter(api_key="placeholder")
    payload = adapter.shadow_validate_order(
        pair="btc-eur", side="buy", order_type="limit", quantity=Decimal("0.001"), limit_price=Decimal("50000")
    )
    assert payload == {
        "pair": "BTC-EUR",
        "side": "Buy",
        "type": "Limit",
        "quantity": "0.001",
        "limitPrice": "50000",
    }


def test_shadow_order_does_not_send_network_request(monkeypatch):
    monkeypatch.setenv("BITPANDA_FUSION_DRY_RUN", "true")
    called = False

    def opener(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("shadow order must not call the network")

    adapter = BitpandaFusionAdapter(api_key="placeholder", opener=opener)
    result = adapter.place_market_order("BTC-EUR", "buy", amount=Decimal("10"))
    assert result["status"] == "SHADOW"
    assert result["would_place"]["pair"] == "BTC-EUR"
    assert result["would_place"]["amount"] == "10"
    assert called is False


def test_live_order_path_is_blocked_even_when_live_mode_is_requested(monkeypatch):
    monkeypatch.setenv("BITPANDA_FUSION_DRY_RUN", "false")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("BITPANDA_FUSION_LIVE_ORDERS_ENABLED", "false")
    adapter = BitpandaFusionAdapter(api_key="placeholder")
    result = adapter.place_market_order("BTC-EUR", "buy", amount=Decimal("10"))
    assert result["status"] == "SHADOW"
    assert result["live_orders_sent"] is False


def test_invalid_quantity_and_amount_are_rejected():
    adapter = BitpandaFusionAdapter(api_key="placeholder")
    with pytest.raises(BitpandaFusionError, match="exactly one"):
        adapter.shadow_validate_order(pair="BTC-EUR", side="buy", order_type="market", quantity="1", amount="10")


def test_list_orders_builds_query(monkeypatch):
    captured = {}
    adapter = BitpandaFusionAdapter(
        api_key="placeholder", opener=fake_opener(captured, {"data": []})
    )
    result = adapter.list_orders(status="open", pair="BTC-EUR", limit=10)
    assert result == {"data": []}
    assert "status=open" in captured["request"].full_url
    assert "pair=BTC-EUR" in captured["request"].full_url
    assert "limit=10" in captured["request"].full_url
