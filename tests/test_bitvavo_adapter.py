from decimal import Decimal

import pytest

from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError


def test_bitvavo_defaults_to_shadow(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "true")
    adapter = BitvavoAdapter()
    monkeypatch.setattr(adapter, "ticker_price", lambda market: Decimal("60000"))
    result = adapter.place_limit_order("BTC-EUR", "buy", Decimal("0.0001"), Decimal("60000"), "bvo-order-1234567890123456")
    assert result["status"] == "SHADOW"
    assert result["would_place"]["market"] == "BTC-EUR"


def test_bitvavo_live_gate_rejects(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("BITVAVO_DRY_RUN", "false")
    monkeypatch.setenv("EMERGENCY_STOP", "true")
    adapter = BitvavoAdapter()
    monkeypatch.setattr(adapter, "ticker_price", lambda market: Decimal("60000"))
    with pytest.raises(BitvavoError, match="adapter|gates"):
        adapter.place_market_order("BTC-EUR", "buy", Decimal("0.0001"), "bvo-live-1234567890123456")
