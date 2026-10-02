from decimal import Decimal
import asyncio

import pytest

from autotrader.connectors.binance_spot import BinanceSpotAdapter, BinanceSpotError
from autotrader.connectors.polymarket import PolymarketAdapter, PolymarketError
from autotrader.connectors.exchange import CONNECTOR_REGISTRY, get_connector



class _AcceptingGateway:
    class _Decision:
        accepted = True
        reason = "accepted"

    def evaluate(self, request, *, armed=False):
        return self._Decision()

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
    with pytest.raises(BinanceSpotError, match="armed|adapter|gates"):
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
    with pytest.raises(PolymarketError, match="armed|adapter|gates"):
        asyncio.run(adapter.place_market_order("token-123", "BUY", Decimal("5"), Decimal("0.50"), "poly-live-1234567890123456"))


def test_legacy_fake_connectors_are_not_runtime_registered():
    assert "binance" not in CONNECTOR_REGISTRY
    assert "kraken" not in CONNECTOR_REGISTRY
    assert "coinbase" not in CONNECTOR_REGISTRY
    assert get_connector("binance") is None
    assert get_connector("kraken") is None
    assert get_connector("coinbase") is None


def test_binance_live_requires_venue_specific_enable(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("BINANCE_DRY_RUN", "false")
    monkeypatch.setenv("BINANCE_LIVE_ORDERS_ENABLED", "false")
    monkeypatch.setenv("LIVE_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("LIVE_EXECUTION_ADAPTER_INSTALLED", "true")
    monkeypatch.setenv("EMERGENCY_STOP", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDERS")
    monkeypatch.setenv("BITVAVO_LIVE_TRADING", "true")
    adapter = BinanceSpotAdapter(gateway=_AcceptingGateway())
    monkeypatch.setattr(adapter, "ticker_price", lambda symbol: Decimal("100"))
    with pytest.raises(BinanceSpotError, match="explicitly enabled"):
        adapter.place_market_order("BTCUSDT", "BUY", Decimal("0.01"), "binance-explicit-gate-123456")


def test_polymarket_live_requires_venue_specific_enable(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("POLYMARKET_DRY_RUN", "false")
    monkeypatch.setenv("POLYMARKET_LIVE_ORDERS_ENABLED", "false")
    monkeypatch.setenv("LIVE_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("LIVE_EXECUTION_ADAPTER_INSTALLED", "true")
    monkeypatch.setenv("EMERGENCY_STOP", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDERS")
    monkeypatch.setenv("BITVAVO_LIVE_TRADING", "true")
    adapter = PolymarketAdapter(gateway=_AcceptingGateway())
    with pytest.raises(PolymarketError, match="explicitly enabled"):
        asyncio.run(adapter.place_market_order(
            "token-123", "BUY", Decimal("5"), Decimal("0.50"), "poly-explicit-gate-123456"
        ))
