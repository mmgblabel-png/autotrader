from types import SimpleNamespace

import pytest

from autotrader.api.server import _fee_margin_payload_from_account


def _agent():
    return SimpleNamespace(
        _config={
            "profit_policy": {
                "estimated_entry_fee_pct": 0.25,
                "estimated_exit_fee_pct": 0.25,
                "estimated_slippage_each_leg_pct": 0.05,
                "min_expected_net_edge_pct": 0.15,
            }
        }
    )


def test_fee_margin_payload_uses_actual_maker_and_taker_rates_without_mutating_policy():
    payload = _fee_margin_payload_from_account(
        _agent(),
        {"fees": {"maker": "0.0015", "taker": "0.0025", "volume": "1234.56"}},
    )

    assert payload["maker_fee_pct"] == pytest.approx(0.15)
    assert payload["taker_fee_pct"] == pytest.approx(0.25)
    assert payload["volume_30d_eur"] == pytest.approx(1234.56)
    assert payload["configured_policy"]["required_gross_edge_pct"] == pytest.approx(0.75)
    assert payload["live_profit_gates_changed"] is False

    routes = {row["strategy"]: row for row in payload["strategy_routes"]}
    assert routes["MarketMaker"]["order_mode"] == "limit + postOnly"
    assert routes["MarketMaker"]["fee_class"] == "maker"
    assert routes["MarketMaker"]["two_leg_fee_floor_pct"] == pytest.approx(0.30)
    assert routes["MarketMaker"]["research_required_gross_edge_pct"] == pytest.approx(0.55)
    assert routes["GridRunnerETH"]["research_required_gross_edge_pct"] == pytest.approx(0.55)
    assert routes["SniperBot"]["order_mode"] == "market"
    assert routes["SniperBot"]["fee_class"] == "taker"
    assert routes["SniperBot"]["research_required_gross_edge_pct"] == pytest.approx(0.75)


def test_fee_margin_payload_fails_read_only_when_account_fee_fields_missing():
    payload = _fee_margin_payload_from_account(_agent(), {})
    assert payload["maker_fee_pct"] is None
    assert payload["taker_fee_pct"] is None
    assert payload["live_profit_gates_changed"] is False
