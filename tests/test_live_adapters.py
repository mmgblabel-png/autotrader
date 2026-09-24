from decimal import Decimal
import asyncio

import pytest

from autotrader.connectors.binance_spot import BinanceSpotAdapter, BinanceSpotError
from autotrader.connectors.polymarket import PolymarketAdapter, PolymarketError


def test_binance_adapter_defaults_to_shadow(monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    adapter = BinanceSpotAdapter()
    monkeypatch.setattr(adapter, "ticker_price", lambda symbol: Decimal("100"))
    result = adapter.place_limit_order("BTCUSDT", "BUY", Decimal("0.01"), Decimal("100"), "test-order-1234567890123456")
    assert result["status"] == "SHADOW"


def test_binance_live_gate_rejects(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("BINANCE_DRY_RUN", "false")
    monkeypatch.setenv("EMERGENCY_STOP", "true")
    adapter = BinanceSpotAdapter()
    monkeypatch.setattr(adapter, "ticker_price", lambda symbol: Decimal("100"))
    with pytest.raises(BinanceSpotError, match="adapter|gates"):
        adapter.place_market_order("BTCUSDT", "BUY", Decimal("0.01"), "live-order-1234567890123456")


def test_polymarket_defaults_to_shadow(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "shadow")
    monkeypatch.setenv("POLYMARKET_DRY_RUN", "true")
    adapter = PolymarketAdapter()
    result = asyncio.run(adapter.place_market_order("token-123", "BUY", Decimal("5"), Decimal("0.50"), "poly-order-1234567890123456"))
    assert result["status"] == "SHADOW"


def test_polymarket_live_gate_rejects(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("POLYMARKET_DRY_RUN", "false")
    monkeypatch.setenv("EMERGENCY_STOP", "true")
    adapter = PolymarketAdapter()
    with pytest.raises(PolymarketError, match="adapter|gates"):
        asyncio.run(adapter.place_market_order("token-123", "BUY", Decimal("5"), Decimal("0.50"), "poly-live-1234567890123456"))
