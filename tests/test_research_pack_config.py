from pathlib import Path

import yaml


def _config():
    return yaml.safe_load(Path("config.yaml").read_text())


def test_research_pack_config_is_valid_and_does_not_raise_live_budget():
    cfg = _config()
    assert cfg["portfolio"]["global_live_budget_eur"] == 50

    live = {
        key: value
        for key, value in cfg["strategies"].items()
        if value.get("enabled") and value.get("live_capable")
    }
    assert sum(float(row.get("allocation_eur", 0)) for row in live.values()) == 40
    assert live["grid"]["allocation_eur"] == 8
    assert live["grid_eth"]["allocation_eur"] == 7
    assert live["grid"]["symbol"] == "SOL-EUR"
    assert live["grid_eth"]["symbol"] == "ETH-EUR"
    assert live["grid_eth"]["strategy_name"] == "GridRunnerETH"


def test_research_only_markets_do_not_leak_into_live_allowlists():
    cfg = _config()
    strategy_markets = cfg["autonomous_execution"]["strategy_markets"]
    research_only = {
        "NEAR-EUR", "AVAX-EUR", "HBAR-EUR", "SUI-EUR", "XLM-EUR",
        "AAVE-EUR", "ALGO-EUR", "ONDO-EUR", "FET-EUR", "DOT-EUR",
        "LTC-EUR", "BCH-EUR", "UNI-EUR", "HYPE-EUR", "QNT-EUR",
    }
    live_allowed = {
        str(market).upper()
        for markets in strategy_markets.values()
        for market in (markets or [])
    }
    assert research_only.isdisjoint(live_allowed)

    router_markets = {
        str(market).upper()
        for market in cfg["opportunity_router"]["markets"]
    }
    assert research_only.issubset(router_markets)


def test_eth_grid_is_pinned_to_eth_only():
    cfg = _config()
    assert cfg["autonomous_execution"]["strategy_markets"]["grid_eth"] == ["ETH-EUR"]
    assert "ETH-EUR" not in cfg["autonomous_execution"]["strategy_markets"]["grid"]
