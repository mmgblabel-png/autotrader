from autotrader.api.server import _start_enabled_strategy_runtimes


class DummyAgent:
    def __init__(self):
        self.started = []

    def list_strategies(self):
        return {
            "market_maker": {"enabled": True, "live_capable": True},
            "arbitrage": {"enabled": True, "live_capable": False},
            "disabled_agent": {"enabled": False, "live_capable": True},
        }

    def start(self, name):
        self.started.append(name)
        return {"strategy": name, "status": "started"}


def test_startup_starts_all_enabled_runtimes_but_skips_disabled():
    agent = DummyAgent()

    started = _start_enabled_strategy_runtimes(agent)

    assert started == ["market_maker", "arbitrage"]
    assert agent.started == ["market_maker", "arbitrage"]
