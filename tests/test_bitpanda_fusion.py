from __future__ import annotations

import json
import os
from contextlib import contextmanager
from decimal import Decimal

import pytest

from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter, BitpandaFusionError


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
        self.request = None

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


def test_live_order_path_is_blocked(monkeypatch):
    monkeypatch.setenv("BITPANDA_FUSION_DRY_RUN", "false")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    adapter = BitpandaFusionAdapter(api_key="placeholder")
    with pytest.raises(BitpandaFusionError) as exc:
        adapter.place_market_order("BTC-EUR", "buy", Decimal("0.001"))
    assert exc.value.category == "live_orders_blocked"


def test_shadow_order_returns_proposal(monkeypatch):
    monkeypatch.setenv("BITPANDA_FUSION_DRY_RUN", "true")
    adapter = BitpandaFusionAdapter(api_key="placeholder")
    result = adapter.place_limit_order("BTC-EUR", "buy", Decimal("0.001"), Decimal("50000"))
    assert result["status"] == "SHADOW"
    assert result["would_place"]["venue"] == "bitpanda_fusion"
