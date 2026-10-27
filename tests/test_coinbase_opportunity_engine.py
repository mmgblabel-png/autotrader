from decimal import Decimal

from autotrader.connectors.coinbase_advanced import CoinbaseTopOfBook
from autotrader.core.coinbase_opportunity_engine import CoinbaseOpportunityEngine


class FakeMarket:
    def __init__(self):
        self.step = 0

    def account_balances(self, portfolio_id=None):
        return {
            "assets": [
                {"currency": "EUR", "available": "6", "hold": "0", "total": "6"},
            ]
        }

    def list_spot_products(self):
        return [
            {
                "product_id": "BTC-EUR", "base": "BTC", "quote": "EUR",
                "tradable": True, "price": "70000", "volume_24h": "100",
                "price_change_24h_pct": "0.8",
            },
            {
                "product_id": "XRP-EUR", "base": "XRP", "quote": "EUR",
                "tradable": True, "price": "1.10", "volume_24h": "2000000",
                "price_change_24h_pct": "2.0",
            },
            {
                "product_id": "SOL-USDC", "base": "SOL", "quote": "USDC",
                "tradable": True, "price": "90", "volume_24h": "100000",
                "price_change_24h_pct": "3.0",
            },
        ]

    def top_of_book(self, product_id):
        base = {"BTC-EUR": 70000.0, "XRP-EUR": 1.10}[product_id]
        growth = 1.0 + self.step * 0.001
        mid = base * growth
        spread = mid * 0.0002
        return CoinbaseTopOfBook(
            product_id=product_id,
            bid_price=Decimal(str(mid - spread / 2)),
            bid_size=Decimal("100"),
            ask_price=Decimal(str(mid + spread / 2)),
            ask_size=Decimal("100"),
        )


def test_opportunity_engine_scans_full_universe_but_only_fundable_quotes_trade():
    market = FakeMarket()
    engine = CoinbaseOpportunityEngine(
        {
            "interval_seconds": 10,
            "universe_refresh_seconds": 60,
            "candidate_limit": 10,
            "sample_lookback_seconds": 600,
            "min_samples": 3,
            "min_recent_momentum_bps": 5,
            "max_spread_bps": 20,
            "min_24h_quote_volume": 1000,
            "quote_currencies": ["EUR", "USDC"],
            "daily_trade_target": 10,
            "daily_profit_target_eur": 1.0,
        },
        market_data=market,
        portfolio_id="agent-portfolio",
    )

    status = None
    for i in range(4):
        market.step = i
        status = engine.tick(now=1000.0 + i * 20.0)

    assert status is not None
    assert status["scanned_markets"] == 3
    assert status["tradable_markets"] == 3
    assert status["fundable_markets"] == 2
    assert status["fundable_quotes"] == ["EUR"]
    decisions = status["last_signal"]["decisions"]
    assert decisions
    assert all(row["product_id"].endswith("-EUR") for row in decisions)
    assert not any(row["product_id"] == "SOL-USDC" for row in decisions)
    assert status["daily_trade_target"] == 10
    assert status["daily_profit_target_eur"] == 1.0
    assert status["target_policy"] == "targets_only_never_force_negative_edge"
