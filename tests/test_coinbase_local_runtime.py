from pathlib import Path

import yaml

from autotrader.api.coinbase_local_server import app


def test_coinbase_local_server_exposes_only_coinbase_control_surface():
    paths = {route.path for route in app.routes}
    assert "/" in paths
    assert "/coinbase-dashboard" in paths
    assert "/api/health" in paths
    assert "/api/coinbase/dashboard/snapshot" in paths
    assert "/api/coinbase/live/readiness" in paths
    assert "/api/coinbase/live/activate" in paths
    assert "/api/coinbase/live/deactivate" in paths
    assert not any("bitvavo" in path.lower() for path in paths)


def test_coinbase_local_server_does_not_import_other_exchange_runtime():
    source = Path("autotrader/api/coinbase_local_server.py").read_text("utf-8").lower()
    assert "from autotrader.agent import" not in source
    assert "autotrader.connectors.bitvavo" not in source
    assert "autotrader.core.market_universe" not in source
    assert "coinbaseautonomousexecutor" in source
    assert "coinbasezscore" in source
    assert "coinbaserealtimeorderflowengine" in source


def test_coinbase_local_compose_is_loopback_only_and_hardened():
    payload = yaml.safe_load(Path("docker-compose.coinbase.local.yml").read_text("utf-8"))
    service = payload["services"]["coinbase-risktrader"]
    assert service["ports"] == ["127.0.0.1:8787:8000"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["cap_add"] == ["CHOWN", "SETUID", "SETGID"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["env_file"] == [".env.coinbase.local"]
    command = " ".join(service["command"])
    assert "autotrader.api.coinbase_local_server:app" in command
    assert "autotrader.api.server:app" not in command


def test_coinbase_local_config_is_risktrader_and_portfolio_isolated():
    cfg = yaml.safe_load(Path("config.coinbase.local.yaml").read_text("utf-8"))
    auto = cfg["coinbase_autonomous_execution"]
    assert auto["require_isolated_portfolio"] is True
    assert auto["supported_products"] == ["BTC-EUR", "BTC-USDC"]
    assert auto["managed_capital_pct"] == 100.0
    assert auto["cash_reserve_pct"] == 0.0
    assert auto["max_single_trade_pct"] == 100.0
    assert auto["full_capacity"] is True
    assert auto["require_shadow_promotion"] is False
    assert auto["allow_dynamic_products"] is True
    assert auto["maker_first"] is True
    assert auto["maker_first_exit"] is True
    assert auto["maker_exit_market_fallback"] is False
    assert auto["maker_entry_market_fallback"] is False
    assert auto["max_taker_entry_fee_bps"] == 60.0
    assert auto["max_taker_entry_slippage_bps"] == 35.0
    assert auto["submission_retry_after_seconds"] == 20
    assert auto["submission_abandon_after_seconds"] == 90
    assert auto["assumed_exit_fee_bps"] == 25.0
    assert auto["min_live_net_edge_bps"] == 15.0
    assert auto["max_spread_bps"] == 15.0
    assert auto["high_risk_min_live_net_edge_bps"] >= auto["min_live_net_edge_bps"]
    assert auto["exploration_enabled"] is False
    assert auto["exploration_trade_fraction_pct"] == 20.0
    assert auto["exploration_min_forecast_bps"] == 5.0
    assert auto["exploration_max_negative_edge_bps"] == 0.0
    assert auto["exploration_max_spread_bps"] == 15.0
    assert auto["daily_trade_target"] == 10
    assert auto["daily_profit_target_eur"] == 1.0
    assert auto["stop_after_daily_profit_target"] is False
    assert auto["high_risk_fallback"] is False
    assert auto["high_risk_min_live_net_edge_bps"] == 15.0
    assert auto["high_risk_max_spread_bps"] == 15.0
    assert auto["day_timezone"] == "Europe/Amsterdam"
    assert auto["max_daily_loss_pct"] == 3.0
    assert auto["max_drawdown_pct"] == 10.0
    realtime = cfg["coinbase_realtime_orderflow"]
    assert realtime["enabled"] is True
    assert realtime["max_products"] == 20
    assert realtime["depth_levels"] == 10
    assert realtime["trade_window_seconds"] == 60
    opportunity = cfg["coinbase_opportunity_engine"]
    assert opportunity["enabled"] is True
    assert opportunity["max_spread_bps"] == 15
    assert opportunity["daily_trade_target"] == 10
    assert opportunity["daily_profit_target_eur"] == 1.0
    assert opportunity["high_risk_enabled"] is False
    assert opportunity["high_risk_min_recent_momentum_bps"] == 3
    assert opportunity["high_risk_max_spread_bps"] == 15
    assert opportunity["realtime_product_limit"] == 20
    assert opportunity["realtime_min_edge_bps"] == 8
    assert opportunity["orderbook_imbalance_weight_bps"] == 22
    assert opportunity["trade_flow_weight_bps"] == 15
    assert "EUR" in opportunity["quote_currencies"]


def test_real_local_env_is_gitignored():
    ignore = Path(".gitignore").read_text("utf-8")
    assert ".env.coinbase.local" in ignore


def test_coinbase_local_compose_enables_existing_btc_seed():
    text = Path("docker-compose.coinbase.local.yml").read_text(encoding="utf-8")
    assert 'COINBASE_ALLOW_EXISTING_BTC_SEED: "true"' in text


def test_coinbase_local_compose_requests_fail_closed_auto_arm():
    text = Path("docker-compose.coinbase.local.yml").read_text(encoding="utf-8")
    assert 'COINBASE_AUTO_ARM_ON_START: "true"' in text


def test_coinbase_local_auto_arm_still_requires_readiness_gates():
    source = Path("autotrader/api/coinbase_local_server.py").read_text("utf-8")
    assert 'COINBASE_AUTO_ARM_ON_START' in source
    assert 'test_ready = await asyncio.to_thread(_executor_readiness, armed=True)' in source
    assert 'if not failed:' in source
    assert 'app.state.live_armed = True' in source
    assert 'app.state.arm_store.write(True, source="startup_auto_arm")' in source


def test_coinbase_local_preserves_live_intent_for_gate_recovery():
    source = Path("autotrader/api/coinbase_local_server.py").read_text("utf-8")
    assert 'app.state.arm_store.write(True, source="startup_auto_arm")' in source
    assert "async def _arm_recovery_loop()" in source
    assert "if not bool(app.state.live_armed) and app.state.arm_store.should_resume()" in source
    assert 'asyncio.create_task(_arm_recovery_loop(), name="coinbase-local-arm-recovery")' in source
    deactivate = source.split('@app.post("/api/coinbase/live/deactivate")', 1)[1]
    assert "app.state.arm_store.write(False)" in deactivate


def test_coinbase_local_startup_reconciles_risk_before_live_resume():
    source = Path("autotrader/api/coinbase_local_server.py").read_text("utf-8")
    reconcile_at = source.index("reconcile_runtime_state")
    resume_at = source.index("arm_store.should_resume")
    assert reconcile_at < resume_at


def test_coinbase_live_control_uses_authenticated_dashboard_session():
    server = Path("autotrader/api/coinbase_local_server.py").read_text("utf-8")
    html = Path("autotrader/api/coinbase_dashboard_html.py").read_text("utf-8")
    activate = server.split('@app.post("/api/coinbase/live/activate")', 1)[1].split('@app.post("/api/coinbase/live/deactivate")', 1)[0]
    deactivate = server.split('@app.post("/api/coinbase/live/deactivate")', 1)[1]
    assert "_require_control_token" not in activate
    assert "_require_control_token" not in deactivate
    assert "AUTOTRADER_CONTROL_TOKEN:" not in html
    assert 'confirmation:"I_UNDERSTAND_COINBASE_LIVE_ORDERS"' in html


def test_coinbase_operator_dashboard_uses_fresh_balances_and_current_action():
    server = Path("autotrader/api/coinbase_local_server.py").read_text("utf-8")
    html = Path("autotrader/api/coinbase_dashboard_html.py").read_text("utf-8")
    assert 'status["readiness"] = _executor_readiness' in server
    assert '"fallback_source"] = "readiness"' in server
    assert "Agent saldo totaal" in html
    assert "USDC beschikbaar" in html
    assert "Bot nu" in html
    assert "const rd=(r.readiness||a.readiness||r||{})" in html
    assert "Laatste actie" in html
    assert "scanCandidate" in html
    assert "todayTrades" in html


def test_coinbase_dashboard_snapshot_reads_nested_readiness_balances():
    server = Path("autotrader/api/coinbase_local_server.py").read_text("utf-8")
    html = Path("autotrader/api/coinbase_dashboard_html.py").read_text("utf-8")
    assert 'readiness.get("readiness")' in server
    assert 'const rd=(r.readiness||a.readiness||r||{})' in html
