from pathlib import Path

import yaml


def _config():
    return yaml.safe_load(Path("config.yaml").read_text())


def test_research_pack_config_uses_80_eur_live_capital_policy():
    cfg = _config()
    assert cfg["portfolio"]["initial_live_capital_eur"] == 80
    assert cfg["portfolio"]["global_live_budget_eur"] == 80
    assert cfg["portfolio"]["dynamic_with_verified_nav"] is True
    assert cfg["portfolio"]["max_deployable_pct"] == 80.0
    assert cfg["portfolio"]["min_cash_reserve_pct"] == 20.0

    live = {
        key: value
        for key, value in cfg["strategies"].items()
        if value.get("enabled") and value.get("live_capable")
    }
    assert sum(float(row.get("allocation_eur", 0)) for row in live.values()) == 72
    assert live["market_maker"]["allocation_eur"] == 8
    assert live["market_maker"]["max_order_eur"] == 5
    assert live["grid"]["allocation_eur"] == 44
    assert live["grid"]["max_order_eur"] == 12
    assert live["grid"]["order_value_eur"] == 10.0
    assert live["grid"]["exit_markup_pct"] == 1.00
    assert live["grid_eth"]["allocation_eur"] == 8
    assert live["grid_eth"]["max_order_eur"] == 5
    assert live["shadow_canary"]["allocation_eur"] == 6
    assert live["shadow_canary"]["max_order_eur"] == 6
    assert live["sniper"]["allocation_eur"] == 6
    assert live["sniper"]["max_order_eur"] == 5
    assert cfg["live_evidence_gate"]["min_completed_exits"] == 4
    assert cfg["live_evidence_gate"]["minimum_net_pnl_eur"] == 0.0
    assert live["grid"]["symbol"] == "SOL-EUR"
    assert cfg["strategies"]["grid_eth"]["symbol"] == "ETH-EUR"
    assert cfg["strategies"]["grid_eth"]["strategy_name"] == "GridRunnerETH"


def test_all_live_bots_can_use_broad_safe_market_selection():
    cfg = _config()
    strategy_markets = cfg["autonomous_execution"]["strategy_markets"]
    assert strategy_markets["market_maker"] == ["*"]
    assert strategy_markets["grid"] == ["*"]
    assert strategy_markets["grid_eth"] == ["*"]
    assert strategy_markets["sniper"] == ["*"]
    assert strategy_markets["shadow_canary"] == ["*"]
    assert cfg["autonomous_execution"]["allow_non_eur_live"] is True
    assert set(cfg["opportunity_router"]["live_quote_assets"]) == {"EUR", "BTC", "ETH", "USDC", "USDT"}


def test_router_scans_full_bitvavo_universe_with_bounded_live_quote_assets():
    cfg = _config()
    router = cfg["opportunity_router"]
    assert router["auto_discover_all"] is True
    assert router["max_markets"] == 500
    assert cfg["shadow_lab"]["dynamic_markets_per_strategy"] >= 10
    assert cfg["shadow_lab"]["promotion_min_completed_trades"] == 24
    assert cfg["shadow_lab"]["promotion_min_profit_factor"] >= 1.10
    assert cfg["shadow_lab"]["promotion_min_q10_return_pct"] >= -2.50
    assert cfg["shadow_lab"]["promotion_cost_stress_multiplier"] >= 1.25
    assert cfg["shadow_lab"]["canary_min_completed_trades"] >= 12
    assert cfg["shadow_lab"]["drift_gate_enabled"] is True
    assert cfg["shadow_lab"]["drift_baseline_bars"] >= 40
    assert cfg["shadow_lab"]["drift_recent_bars"] >= 10
    assert cfg["research_lab"]["walk_forward_purge_bars"] >= 1
    assert cfg["research_lab"]["walk_forward_embargo_bars"] >= 1
    assert cfg["shadow_lab"]["canary_min_net_pnl_eur"] > 0
    assert cfg["shadow_lab"]["canary_min_profit_factor"] >= 1.05
    assert cfg["shadow_lab"]["canary_min_q10_return_pct"] >= -3.50
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


def test_autonomous_fund_hard_policy_is_spot_only_and_non_disableable_in_config():
    cfg = _config()
    fund = cfg["fund"]
    auto = cfg["autonomous_execution"]
    scheduler = cfg["autonomous_fund"]
    assert fund["max_portfolio_drawdown_pct"] == 10.0
    assert fund["max_daily_loss_pct"] == 3.0
    assert fund["max_single_trade_pct"] == 20.0
    assert fund["max_gross_exposure_pct"] == 80.0
    assert fund["max_asset_exposure_pct"] == 20.0
    assert fund["min_cash_reserve_pct"] == 20.0
    assert auto["min_score"] == 85.0
    assert auto["instrument_scope"] == "spot_only"
    assert auto["allow_margin"] is False
    assert auto["allow_futures"] is False
    assert auto["allow_borrowing"] is False
    assert cfg["leverage_martingale_risk_lab"]["enabled"] is False
    assert cfg["leverage_martingale_risk_lab"]["leverage"] == 1.0
    assert cfg["leverage_martingale_risk_lab"]["max_martingale_steps"] == 0
    assert scheduler["monte_carlo_simulations"] >= 10000
    assert scheduler["report_daily"] is True
    assert scheduler["report_weekly"] is True
    assert scheduler["report_monthly"] is True


