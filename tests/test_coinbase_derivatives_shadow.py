from autotrader.connectors.coinbase_derivatives import (
    CoinbaseDerivativesGateway,
    CoinbaseDerivativesTicker,
)
from autotrader.core.coinbase_derivatives_shadow import CoinbaseDerivativesShadowScanner


def test_derivatives_gateway_lists_futures(monkeypatch):
    client = CoinbaseDerivativesGateway()
    monkeypatch.setattr(
        client,
        "_request",
        lambda path, **kwargs: [
            {
                "instrument_name": "BTC-PERPETUAL",
                "kind": "future",
                "is_active": True,
                "settlement_period": "perpetual",
            }
        ],
    )
    rows = client.list_futures(currency="any")
    assert rows[0]["instrument_name"] == "BTC-PERPETUAL"


def test_derivatives_ticker_spread_bps(monkeypatch):
    client = CoinbaseDerivativesGateway()
    monkeypatch.setattr(
        client,
        "_request",
        lambda path, **kwargs: {
            "instrument_name": "BTC-PERPETUAL",
            "mark_price": 100.0,
            "index_price": 100.0,
            "best_bid_price": 99.9,
            "best_ask_price": 100.1,
            "open_interest": 1000,
            "current_funding": 0.0001,
            "stats": {"volume_usd": 1_000_000, "price_change": 1.2},
        },
    )
    ticker = client.ticker("BTC-PERPETUAL")
    assert round(ticker.spread_bps, 2) == 20.0
    assert ticker.volume_usd == 1_000_000


def test_derivatives_shadow_scanner_never_places_orders():
    class FakeClient:
        def list_futures(self, *, currency="any"):
            return [
                {
                    "instrument_name": "BTC-PERPETUAL",
                    "is_active": True,
                    "settlement_period": "perpetual",
                    "max_leverage": 10,
                    "contract_size": 1,
                }
            ]

        def ticker(self, instrument_name):
            return CoinbaseDerivativesTicker(
                instrument_name=instrument_name,
                mark_price=100.0,
                index_price=100.0,
                best_bid_price=99.99,
                best_ask_price=100.01,
                open_interest=5000,
                volume_usd=5_000_000,
                price_change_pct=1.5,
                current_funding=0.0001,
            )

        def auth_probe(self):
            return {
                "authenticated": True,
                "risk_profile_readable": True,
                "positions_readable": True,
                "position_count": 0,
                "error_category": None,
                "order_sent": False,
            }

    scanner = CoinbaseDerivativesShadowScanner(
        {
            "enabled": True,
            "max_instruments": 8,
            "min_volume_usd": 1000,
            "max_spread_bps": 50,
            "top_n": 5,
        },
        client=FakeClient(),
    )
    status = scanner.tick()
    assert status["mode"] == "shadow_only"
    assert status["live_orders_sent"] is False
    assert status["order_capability_implemented"] is False
    assert status["candidate_count"] == 1
    assert status["candidates"][0]["instrument"] == "BTC-PERPETUAL"
    assert status["candidates"][0]["shadow_only"] is True
