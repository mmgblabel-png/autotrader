import asyncio
from types import SimpleNamespace

import pytest

from autotrader.api import server


class _FakeAgent:
    def __init__(self):
        self.started = []
        self._bitvavo = SimpleNamespace()
    def list_strategies(self):
        return {
            "market_maker": {"enabled": True, "live_capable": True},
            "grid": {"enabled": True, "live_capable": True},
            "sniper": {"enabled": True, "live_capable": True},
            "arbitrage": {"enabled": True, "live_capable": False},
        }
    def start(self, name):
        self.started.append(name)
        return {"strategy": name, "status": "started"}


def test_shadow_scan_never_reports_live_orders(monkeypatch):
    monkeypatch.setenv("ARBITRAGE_MARKETS", "")
    monkeypatch.setattr(server, "get_agent", lambda: SimpleNamespace(_bitvavo=SimpleNamespace()))
    payload = server._build_coinbase_bitvavo_shadow_scan()
    assert payload["mode"] == "shadow"
    assert payload["live_orders_sent"] is False
    assert payload["markets"] == []


def test_enabled_shadow_runtime_autostarts_but_remains_non_live_capable():
    agent = _FakeAgent()

    started = server._start_enabled_strategy_runtimes(agent)

    assert started == ["market_maker", "grid", "sniper", "arbitrage"]
    assert agent.started == started
    assert agent.list_strategies()["arbitrage"]["live_capable"] is False


def test_readiness_allows_enabled_shadow_runtime_and_blocks_disabled_running_runtime():
    states = {
        "grid": {"enabled": True, "live_capable": True, "running": True},
        "arbitrage": {"enabled": True, "live_capable": False, "running": True},
    }
    assert server._running_strategies_are_approved(states) is True

    states["disabled_agent"] = {
        "enabled": False,
        "live_capable": False,
        "running": True,
    }
    assert server._running_strategies_are_approved(states) is False


def test_shadow_loop_updates_cache_without_arming(monkeypatch):
    app = SimpleNamespace(
        state=SimpleNamespace(
            arbitrage_shadow_interval_seconds=0.001,
            live_armed=False,
        )
    )
    monkeypatch.setattr(
        server,
        "_build_coinbase_bitvavo_shadow_scan",
        lambda: {"mode": "shadow", "live_orders_sent": False, "markets": []},
    )

    async def scenario():
        task = asyncio.create_task(server._arbitrage_shadow_loop(app))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert app.state.arbitrage_shadow_cache["live_orders_sent"] is False
    assert app.state.live_armed is False
