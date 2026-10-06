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
