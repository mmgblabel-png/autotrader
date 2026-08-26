"""Tests for AutoTrader core modules and API routes."""

import json

import pytest
from fastapi.testclient import TestClient

from autotrader.core.order_manager import Order, OrderManager, OrderSide, OrderType
from autotrader.core.risk_manager import RiskManager, StrategyRiskConfig
from autotrader.core.profit_engine import ProfitEngine, Trade


# ── OrderManager ─────────────────────────────────────────────────────────────

def test_order_manager_register_and_retrieve():
    om = OrderManager()
    order = Order(exchange="binance", symbol="BTC/USDT",
                  side=OrderSide.BUY, order_type=OrderType.LIMIT,
                  quantity=0.001, price=30000.0, strategy="test")
    om.register(order)
    assert om.get(order.order_id) is order


def test_order_manager_open_orders():
    om = OrderManager()
    o1 = Order(exchange="binance", symbol="BTC/USDT",
               side=OrderSide.BUY, order_type=OrderType.MARKET,
               quantity=0.001, strategy="s1")
    o2 = Order(exchange="binance", symbol="ETH/USDT",
               side=OrderSide.SELL, order_type=OrderType.MARKET,
               quantity=0.01, strategy="s2")
    om.register(o1)
    om.register(o2)
    assert len(om.open_orders("s1")) == 1
    assert len(om.open_orders()) == 2


# ── RiskManager ──────────────────────────────────────────────────────────────

def test_risk_manager_allows_normal_order():
    rm = RiskManager()
    rm.set_config("s1", StrategyRiskConfig(max_daily_loss=50, max_position_size=500))
    assert rm.check_order("s1", notional=100) is True


def test_risk_manager_blocks_oversized_order():
    rm = RiskManager()
    rm.set_config("s1", StrategyRiskConfig(max_position_size=100))
    assert rm.check_order("s1", notional=200) is False


def test_risk_manager_kill_switch_on_loss():
    rm = RiskManager()
    rm.set_config("s1", StrategyRiskConfig(max_daily_loss=10))
    rm.record_loss("s1", 11)
    assert rm.is_killed("s1") is True
    assert rm.check_order("s1", notional=1) is False


def test_risk_manager_kill_switch_on_errors():
    rm = RiskManager()
    rm.set_config("s1", StrategyRiskConfig(max_consecutive_errors=3))
    for _ in range(3):
        rm.record_error("s1")
    assert rm.is_killed("s1") is True


def test_risk_manager_reset():
    rm = RiskManager()
    rm.set_config("s1", StrategyRiskConfig(max_daily_loss=5))
    rm.record_loss("s1", 10)
    assert rm.is_killed("s1") is True
    rm.reset_daily()
    assert rm.is_killed("s1") is False


def test_risk_manager_status_shape():
    rm = RiskManager()
    rm.set_config("mm", StrategyRiskConfig(max_daily_loss=20))
    status = rm.status()
    assert "any_killed" in status
    assert "kill_switch" in status
    assert "daily_pnl" in status
    assert "max_daily_loss" in status
    assert "open_positions" in status
    assert "strategies" in status
    s = status["strategies"]["mm"]
    assert "daily_loss" in s and "max_daily_loss" in s and "kill_switch" in s


