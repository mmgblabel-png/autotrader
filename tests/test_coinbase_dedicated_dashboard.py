from types import SimpleNamespace

from autotrader.api.coinbase_dashboard_html import coinbase_dashboard_html
from autotrader.api import server


def test_coinbase_dashboard_is_standalone_and_uses_coinbase_snapshot():
    html = coinbase_dashboard_html()
    assert "Coinbase Control Room" in html
    assert "/api/coinbase/dashboard/snapshot" in html
    assert "/api/dashboard/snapshot" not in html
    assert "/api/security/bitvavo" not in html.lower()
    assert "Bitvavo" not in html
    assert "I_UNDERSTAND_COINBASE_LIVE_ORDERS" in html
    assert "X-Autotrader-Token" in html


def test_coinbase_dashboard_routes_are_registered():
    paths = {route.path for route in server.app.routes}
    assert "/coinbase-dashboard" in paths
    assert "/api/coinbase/dashboard/snapshot" in paths


def test_coinbase_snapshot_scopes_balance_to_agent_portfolio(monkeypatch):
    seen = {}

    class FakeMarketData:
        def account_balances(self, portfolio_id=None):
            seen["portfolio_id"] = portfolio_id
            return {
                "venue": "coinbase_advanced",
                "authenticated": True,
                "portfolio_scoped": bool(portfolio_id),
                "assets": [{"currency": "EUR", "available": "6", "hold": "0", "total": "6"}],
            }

    server.app.state.coinbase_autonomous_executor = SimpleNamespace(
        config=SimpleNamespace(
            portfolio_id="agent-portfolio",
            require_isolated_portfolio=True,
        )
    )
    server.app.state.market_universe = SimpleNamespace(
        status=lambda: {
            "coinbase": {"all": 911, "tradable": 900, "crypto_crypto": 467, "eur_quote": 80},
            "updated_at": 1.0,
            "venue_errors": {},
        }
    )

    monkeypatch.setattr(server, "CoinbaseAdvancedMarketData", FakeMarketData)
    monkeypatch.setattr(server, "coinbase_zscore_shadow_status", lambda: {"settled_trades": 3})
    monkeypatch.setattr(server, "coinbase_autonomous_status", lambda: {"coinbase_armed": False})
    monkeypatch.setattr(server, "coinbase_live_readiness", lambda: {"ready_to_arm": True})

    data = server.coinbase_dashboard_snapshot()
    assert seen["portfolio_id"] == "agent-portfolio"
    assert data["portfolio_isolated"] is True
    assert data["balances"]["assets"][0]["total"] == "6"
    assert data["universe"]["all"] == 911
    assert "bitvavo" not in data
