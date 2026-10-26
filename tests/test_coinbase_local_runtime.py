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
    assert auto["max_daily_loss_pct"] == 3.0
    assert auto["max_drawdown_pct"] == 10.0


def test_real_local_env_is_gitignored():
    ignore = Path(".gitignore").read_text("utf-8")
    assert ".env.coinbase.local" in ignore