def test_risk_manager_kill_event_forwarded(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    rm = RiskManager()
    rm.set_profit_engine(pe)
    rm.set_config("s1", StrategyRiskConfig(max_daily_loss=5))
    rm.record_loss("s1", 6)
    evts = pe.events()
    assert any(e["kind"] == "risk" for e in evts)


# ── ProfitEngine ─────────────────────────────────────────────────────────────

def test_profit_engine_record_and_summary(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_trade(Trade(strategy="mm", symbol="BTC/USDT", side="BUY",
                          quantity=0.001, price=30000.0, fee=0.03))
    pe.record_realized_pnl("mm", 5.0)
    summary = pe.summary()
    assert "mm" in summary
    assert summary["mm"]["realized_pnl"] == 5.0
    assert summary["mm"]["wins"] == 1


def test_profit_engine_as_summary(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_realized_pnl("mm", 10.0)
    pe.record_realized_pnl("arb", -2.0)
    s = pe.as_summary()
    assert "total_pnl" in s
    assert "pnl_per_strategy" in s
    assert "by_strategy" in s
    assert "trade_count" in s
    assert "total_fees" in s


def test_profit_engine_total_pnl(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_realized_pnl("mm", 10.0)
    pe.record_realized_pnl("arb", -2.0)
    assert pe.total_pnl() == 8.0


def test_profit_engine_pnl_per_strategy(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_realized_pnl("mm", 5.0)
    d = pe.pnl_per_strategy()
    assert "mm" in d
    assert d["mm"] == 5.0


def test_profit_engine_last_trades(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    for i in range(5):
        pe.record_trade(Trade(strategy="mm", symbol="BTC/USDT", side="BUY",
                              quantity=0.001, price=float(30000 + i), fee=0.0))
    trades = pe.last_trades(3)
    assert len(trades) == 3


def test_profit_engine_recent_trades_sorted(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    for i in range(5):
        pe.record_trade(Trade(strategy="mm", symbol="BTC/USDT", side="BUY",
                              quantity=0.001, price=float(30000 + i), fee=0.0))
    trades = pe.recent_trades(limit=3)
    assert len(trades) == 3
    assert trades[0]["price"] >= trades[-1]["price"]


def test_profit_engine_events_on_large_pnl(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_realized_pnl("mm", 50.0)
    evts = pe.events()
    assert any(e["kind"] == "large_pnl" for e in evts)


def test_profit_engine_export_json(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_realized_pnl("arb", 10.0)
    path = pe.export_json("test.json")
    import os
    assert os.path.exists(path)
    data = json.load(open(path))
    assert "by_strategy" in data


def test_profit_engine_export_csv(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_trade(Trade(strategy="grid", symbol="SOL/USDT", side="SELL",
                          quantity=1.0, price=100.0, fee=0.1))
    path = pe.export_csv("test.csv")
    import os
    assert os.path.exists(path)


# ── Strategy smoke tests ──────────────────────────────────────────────────────

def _make_deps(tmp_path):
    om = OrderManager()
    rm = RiskManager()
    pe = ProfitEngine(export_dir=str(tmp_path))
    return om, rm, pe


def test_market_maker_tick(tmp_path):
    om, rm, pe = _make_deps(tmp_path)
    cfg = {"symbol": "BTC/USDT", "exchange": "test", "order_size": 0.001,
           "target_spread": 0.2, "_mid_price": 30000.0,
           "max_position_size": 500, "max_daily_loss": 50}
    rm.set_config("MarketMaker", StrategyRiskConfig(max_position_size=500, max_daily_loss=50))
    from autotrader.strategies.market_maker import MarketMaker
    mm = MarketMaker(om, rm, pe, cfg)
    mm.start()
    mm.tick()


def test_arbitrage_hunter_tick(tmp_path):
    om, rm, pe = _make_deps(tmp_path)
    cfg = {"symbol": "ETH/USDT", "order_size": 0.01, "min_profit_pct": 0.1,
           "_prices": {"binance": 1900.0, "kraken": 1910.0},
           "max_position_size": 1000, "max_daily_loss": 50}
    rm.set_config("ArbitrageHunter", StrategyRiskConfig(max_position_size=1000, max_daily_loss=50))
    from autotrader.strategies.arbitrage_hunter import ArbitrageHunter
    arb = ArbitrageHunter(om, rm, pe, cfg)
    arb.start()
    arb.tick()


def test_grid_runner_tick(tmp_path):
    om, rm, pe = _make_deps(tmp_path)
    cfg = {"symbol": "SOL/USDT", "exchange": "test",
           "upper_price": 110.0, "lower_price": 90.0, "grid_levels": 5,
           "order_size": 1.0, "_current_price": 100.0,
           "max_position_size": 500, "max_daily_loss": 50}
    rm.set_config("GridRunner", StrategyRiskConfig(max_position_size=500, max_daily_loss=50))
    from autotrader.strategies.grid_runner import GridRunner
    gr = GridRunner(om, rm, pe, cfg)
    gr.start()
    gr.tick()


def test_sniper_bot_tick(tmp_path):
    om, rm, pe = _make_deps(tmp_path)
    cfg = {"symbol": "BTC/USDT", "exchange": "test", "order_size": 0.001,
           "momentum_pct": 0.5, "take_profit_pct": 1.0, "stop_loss_pct": 0.3,
           "_current_price": 30150.0,
           "max_position_size": 200, "max_daily_loss": 15}
    rm.set_config("SniperBot", StrategyRiskConfig(max_position_size=200, max_daily_loss=15))
    from autotrader.strategies.sniper_bot import SniperBot
    sb = SniperBot(om, rm, pe, cfg)
    sb.start()
    sb._prev_price = 30000.0
    sb.tick()


# ── AutoTrader agent tests ────────────────────────────────────────────────────

def test_agent_start_stop_return_dicts(tmp_path):
    from autotrader.agent import AutoTrader
    import autotrader.api.deps as deps
    agent = AutoTrader.__new__(AutoTrader)
    agent._config = {}
    agent._om = OrderManager()
    agent._rm = RiskManager()
    agent._pe = ProfitEngine(export_dir=str(tmp_path))
    agent._rm.set_profit_engine(agent._pe)
    from autotrader.strategies.market_maker import MarketMaker
    agent._strategies = {"market_maker": MarketMaker(agent._om, agent._rm, agent._pe, {})}

    result = agent.start("market_maker")
    assert result["status"] == "started"
    result = agent.stop("market_maker")
    assert result["status"] == "stopped"
    result = agent.start("nonexistent")
    assert "error" in result


def test_agent_list_strategies(tmp_path):
    from autotrader.agent import AutoTrader
    agent = AutoTrader.__new__(AutoTrader)
    agent._config = {}
    agent._om = OrderManager()
    agent._rm = RiskManager()
    agent._pe = ProfitEngine(export_dir=str(tmp_path))
    agent._rm.set_profit_engine(agent._pe)
    from autotrader.strategies.market_maker import MarketMaker
    agent._strategies = {"market_maker": MarketMaker(agent._om, agent._rm, agent._pe, {})}

    strats = agent.list_strategies()
    assert "market_maker" in strats
    assert "running" in strats["market_maker"]


def test_agent_properties(tmp_path):
    from autotrader.agent import AutoTrader
    agent = AutoTrader.__new__(AutoTrader)
    agent._config = {}
    agent._om = OrderManager()
    agent._rm = RiskManager()
    agent._pe = ProfitEngine(export_dir=str(tmp_path))
    agent._rm.set_profit_engine(agent._pe)
    agent._strategies = {}

    assert agent.profit_engine is agent._pe
    assert agent.risk_manager is agent._rm


# ── API route tests ────────────────────────────────────────────────────────────

@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOTRADER_CONTROL_TOKEN", "test-control-token")
    import autotrader.api.deps as deps
    from autotrader.agent import AutoTrader
    from autotrader.api.server import app

    deps._agent = AutoTrader.__new__(AutoTrader)
    deps._agent._config = {}
    deps._agent._om = OrderManager()
    deps._agent._rm = RiskManager()
    deps._agent._pe = ProfitEngine(export_dir=str(tmp_path))
    deps._agent._rm.set_profit_engine(deps._agent._pe)
    deps._agent._strategies = {}

    from autotrader.strategies.market_maker import MarketMaker
    from autotrader.strategies.arbitrage_hunter import ArbitrageHunter
    from autotrader.strategies.grid_runner import GridRunner
    from autotrader.strategies.sniper_bot import SniperBot
    for key, cls in [("market_maker", MarketMaker), ("arbitrage", ArbitrageHunter),
                     ("grid", GridRunner), ("sniper", SniperBot)]:
        deps._agent._strategies[key] = cls(
            deps._agent._om, deps._agent._rm, deps._agent._pe, {}
        )

    with TestClient(
        app,
        raise_server_exceptions=True,
        headers={"X-AutoTrader-Token": "test-control-token"},
    ) as client:
        yield client

    deps._agent = None


def test_api_health(api_client):
    r = api_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_api_root_health(api_client):
    r = api_client.get("/")
    assert r.status_code == 200


def test_api_list_strategies(api_client):
    r = api_client.get("/api/strategies")
    assert r.status_code == 200
    data = r.json()
    assert "strategies" in data
    names = {s["name"] for s in data["strategies"]}
    assert "market_maker" in names


def test_api_strategy_status_compatibility(api_client):
    r = api_client.get("/strategies/status")
    assert r.status_code == 200
    assert r.json() == {
        "running": {
            "MarketMaker": False,
            "ArbitrageHunter": False,
            "GridRunner": False,
            "SniperBot": False,
        }
    }


def test_api_start_valid_strategy(api_client):
    r = api_client.post("/api/strategies/start", json={"name": "market_maker"})
    assert r.status_code == 200
    assert r.json()["status"] == "started"


def test_api_start_invalid_strategy(api_client):
    r = api_client.post("/api/strategies/start", json={"name": "unknown_strat"})
    assert r.status_code == 422


def test_api_strategy_control_rejects_invalid_token(api_client):
    response = api_client.post(
        "/api/strategies/start",
        json={"name": "market_maker"},
        headers={"X-AutoTrader-Token": "wrong-token"},
    )
    assert response.status_code == 401


def test_api_stop_strategy(api_client):
    api_client.post("/api/strategies/start", json={"name": "grid"})
    r = api_client.post("/api/strategies/stop", json={"name": "grid"})
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"


def test_api_pnl_summary(api_client):
    r = api_client.get("/api/pnl/summary")
    assert r.status_code == 200
    data = r.json()
    assert "total_pnl" in data
    assert "pnl_per_strategy" in data
    assert "by_strategy" in data
    assert "trade_count" in data


def test_api_recent_trades(api_client):
    r = api_client.get("/api/trades/recent?limit=10")
    assert r.status_code == 200
    assert "trades" in r.json()


def test_api_risk_status(api_client):
    r = api_client.get("/api/risk/status")
    assert r.status_code == 200
    data = r.json()
    assert "kill_switch" in data
    assert "daily_pnl" in data
    assert "max_daily_loss" in data
    assert "open_positions" in data


def test_api_pnl_events(api_client):
    r = api_client.get("/api/pnl/events")
    assert r.status_code == 200
    assert "events" in r.json()


def test_api_health_reports_paper_runtime(api_client):
    response = api_client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "paper"
    assert payload["runtime"]["ticker_running"] is True
    assert payload["runtime"]["tick_interval_seconds"] >= 0.1


def test_api_recent_trades_rejects_out_of_range_limit(api_client):
    assert api_client.get("/api/trades/recent?limit=0").status_code == 422
    assert api_client.get("/api/trades/recent?limit=201").status_code == 422


def test_api_pnl_events_rejects_out_of_range_limit(api_client):
    assert api_client.get("/api/pnl/events?limit=0").status_code == 422
    assert api_client.get("/api/pnl/events?limit=201").status_code == 422


def test_api_pnl_summary_matches_dashboard_strategy_shape(api_client):
    response = api_client.get("/api/pnl/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "paper"
    assert isinstance(payload["pnl_per_strategy"], list)
    rows = {row["name"]: row for row in payload["pnl_per_strategy"]}
    assert set(rows) == {"market_maker", "arbitrage", "grid", "sniper"}
    assert rows["market_maker"]["status"] == "stopped"
    assert "pnl_by_strategy" in payload


def test_api_dashboard_compatibility_routes(api_client):
    events = api_client.get("/api/events")
    assert events.status_code == 200
    assert isinstance(events.json(), list)

    history = api_client.get("/api/pnl/history")
    assert history.status_code == 200
    assert history.json() == {"history": []}

    credits = api_client.get("/api/wallet/credits?address=0xnot-used")
    assert credits.status_code == 200
    assert credits.json() == {"credits": 0, "mode": "paper"}


def test_api_risk_status_marks_paper_mode(api_client):
    response = api_client.get("/api/risk/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "paper"
    assert payload["slippage_alerts"] == []


# ── Base Mainnet readiness policy (offline, non-custodial) ────────────────────


def _mainnet_intent(**overrides):
    from decimal import Decimal

    from autotrader.blockchain.mainnet_policy import (
        BASE_MAINNET_CHAIN_ID,
        BASE_USDC,
        BASE_WETH,
        UNISWAP_V3_SWAP_ROUTER_02,
        TradeIntent,
    )

    payload = {
        "proposal_id": "proposal-7dc5b4a9e4c2",
        "chain_id": BASE_MAINNET_CHAIN_ID,
        "token_in": BASE_USDC,
        "token_out": BASE_WETH,
        "router": UNISWAP_V3_SWAP_ROUTER_02,
        "amount_in_usdc": Decimal("5"),
        "min_amount_out": Decimal("0.001"),
        "quoted_at_epoch": 1_000,
        "expires_at_epoch": 1_100,
        "slippage_bps": 20,
        "estimated_network_fee_eth": Decimal("0.0001"),
    }
    payload.update(overrides)
    return TradeIntent(**payload)


def _enabled_mainnet_policy(**overrides):
    from decimal import Decimal

    from autotrader.blockchain.mainnet_policy import MainnetExecutionPolicy

    payload = {
        "execution_enabled": True,
        "emergency_stop": False,
        "max_trade_usdc": Decimal("10"),
        "max_daily_usdc": Decimal("25"),
        "max_daily_loss_usdc": Decimal("5"),
        "max_slippage_bps": 30,
        "max_network_fee_eth": Decimal("0.001"),
    }
    payload.update(overrides)
    return MainnetExecutionPolicy(**payload)


def test_mainnet_policy_fails_closed_by_default():
    from autotrader.blockchain.mainnet_policy import MainnetExecutionPolicy, PolicyViolation

    with pytest.raises(PolicyViolation, match="disabled"):
        MainnetExecutionPolicy().validate(_mainnet_intent(), now_epoch=1_050)


def test_mainnet_policy_accepts_bounded_allowlisted_metadata_only_intent():
    policy = _enabled_mainnet_policy()
    intent = _mainnet_intent()
    policy.validate(intent, daily_used_usdc=0, now_epoch=1_050)
    summary = policy.proposal_summary(intent)
    assert summary["execution_capability"] == "not_implemented"
    assert summary["chain_id"] == 8453
    assert "data" not in summary and "signed" not in summary


def test_mainnet_policy_rejects_emergency_stop():
    from autotrader.blockchain.mainnet_policy import PolicyViolation

    with pytest.raises(PolicyViolation, match="Emergency stop"):
        _enabled_mainnet_policy(emergency_stop=True).validate(_mainnet_intent(), now_epoch=1_050)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("chain_id", 84532, "Base Mainnet"),
        ("token_out", "0x0000000000000000000000000000000000000001", "allowlisted"),
        ("router", "0x0000000000000000000000000000000000000002", "Router"),
        ("slippage_bps", 31, "Slippage"),
        ("expires_at_epoch", 1_050, "expired"),
        ("estimated_network_fee_eth", __import__("decimal").Decimal("0.01"), "network fee"),
    ],
)
def test_mainnet_policy_rejects_unsafe_intents(field, value, reason):
    from autotrader.blockchain.mainnet_policy import PolicyViolation

    with pytest.raises(PolicyViolation, match=reason):
        _enabled_mainnet_policy().validate(
            _mainnet_intent(**{field: value}), now_epoch=1_050
        )


def test_mainnet_policy_rejects_exposure_over_caps():
    from decimal import Decimal

    from autotrader.blockchain.mainnet_policy import PolicyViolation

    with pytest.raises(PolicyViolation, match="per-trade"):
        _enabled_mainnet_policy(max_trade_usdc=Decimal("4")).validate(
            _mainnet_intent(), now_epoch=1_050
        )
    with pytest.raises(PolicyViolation, match="daily exposure"):
        _enabled_mainnet_policy().validate(
            _mainnet_intent(), daily_used_usdc=Decimal("21"), now_epoch=1_050
        )


def test_mainnet_policy_rejects_unset_financial_caps():
    from decimal import Decimal

    from autotrader.blockchain.mainnet_policy import PolicyViolation

    for override, phrase in [
        ({"max_trade_usdc": Decimal("0")}, "Per-trade cap"),
        ({"max_daily_usdc": Decimal("0")}, "Daily exposure cap"),
        ({"max_network_fee_eth": Decimal("0")}, "Network-fee cap"),
    ]:
        with pytest.raises(PolicyViolation, match=phrase):
            _enabled_mainnet_policy(**override).validate(_mainnet_intent(), now_epoch=1_050)


def test_mainnet_policy_rejects_daily_loss_stop():
    from decimal import Decimal

    from autotrader.blockchain.mainnet_policy import PolicyViolation

    with pytest.raises(PolicyViolation, match="Daily loss stop"):
        _enabled_mainnet_policy(max_daily_loss_usdc=Decimal("2")).validate(
            _mainnet_intent(), daily_realized_loss_usdc=Decimal("2"), now_epoch=1_050
        )


def test_mainnet_policy_environment_defaults_fail_closed(monkeypatch):
    from autotrader.blockchain.mainnet_policy import MainnetExecutionPolicy

    for name in [
        "MAINNET_EXECUTION_ENABLED",
        "MAINNET_EMERGENCY_STOP",
        "MAINNET_MAX_TRADE_USDC",
        "MAINNET_MAX_DAILY_USDC",
        "MAINNET_MAX_DAILY_LOSS_USDC",
        "MAINNET_MAX_SLIPPAGE_BPS",
        "MAINNET_MAX_GAS_ETH",
    ]:
        monkeypatch.delenv(name, raising=False)
    policy = MainnetExecutionPolicy.from_environment()
    assert policy.execution_enabled is False
    assert policy.emergency_stop is True
    assert str(policy.max_trade_usdc) == "0"
    assert str(policy.max_daily_usdc) == "0"
    assert str(policy.max_daily_loss_usdc) == "0"
    assert policy.max_slippage_bps == 0
    assert str(policy.max_network_fee_eth) == "0"


def test_mainnet_policy_environment_invalid_values_fail_closed(monkeypatch):
    from autotrader.blockchain.mainnet_policy import MainnetExecutionPolicy

    monkeypatch.setenv("MAINNET_EXECUTION_ENABLED", "not-a-boolean")
    monkeypatch.setenv("MAINNET_EMERGENCY_STOP", "not-a-boolean")
    monkeypatch.setenv("MAINNET_MAX_TRADE_USDC", "-1")
    monkeypatch.setenv("MAINNET_MAX_DAILY_USDC", "nan")
    monkeypatch.setenv("MAINNET_MAX_DAILY_LOSS_USDC", "broken")
    monkeypatch.setenv("MAINNET_MAX_SLIPPAGE_BPS", "101")
    monkeypatch.setenv("MAINNET_MAX_GAS_ETH", "-0.01")
    policy = MainnetExecutionPolicy.from_environment()
    assert policy.execution_enabled is False
    assert policy.emergency_stop is True
    assert str(policy.max_trade_usdc) == "0"
    assert str(policy.max_daily_usdc) == "0"
    assert str(policy.max_daily_loss_usdc) == "0"
    assert policy.max_slippage_bps == 0
    assert str(policy.max_network_fee_eth) == "0"


def test_mainnet_policy_environment_explicit_values(monkeypatch):
    from autotrader.blockchain.mainnet_policy import MainnetExecutionPolicy

    monkeypatch.setenv("MAINNET_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("MAINNET_EMERGENCY_STOP", "false")
    monkeypatch.setenv("MAINNET_MAX_TRADE_USDC", "10")
    monkeypatch.setenv("MAINNET_MAX_DAILY_USDC", "25")
    monkeypatch.setenv("MAINNET_MAX_DAILY_LOSS_USDC", "5")
    monkeypatch.setenv("MAINNET_MAX_SLIPPAGE_BPS", "25")
    monkeypatch.setenv("MAINNET_MAX_GAS_ETH", "0.001")
    policy = MainnetExecutionPolicy.from_environment()
    assert policy.execution_enabled is True
    assert policy.emergency_stop is False
    assert str(policy.max_trade_usdc) == "10"
    assert str(policy.max_daily_usdc) == "25"
    assert str(policy.max_daily_loss_usdc) == "5"
    assert policy.max_slippage_bps == 25
    assert str(policy.max_network_fee_eth) == "0.001"


def test_api_strategies_status_alias_matches_legacy_route(api_client):
    legacy = api_client.get("/strategies/status")
    alias = api_client.get("/api/strategies/status")
    assert legacy.status_code == 200
    assert alias.status_code == 200
    assert alias.json() == legacy.json()


def test_api_mainnet_safety_defaults_to_nonexecuting(api_client, monkeypatch):
    for name in [
        "MAINNET_EXECUTION_ENABLED",
        "MAINNET_EMERGENCY_STOP",
        "MAINNET_MAX_TRADE_USDC",
        "MAINNET_MAX_DAILY_USDC",
        "MAINNET_MAX_DAILY_LOSS_USDC",
        "MAINNET_MAX_SLIPPAGE_BPS",
        "MAINNET_MAX_GAS_ETH",
    ]:
        monkeypatch.delenv(name, raising=False)
    response = api_client.get("/api/mainnet/safety")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "paper"
    assert payload["execution_enabled"] is False
    assert payload["emergency_stop"] is True
    assert payload["max_daily_loss_usdc"] == "0"
    assert payload["execution_capability"] == "not_implemented"
    assert payload["wallet_capability"] == "not_implemented"
    assert payload["broadcast_capability"] == "not_implemented"
