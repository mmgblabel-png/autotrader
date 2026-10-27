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
    assert auto["daily_trade_target"] == 10
    assert auto["daily_profit_target_eur"] == 1.0
    assert auto["stop_after_daily_profit_target"] is False
    assert auto["high_risk_fallback"] is True
    assert auto["high_risk_min_live_net_edge_bps"] == 0.0
    assert auto["high_risk_max_spread_bps"] == 45.0
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
    assert opportunity["daily_trade_target"] == 10
    assert opportunity["daily_profit_target_eur"] == 1.0
    assert opportunity["high_risk_enabled"] is True
    assert opportunity["high_risk_min_recent_momentum_bps"] == 3
    assert opportunity["high_risk_max_spread_bps"] == 45
    assert opportunity["realtime_product_limit"] == 20
    assert opportunity["realtime_min_edge_bps"] == 4
    assert opportunity["orderbook_imbalance_weight_bps"] == 22
    assert opportunity["trade_flow_weight_bps"] == 15
    assert "EUR" in opportunity["quote_currencies"]


def test_real_local_env_is_gitignored():
    ignore = Path(".gitignore").read_text("utf-8")
    assert ".env.coinbase.local" in ignore
