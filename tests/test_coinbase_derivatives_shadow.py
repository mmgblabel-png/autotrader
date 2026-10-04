from autotrader.connectors.coinbase_derivatives import (
    CoinbaseDerivativesGateway,
    CoinbaseDerivativesTicker,
)
from autotrader.core.coinbase_derivatives_shadow import CoinbaseDerivativesShadowScanner


def test_cde_gateway_lists_perpetual_instruments(monkeypatch):
    client = CoinbaseDerivativesGateway()
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return [
            {
                "symbol": "BIPZ30",
                "product_code": "BIP",
                "trading_state": "OPEN",
                "is_perp": True,
                "contract_size": 0.01,
            }
        ]

    monkeypatch.setattr(client, "_request", fake_request)
    rows = client.list_futures(product_codes=["BIP"])
    assert rows[0]["symbol"] == "BIPZ30"
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/rest/instruments"
    assert calls[0][2]["payload"]["product_codes"] == ["BIP"]


def test_cde_ticker_uses_latest_funding_snapshot(monkeypatch):
    client = CoinbaseDerivativesGateway()
    monkeypatch.setattr(
        client,
        "funding_history",
        lambda symbol: [
            {
                "symbol": symbol,
                "funding_rate": "0.0001",
                "future_mark_price": "100.20",
                "spot_mark_price": "100.00",
                "fair_value_price": "100.10",
            }
        ],
    )
    ticker = client.ticker_from_instrument(
        {
            "symbol": "BIPZ30",
            "contract_size": 0.01,
            "long_initial_margin": 1000,
            "short_initial_margin": 1000,
            "trading_state": "OPEN",
            "funding_interval_minutes": 60,
            "is_perp": True,
        }
    )
    assert round(ticker.basis_bps, 2) == 20.0
    assert ticker.funding_rate == 0.0001
    assert ticker.contract_size == 0.01


def test_derivatives_shadow_scanner_never_places_orders():
    class FakeClient:
        def list_futures(self, *, product_codes=None):
            return [
                {
                    "symbol": "BIPZ30",
                    "product_code": "BIP",
                    "is_perp": True,
                    "trading_state": "OPEN",
                    "contract_size": 0.01,
                }
            ]

        def ticker_from_instrument(self, row):
            return CoinbaseDerivativesTicker(
                instrument_name="BIPZ30",
                mark_price=100.20,
                index_price=100.00,
                fair_value_price=100.10,
                funding_rate=0.0001,
                contract_size=0.01,
                long_initial_margin_bps=1000,
                short_initial_margin_bps=1000,
                trading_state="OPEN",
                funding_interval_minutes=60,
                is_perp=True,
            )

        def auth_probe(self):
            return {
                "authenticated": False,
                "risk_profile_readable": False,
                "positions_readable": False,
                "error_category": "consumer_broker_order_api_not_exposed_by_current_cdp_key",
                "order_sent": False,
                "public_cde_data_available": True,
            }

    scanner = CoinbaseDerivativesShadowScanner(
        {
            "enabled": True,
            "product_codes": ["BIP"],
            "max_abs_basis_bps": 250,
            "top_n": 4,
        },
        client=FakeClient(),
    )
    status = scanner.tick()
    assert status["mode"] == "shadow_signal"
    assert status["live_orders_sent"] is False
    assert status["order_capability_implemented"] is False
    assert status["candidate_count"] == 1
    row = status["candidates"][0]
    assert row["instrument"] == "BIPZ30"
    assert row["spot_market"] == "BTC-EUR"
    assert row["direction"] == "SHORT_BIAS"
    assert row["shadow_only"] is True
