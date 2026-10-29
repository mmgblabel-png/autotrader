from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData


def test_coinbase_balance_summary_aggregates_without_ids(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    monkeypatch.setattr(
        client,
        "_auth_get",
        lambda path: {
            "accounts": [
                {
                    "uuid": "secret-account-id-1",
                    "currency": "EUR",
                    "active": True,
                    "available_balance": {"value": "12.50", "currency": "EUR"},
                    "hold": {"value": "1.25", "currency": "EUR"},
                },
                {
                    "uuid": "secret-account-id-2",
                    "currency": "EUR",
                    "active": True,
                    "available_balance": {"value": "2.50", "currency": "EUR"},
                    "hold": {"value": "0.25", "currency": "EUR"},
                },
                {
                    "uuid": "secret-account-id-3",
                    "currency": "BTC",
                    "active": True,
                    "available_balance": {"value": "0.001", "currency": "BTC"},
                    "hold": {"value": "0.0002", "currency": "BTC"},
                },
                {
                    "uuid": "zero-balance-account",
                    "currency": "ETH",
                    "active": True,
                    "available_balance": {"value": "0", "currency": "ETH"},
                    "hold": {"value": "0", "currency": "ETH"},
                },
            ]
        },
    )

    result = client.account_balances()
    assert result["authenticated"] is True
    assert result["account_count"] == 4
    assert result["asset_count"] == 2
    assert result["assets"][0] == {
        "currency": "EUR",
        "available": "15.00",
        "hold": "1.50",
        "total": "16.50",
    }
    assert result["assets"][1] == {
        "currency": "BTC",
        "available": "0.001",
        "hold": "0.0002",
        "total": "0.0012",
    }
    assert "uuid" not in str(result).lower()
    assert "secret-account-id" not in str(result)


def test_dashboard_is_bitvavo_only():
    from autotrader.api.dashboard_html import dashboard_html

    html = dashboard_html()
    lower = html.lower()
    assert "Bitvavo Connectivity & Safety" in html
    assert "Bitvavo Market Universe" in html
    assert "Bitvavo Scanner Health" in html
    assert "/api/dashboard/snapshot" in html
    assert "section('bitvavo_live_state')" in html
    assert "section('bitvavo_security')" in html
    assert "coinbase" not in lower
    assert "binance" not in lower


def test_coinbase_balance_retries_unfiltered_for_portfolio_bound_key(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    calls = []

    def fake_auth_get(path, params=None):
        calls.append((path, params))
        if params and params.get("retail_portfolio_id") == "agent-portfolio":
            return {"accounts": []}
        return {
            "accounts": [
                {
                    "currency": "USDC",
                    "active": True,
                    "available_balance": {"value": "15.128855941", "currency": "USDC"},
                    "hold": {"value": "0", "currency": "USDC"},
                },
                {
                    "currency": "EUR",
                    "active": True,
                    "available_balance": {"value": "0.90928517903825", "currency": "EUR"},
                    "hold": {"value": "0", "currency": "EUR"},
                },
            ]
        }

    monkeypatch.setattr(client, "_auth_get", fake_auth_get)

    result = client.account_balances("agent-portfolio")

    assert result["portfolio_scoped"] is True
    assert result["portfolio_id"] == "agent-portfolio"
    assert result["portfolio_filter_fallback"] is True
    assert result["asset_count"] == 2
    assert result["assets"][0]["currency"] == "EUR"
    assert result["assets"][1]["currency"] == "USDC"
    assert calls == [
        (client.ACCOUNTS_PATH, {"retail_portfolio_id": "agent-portfolio"}),
        (f"{client.PORTFOLIOS_PATH}/agent-portfolio", None),
        (client.ACCOUNTS_PATH, None),
    ]


def test_coinbase_balance_uses_portfolio_breakdown_when_scoped_accounts_are_empty(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    calls = []

    def fake_auth_get(path, params=None):
        calls.append((path, params))
        if path == client.ACCOUNTS_PATH and params:
            return {"accounts": []}
        if path == f"{client.PORTFOLIOS_PATH}/agent-portfolio":
            return {
                "portfolio": {"uuid": "agent-portfolio", "name": "AutoTrader Agent"},
                "portfolio_balances": {
                    "total_balance": {"currency": "EUR", "value": "14.49"}
                },
                "spot_positions": [
                    {
                        "asset": "USDC",
                        "available_to_trade_crypto": "15.128856",
                        "total_balance_crypto": "15.128856",
                        "is_cash": True,
                    },
                    {
                        "asset": "EUR",
                        "available_to_trade_crypto": "0.9092852",
                        "total_balance_crypto": "0.9092852",
                        "is_cash": True,
                    },
                ],
            }
        raise AssertionError(f"unexpected fallback request: {path} {params}")

    monkeypatch.setattr(client, "_auth_get", fake_auth_get)

    result = client.account_balances("agent-portfolio")

    assert result["portfolio_scoped"] is True
    assert result["portfolio_filter_fallback"] is True
    assert result["balance_source"] == "portfolio_breakdown"

    assets = {row["currency"]: row for row in result["assets"]}
    assert set(assets) == {"EUR", "USDC"}
    assert float(assets["EUR"]["available"]) > 0
    assert float(assets["USDC"]["available"]) > 15
    assert float(assets["EUR"]["total"]) == float(assets["EUR"]["available"])
    assert float(assets["USDC"]["total"]) == float(assets["USDC"]["available"])

    assert calls[0] == (
        client.ACCOUNTS_PATH,
        {"retail_portfolio_id": "agent-portfolio"},
    )
    assert calls[1] == (f"{client.PORTFOLIOS_PATH}/agent-portfolio", None)
    assert len(calls) == 2
