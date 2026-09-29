import os

from autotrader.api import server


class Journal:
    def strategy_market_state(self, market, strategy):
        return {
            "latest_side": "sell",
            "latest_status": "new",
            "latest_amount": "0.0001",
            "fill_count": 3,
            "nonterminal_count": 1,
            "net_base_inventory": "0.0001",
            "average_entry_price": "74100",
        }


class Agent:
    _bitvavo = type("Adapter", (), {"journal": Journal()})()

    def list_strategies(self):
        return {
            "market_maker": {
                "enabled": True,
                "live_capable": True,
                "running": True,
            }
        }


def _set_live_env(monkeypatch):
    values = {
        "EXECUTION_MODE": "live",
        "LIVE_EXECUTION_APPROVED": "true",
        "LIVE_EXECUTION_ADAPTER_INSTALLED": "true",
        "EMERGENCY_STOP": "false",
        "LIVE_TRADING_CONFIRMATION": "I_UNDERSTAND_LIVE_ORDERS",
        "BITVAVO_LIVE_TRADING": "true",
        "BITVAVO_DRY_RUN": "false",
        "BITVAVO_API_KEY": "present",
        "BITVAVO_API_SECRET": "present",
        "AUTOTRADER_CONTROL_TOKEN": "present",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _install_common(monkeypatch):
    _set_live_env(monkeypatch)
    monkeypatch.setattr(server, "get_agent", lambda: Agent())
    monkeypatch.setattr(server, "_cached_bitvavo_security", lambda: {"passed": True})
    server.app.state.execution_gateway = type(
        "Gateway",
        (),
        {"mode": type("Mode", (), {"value": "live"})()},
    )()


def test_prearm_requires_exchange_to_be_clear(monkeypatch):
    _install_common(monkeypatch)
    server.app.state.live_armed = False
    monkeypatch.setattr(
        server,
        "_cached_live_preflight",
        lambda: {
            "passed": False,
            "market_rules_passed": True,
            "open_orders_clear": False,
            "all_open_orders_bot_owned": True,
            "strategies": [],
        },
    )

    result = server.live_readiness()

    assert result["ready"] is False
    assert result["gates"]["exchange_order_state_safe"] is False


def test_armed_runtime_accepts_only_bot_owned_open_orders(monkeypatch):
    _install_common(monkeypatch)
    server.app.state.live_armed = True
    monkeypatch.setattr(
        server,
        "_cached_live_preflight",
        lambda: {
            "passed": False,
            "market_rules_passed": True,
            "open_orders_clear": False,
            "all_open_orders_bot_owned": True,
            "strategies": [],
        },
    )

    result = server.live_readiness()

    assert result["ready"] is True
    assert result["gates"]["exchange_order_state_safe"] is True
    assert result["exchange_open_orders_clear"] is False


def test_armed_runtime_rejects_unknown_open_order(monkeypatch):
    _install_common(monkeypatch)
    server.app.state.live_armed = True
    monkeypatch.setattr(
        server,
        "_cached_live_preflight",
        lambda: {
            "passed": False,
            "market_rules_passed": True,
            "open_orders_clear": False,
            "all_open_orders_bot_owned": False,
            "strategies": [],
        },
    )

    result = server.live_readiness()

    assert result["ready"] is False
    assert result["gates"]["exchange_order_state_safe"] is False
