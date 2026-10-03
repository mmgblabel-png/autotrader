import os

import pytest

from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData
from autotrader.core.derivatives_risk_lab import DerivativesRiskLab


def test_derivatives_lab_is_shadow_only_and_never_promotion_ready():
    lab = DerivativesRiskLab({
        "enabled": True,
        "max_research_leverage": 3.0,
        "max_collateral_pct_of_nav": 5.0,
        "min_liquidation_buffer_pct": 20.0,
        "max_stressed_loss_pct_of_collateral": 35.0,
        "initial_margin_pct": 50.0,
        "maintenance_margin_pct": 10.0,
        "fee_pct_each_leg": 0.25,
        "funding_rate_8h_pct": 0.01,
        "holding_hours": 8.0,
        "stress_move_pct": 8.0,
    })
    status = lab.status(nav_eur=80.0)
    assert status["live_capable"] is False
    assert status["live_orders_sent"] is False
    assert status["promotion_ready"] is False
    assert all(row["promotion_ready"] is False for row in status["scenarios"])


def test_derivatives_lab_blocks_too_much_collateral_and_stress():
    lab = DerivativesRiskLab({
        "max_research_leverage": 3.0,
        "max_collateral_pct_of_nav": 5.0,
        "min_liquidation_buffer_pct": 20.0,
        "max_stressed_loss_pct_of_collateral": 35.0,
        "initial_margin_pct": 50.0,
        "maintenance_margin_pct": 10.0,
        "fee_pct_each_leg": 0.25,
        "funding_rate_8h_pct": 0.01,
        "holding_hours": 8.0,
        "stress_move_pct": 20.0,
    })
    row = lab.evaluate(
        symbol="BTC-PERP",
        side="LONG",
        collateral_eur=8.0,
        leverage=3.0,
        nav_eur=80.0,
    )
    assert row["research_gate_passed"] is False
    assert "collateral_share_of_nav_too_high" in row["blockers"]
    assert "initial_margin_insufficient" in row["blockers"]
    assert "stress_loss_too_high" in row["blockers"]


def test_derivatives_lab_approximates_isolated_liquidation_buffer():
    lab = DerivativesRiskLab({
        "max_research_leverage": 3.0,
        "initial_margin_pct": 50.0,
        "maintenance_margin_pct": 10.0,
        "fee_pct_each_leg": 0.0,
        "funding_rate_8h_pct": 0.0,
        "stress_move_pct": 5.0,
    })
    row = lab.evaluate(
        symbol="ETH-PERP",
        side="LONG",
        collateral_eur=4.0,
        leverage=2.0,
        nav_eur=100.0,
    )
    assert row["notional_eur"] == 8.0
    assert row["liquidation_buffer_pct_approx"] == pytest.approx(40.0)
    assert row["stressed_net_pnl_eur"] == pytest.approx(-0.4)


def test_derivatives_probe_fails_closed_without_portfolio(monkeypatch):
    monkeypatch.delenv("COINBASE_INTX_PORTFOLIO_UUID", raising=False)
    client = CoinbaseAdvancedMarketData()
    result = client.derivatives_risk_probe()
    assert result["read_only"] is True
    assert result["configured"] is False
    assert result["eligible"] is None
    assert result["error_category"] == "derivatives_portfolio_missing"


def test_derivatives_positions_are_redacted_and_read_only(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    portfolio = "11111111-1111-1111-1111-111111111111"

    def fake(path):
        assert path.endswith(portfolio)
        if "/positions/" in path:
            return {
                "positions": [{
                    "product_id": "BTC-PERP-INTX",
                    "product_uuid": "secret-product-id",
                    "portfolio_uuid": portfolio,
                    "symbol": "BTC-PERP",
                    "position_side": "LONG",
                    "margin_type": "ISOLATED",
                    "net_size": "0.001",
                    "leverage": "2",
                    "mark_price": {"value": "70000", "currency": "USD"},
                    "liquidation_price": {"value": "40000", "currency": "USD"},
                    "position_notional": {"value": "70", "currency": "USDC"},
                    "unrealized_pnl": {"value": "1.5", "currency": "USDC"},
                    "im_contribution": "35",
                }]
            }
        return {
            "portfolio_balances": [{
                "portfolio_uuid": portfolio,
                "is_margin_limit_reached": False,
                "balances": [{
                    "asset": {
                        "asset_id": "USDC",
                        "asset_uuid": "secret-asset-uuid",
                        "asset_name": "USD Coin",
                    },
                    "quantity": "100",
                    "hold": "5",
                    "collateral_value": "100",
                    "collateral_weight": "1",
                    "max_withdraw_amount": "95",
                }],
            }]
        }

    monkeypatch.setattr(client, "_auth_get", fake)
    result = client.derivatives_risk_probe(portfolio)
    assert result["authenticated"] is True
    assert result["eligible"] is True
    assert result["positions"]["position_count"] == 1
    assert "portfolio_uuid" not in str(result)
    assert "secret-product-id" not in str(result)
    assert "secret-asset-uuid" not in str(result)