def test_every_live_spot_strategy_has_stop_trailing_and_partial_profit_protection():
    cfg = _config()
    for key in ("market_maker", "grid", "grid_eth"):
        row = cfg["strategies"][key]
        assert row["protection_stop_loss_pct"] > 0
        assert row["protection_trailing_activation_pct"] > 0
        assert row["protection_trailing_drawdown_pct"] > 0
        assert row["protection_partial_profit_trigger_pct"] > 0
        assert 0 < row["protection_partial_profit_fraction"] < 1


def test_aggressive_safe_bitvavo_profile_keeps_hard_risk_floor():
    cfg = _config()
    gate = cfg["live_evidence_gate"]
    auto = cfg["autonomous_execution"]
    fund = cfg["fund"]
    grid = cfg["strategies"]["grid"]

    assert auto["min_score"] == 85.0
    assert gate["recovery_min_score"] > 85.0
    assert gate["recovery_min_score"] == 86.0
    assert gate["recovery_order_eur"] <= 6.0
    assert gate["recovery_cooldown_seconds"] == 900
    assert gate["recovery_min_confidence"] >= 0.65
    assert gate["recovery_min_signal_strength"] >= 65.0
    assert gate["recovery_min_winrate_pct"] >= 45.0
    assert gate["recovery_max_net_deficit_eur"] <= 0.75

    assert auto["instrument_scope"] == "spot_only"
    assert auto["allow_margin"] is False
    assert auto["allow_futures"] is False
    assert auto["allow_borrowing"] is False
    assert fund["max_portfolio_drawdown_pct"] == 10.0
    assert fund["max_daily_loss_pct"] == 3.0
    assert fund["max_single_trade_pct"] == 20.0
    assert fund["min_cash_reserve_pct"] == 20.0

    assert auto["switch_cooldown_seconds"] == 45
    assert auto["max_size_score"] == 90.0
    assert auto["max_size_confidence"] == 0.70
    assert auto["high_volatility_size_multiplier"] == 0.65
    assert grid["cycle_cooldown_seconds"] == 30
    assert grid["failure_cooldown_seconds"] == 10


def test_all_research_agents_participate_and_learning_runs_faster():
    cfg = _config()
    weights = cfg["fund"]["agent_weights"]
    for name in (
        "market_research",
        "trend_detection",
        "onchain_analysis",
        "whale_tracking",
        "sentiment",
        "risk",
        "portfolio_allocation",
    ):
        assert float(weights[name]) > 0.0

    assert cfg["autonomous_fund"]["enabled"] is True
    assert cfg["autonomous_fund"]["research_interval_seconds"] <= 3600
    assert cfg["autonomous_fund"]["research_top_markets"] >= 5
    assert cfg["adaptive_learning"]["enabled"] is True
    assert cfg["adaptive_learning"]["min_samples"] <= 6
    assert cfg["adaptive_learning"]["change_cooldown"] <= 3
    assert cfg["shadow_lab"]["enabled"] is True
    assert cfg["shadow_lab"]["dynamic_markets_per_strategy"] >= 16


def test_bitvavo_aggressive_canary_profile_preserves_hard_risk():
    import yaml
    from pathlib import Path

    cfg = yaml.safe_load(Path("config.yaml").read_text())

    fund = cfg["fund"]
    assert fund["max_portfolio_drawdown_pct"] == 10.0
    assert fund["max_daily_loss_pct"] == 3.0
    assert fund["max_single_trade_pct"] == 20.0
    assert fund["min_cash_reserve_pct"] == 20.0

    auto = cfg["autonomous_execution"]
    assert auto["min_score"] >= 85.0
    assert auto["allow_margin"] is False
    assert auto["allow_futures"] is False
    assert auto["allow_borrowing"] is False
    assert auto["allow_leverage"] is False
    assert auto["allow_martingale"] is False

    strategies = cfg["strategies"]
    for key in ("market_maker", "grid", "grid_eth", "shadow_canary", "sniper"):
        assert strategies[key]["enabled"] is True
        assert strategies[key]["live_capable"] is True

    assert strategies["market_maker"]["max_order_eur"] <= 5
    assert strategies["grid_eth"]["max_order_eur"] <= 5
    assert strategies["sniper"]["max_order_eur"] <= 5
    assert strategies["arbitrage"]["enabled"] is True
    assert strategies["arbitrage"]["live_capable"] is False

    gate = cfg["live_evidence_gate"]
    assert gate["recovery_order_eur"] <= 5.0
    assert gate["recovery_min_score"] >= 85.0
    assert gate["recovery_min_confidence"] >= 0.62
    assert gate["recovery_min_signal_strength"] >= 62.0

    assert strategies["grid"]["protection_stop_loss_pct"] <= 1.25
    assert strategies["grid_eth"]["protection_stop_loss_pct"] <= 1.25
