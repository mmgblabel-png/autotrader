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
            "arbitrage": {"enabled": False, "live_capable": False},
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


def test_approved_runtime_selection_excludes_arbitrage():
    agent = _FakeAgent()
    state = agent.list_strategies()
    names = [
        name for name, item in state.items()
        if item.get("enabled") and item.get("live_capable")
    ]
    for name in names:
        agent.start(name)
    assert agent.started == ["market_maker", "grid", "sniper"]
    assert "arbitrage" not in agent.started


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
