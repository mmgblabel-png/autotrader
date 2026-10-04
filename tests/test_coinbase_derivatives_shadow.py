from decimal import Decimal

from autotrader.connectors.coinbase_advanced import CoinbaseTopOfBook
from autotrader.connectors.coinbase_derivatives import (
    CoinbaseDerivativesGateway,
    CoinbaseDerivativesTicker,
)
from autotrader.core.coinbase_derivatives_shadow import CoinbaseDerivativesShadowScanner


def test_derivatives_gateway_lists_future_catalogue(monkeypatch):
    class FakeAdvanced:
        PRODUCTS_PATH = "/api/v3/brokerage/market/products"

        def __init__(self):
            self.calls = []

        def _get(self, path, params=None):
            self.calls.append((path, dict(params or {})))
            return {
                "products": [
                    {
                        "product_id": "BIT-30OCT26-CDE",
                        "product_type": "FUTURE",
                        "future_product_details": {
                            "contract_expiry": "2026-10-30T16:00:00Z",
                            "open_interest": "100",
                        },
                    }
                ],
                "has_next": False,
            }

    fake = FakeAdvanced()
    client = CoinbaseDerivativesGateway(client=fake)
    rows = client.list_futures()
    assert rows[0]["product_id"] == "BIT-30OCT26-CDE"
    assert fake.calls[0][1]["product_type"] == "FUTURE"


def test_derivatives_gateway_selects_nearest_crypto_future(monkeypatch):
    client = CoinbaseDerivativesGateway(client=object())
    monkeypatch.setattr(
        client,
        "list_futures",
        lambda: [
            {
                "product_id": "BIT-27NOV26-CDE",
                "future_product_details": {
                    "contract_expiry": "2026-11-27T16:00:00Z",
                    "open_interest": "500",
                },
                "fcm_trading_session_details": {"is_session_open": True},
            },
            {
                "product_id": "BIT-30OCT26-CDE",
                "future_product_details": {
                    "contract_expiry": "2026-10-30T16:00:00Z",
                    "open_interest": "1000",
                },
                "fcm_trading_session_details": {"is_session_open": True},
            },
            {
                "product_id": "ET-30OCT26-CDE",
                "future_product_details": {
                    "contract_expiry": "2026-10-30T16:00:00Z",
                    "open_interest": "2000",
                },
                "fcm_trading_session_details": {"is_session_open": True},
            },
        ],
    )
    selected = client.nearest_crypto_futures()
    ids = {row["product_id"] for row in selected}
    assert "BIT-30OCT26-CDE" in ids
    assert "BIT-27NOV26-CDE" not in ids
    assert "ET-30OCT26-CDE" in ids


def test_derivatives_ticker_joins_future_and_spot_books():
    class FakeAdvanced:
        def top_of_book(self, product_id):
            if product_id == "BIT-30OCT26-CDE":
                return CoinbaseTopOfBook(
                    product_id=product_id,
                    bid_price=Decimal("85400"),
                    bid_size=Decimal("20"),
                    ask_price=Decimal("85420"),
                    ask_size=Decimal("25"),
                )
            assert product_id == "BTC-USD"
            return CoinbaseTopOfBook(
                product_id=product_id,
                bid_price=Decimal("85000"),
                bid_size=Decimal("1"),
                ask_price=Decimal("85010"),
                ask_size=Decimal("1"),
            )

    client = CoinbaseDerivativesGateway(client=FakeAdvanced())
    ticker = client.ticker_from_product(
        {
            "product_id": "BIT-30OCT26-CDE",
            "price_percentage_change_24h": "1.2",
            "future_product_details": {
                "contract_expiry": "2026-10-30T16:00:00Z",
                "contract_size": "0.01",
                "open_interest": "10000",
                "intraday_margin_rate": {
                    "long_margin_rate": "0.10",
                    "short_margin_rate": "0.10",
                },
            },
            "fcm_trading_session_details": {"is_session_open": True},
        }
    )
    assert ticker.underlying == "BTC"
    assert ticker.spot_product_id == "BTC-USD"
    assert ticker.open_interest == 10000
    assert ticker.basis_bps > 0
    assert ticker.spread_bps > 0


def test_derivatives_shadow_scanner_is_confirmation_only():
    class FakeClient:
        def nearest_crypto_futures(self):
            return [{"product_id": "BIT-30OCT26-CDE"}]

        def ticker_from_product(self, row):
            return CoinbaseDerivativesTicker(
                instrument_name="BIT-30OCT26-CDE",
                underlying="BTC",
                spot_product_id="BTC-USD",
                mark_price=85410.0,
                index_price=85005.0,
                best_bid_price=85400.0,
                best_ask_price=85420.0,
                open_interest=10000.0,
                price_change_pct=1.2,
                contract_size=0.01,
                long_margin_rate=0.10,
                short_margin_rate=0.10,
                contract_expiry="2026-10-30T16:00:00Z",
                session_open=True,
            )

        def auth_probe(self):
            return {
                "authenticated": False,
                "risk_profile_readable": False,
                "positions_readable": False,
                "error_category": "market_data_only_consumer_derivatives_route",
                "order_sent": False,
                "public_advanced_futures_data_available": True,
            }

    scanner = CoinbaseDerivativesShadowScanner(
        {
            "enabled": True,
            "max_abs_basis_bps": 500,
            "max_spread_bps": 100,
            "min_open_interest": 10,
            "top_n": 4,
            "score_adjustment_max": 2,
        },
        client=FakeClient(),
    )
    status = scanner.tick()
    assert status["mode"] == "shadow_confirmation"
    assert status["signal_usage"] == "spot_confirmation_overlay"
    assert status["live_orders_sent"] is False
    assert status["order_capability_implemented"] is False
    assert status["candidate_count"] == 1
    row = status["candidates"][0]
    assert row["spot_market"] == "BTC-EUR"
    assert row["direction"] == "LONG_BIAS"
    assert 0 < row["score_adjustment_hint"] <= 2.0
    assert row["shadow_only"] is True
