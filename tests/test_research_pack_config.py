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
    assert sum(float(row.get("allocation_eur", 0)) for row in live.values()) == 50
    assert live["market_maker"]["allocation_eur"] == 20
    assert live["grid"]["allocation_eur"] == 15
    assert live["grid_eth"]["allocation_eur"] == 15
    assert cfg["strategies"]["sniper"]["live_capable"] is False
    assert cfg["strategies"]["sniper"]["allocation_eur"] == 0
    assert cfg["live_evidence_gate"]["min_completed_exits"] == 4
    assert cfg["live_evidence_gate"]["minimum_net_pnl_eur"] == -0.10
    assert live["grid"]["allocation_eur"] == 10
    assert live["grid_eth"]["allocation_eur"] == 10
    assert live["sniper"]["allocation_eur"] == 12
    assert live["grid"]["symbol"] == "SOL-EUR"
    assert live["grid_eth"]["symbol"] == "ETH-EUR"
    assert live["grid_eth"]["strategy_name"] == "GridRunnerETH"


def test_all_live_bots_can_use_broad_safe_market_selection():
    cfg = _config()
    strategy_markets = cfg["autonomous_execution"]["strategy_markets"]
    assert strategy_markets["market_maker"] == ["*"]
    assert strategy_markets["grid"] == ["*"]
    assert strategy_markets["grid_eth"] == ["*"]
    assert strategy_markets["sniper"] == ["*"]
    assert cfg["autonomous_execution"]["allow_non_eur_live"] is False


def test_router_scans_full_bitvavo_universe_but_live_non_eur_stays_blocked():
    cfg = _config()
    router = cfg["opportunity_router"]
    assert router["auto_discover_all"] is True
    assert router["max_markets"] == 500
    assert cfg["shadow_lab"]["dynamic_markets_per_strategy"] >= 10
    assert cfg["shadow_lab"]["promotion_min_completed_trades"] == 24
    assert cfg["shadow_lab"]["promotion_min_profit_factor"] >= 1.10
    assert cfg["shadow_lab"]["promotion_cost_stress_multiplier"] >= 1.25
    assert cfg["shadow_lab"]["strategies"]["volatility_breakout"]["strategy_version"] == "v3"
    assert cfg["shadow_lab"]["strategies"]["sniper_v2"]["strategy_version"] == "v2"


def test_live_sniper_has_bounded_execution_quality_gates():
    cfg = _config()
    sniper = cfg["strategies"]["sniper"]
    assert sniper["autonomous_min_score"] >= 82
    assert sniper["autonomous_min_signal_strength"] >= 80
    assert sniper["autonomous_min_confidence"] >= 0.75
    assert sniper["autonomous_min_momentum_pct"] >= 0.12
    assert sniper["autonomous_max_momentum_pct"] <= 0.80
    assert sniper["autonomous_max_spread_bps"] <= 15.0
    assert sniper["autonomous_min_liquidity_eur"] >= 100.0
    assert sniper["autonomous_max_expected_slippage_bps"] <= 5.0
    assert sniper["entry_max_slippage_pct"] <= 0.12


def test_adaptive_learning_has_post_rollback_holdoff():
    cfg = _config()
    adaptive = cfg["adaptive_learning"]
    assert adaptive["rollback_cooldown_exits"] >= adaptive["change_cooldown"]
    assert adaptive["rollback_cooldown_exits"] >= 12
