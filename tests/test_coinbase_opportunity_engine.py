from decimal import Decimal

from autotrader.connectors.coinbase_advanced import CoinbaseTopOfBook
from autotrader.core.coinbase_opportunity_engine import CoinbaseOpportunityEngine


class FakeRealtime:
    def __init__(self):
        self.products = []

    def set_products(self, product_ids):
        self.products = list(product_ids)

    def snapshot(self, product_id):
        return {
            "product_id": product_id,
            "fresh": True,
            "best_bid": 100.0,
            "best_ask": 100.1,
            "book_imbalance": 0.8,
            "trade_flow_imbalance": 0.7,
            "microprice_edge_bps": 1.5,
            "trade_velocity_ratio": 2.0,
            "trade_count": 12,
        }

    def status(self):
        return {
            "enabled": True,
            "started": True,
            "connected": True,
            "subscribed_count": len(self.products),
            "subscribed_products": list(self.products),
            "last_error": None,
        }


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
    assert status["target_policy"] == "aggregate_realized_pnl_target_never_force_negative_edge"


def test_opportunity_engine_emits_high_risk_fallback_tier():
    market = FakeMarket()
    engine = CoinbaseOpportunityEngine(
        {
            "interval_seconds": 10,
            "universe_refresh_seconds": 60,
            "candidate_limit": 10,
            "sample_lookback_seconds": 600,
            "min_samples": 4,
            "min_recent_momentum_bps": 50,
            "max_spread_bps": 20,
            "min_24h_quote_volume": 1000,
            "quote_currencies": ["EUR"],
            "high_risk_enabled": True,
            "high_risk_min_samples": 3,
            "high_risk_min_recent_momentum_bps": 8,
            "high_risk_max_spread_bps": 35,
            "high_risk_min_24h_quote_volume": 1000,
        },
        market_data=market,
        portfolio_id="agent-portfolio",
    )

    status = None
    for i in range(3):
        market.step = i
        status = engine.tick(now=2000.0 + i * 20.0)

    assert status is not None
    decisions = status["last_signal"]["decisions"]
    assert decisions
    assert all(row["risk_tier"] == "high" for row in decisions)
    assert all(row["reason"] == "high_risk_orderflow_momentum" for row in decisions)


def test_opportunity_engine_uses_realtime_orderflow_edge(tmp_path):
    market = FakeMarket()
    realtime = FakeRealtime()
    engine = CoinbaseOpportunityEngine(
        {
            "interval_seconds": 5,
            "universe_refresh_seconds": 60,
            "candidate_limit": 10,
            "realtime_product_limit": 2,
            "sample_lookback_seconds": 600,
            "min_samples": 2,
            "min_recent_momentum_bps": 500,
            "realtime_min_edge_bps": 4,
            "max_spread_bps": 20,
            "min_24h_quote_volume": 1000,
            "quote_currencies": ["EUR"],
            "state_path": str(tmp_path / "opportunity-state.json"),
        },
        market_data=market,
        portfolio_id="agent-portfolio",
        realtime_orderflow=realtime,
    )

    market.step = 0
    engine.tick(now=1000.0)
    market.step = 0
    status = engine.tick(now=1010.0)

    assert realtime.products
    assert all(product.endswith("-EUR") for product in realtime.products)
    assert status["realtime"]["connected"] is True
    candidates = status["top_candidates"]
    assert candidates
    assert candidates[0]["orderflow_fresh"] is True
    assert candidates[0]["realtime_edge_bps"] > 0
    decisions = status["last_signal"]["decisions"]
    assert decisions
    assert any(row["reason"] == "multi_market_positive_momentum" for row in decisions)


def test_opportunity_rotation_eventually_evaluates_full_fundable_universe():
    class ManyMarket:
        def __init__(self):
            self.seen_books = []

        def account_balances(self, portfolio_id=None):
            return {
                "assets": [
                    {"currency": "USDC", "available": "20", "hold": "0", "total": "20"},
                ]
            }

        def list_spot_products(self):
            rows = []
            for i in range(80):
                rows.append({
                    "product_id": f"C{i}-USDC",
                    "base": f"C{i}",
                    "quote": "USDC",
                    "tradable": True,
                    "price": "1",
                    "volume_24h": "100000",
                    "price_change_24h_pct": str(8.0 - i * 0.01),
                })
            return rows

        def top_of_book(self, product_id):
            self.seen_books.append(product_id)
            return CoinbaseTopOfBook(
                product_id=product_id,
                bid_price=Decimal("1.0000"),
                bid_size=Decimal("1000"),
                ask_price=Decimal("1.0005"),
                ask_size=Decimal("1000"),
            )

    market = ManyMarket()
    engine = CoinbaseOpportunityEngine(
        {
            "candidate_limit": 40,
            "realtime_product_limit": 10,
            "min_samples": 2,
            "min_recent_momentum_bps": 1000,
            "min_24h_quote_volume": 1000,
            "quote_currencies": ["USDC"],
        },
        market_data=market,
        portfolio_id="agent-portfolio",
    )

    for i in range(5):
        engine.tick(now=1000.0 + i * 20.0)

    assert len(set(market.seen_books)) == 80
    assert engine.status()["evaluated_markets_this_tick"] == 40
