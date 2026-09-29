from autotrader.agent import AutoTrader
from autotrader.core.order_manager import OrderManager
from autotrader.core.profit_engine import ProfitEngine
from autotrader.core.risk_manager import RiskManager
from autotrader.strategies.market_maker import MarketMaker
from autotrader.strategies.sniper_bot import SniperBot


class DummyStrategy:
    def __init__(self):
        self.is_running = True
        self.observe_calls = 0
        self.tick_calls = 0

    def observe(self):
        self.observe_calls += 1

    def tick(self):
        self.tick_calls += 1


class DummyExecutor:
    def __init__(self):
        self.submit_calls = 0

    def submit_pending(self):
        self.submit_calls += 1


def test_live_disarmed_agent_observes_without_execution(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    strategy = DummyStrategy()
    executor = DummyExecutor()

    agent = AutoTrader.__new__(AutoTrader)
    agent._strategies = {"dummy": strategy}
    agent._executor = executor
    agent._is_live_armed = lambda: False

    agent.tick_all()

    assert strategy.observe_calls == 1
    assert strategy.tick_calls == 0
    assert executor.submit_calls == 0


def test_live_armed_agent_ticks_and_submits(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    strategy = DummyStrategy()
    executor = DummyExecutor()

    agent = AutoTrader.__new__(AutoTrader)
    agent._strategies = {"dummy": strategy}
    agent._executor = executor
    agent._is_live_armed = lambda: True

    agent.tick_all()

    assert strategy.observe_calls == 0
    assert strategy.tick_calls == 1
    assert executor.submit_calls == 1


def test_market_maker_observe_warms_adaptive_state_without_order(tmp_path):
    om = OrderManager()
    strategy = MarketMaker(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "adaptive_enabled": True,
            "target_spread": 0.8,
            "adaptive_ema_alpha": 0.2,
            "adaptive_min_spread_pct": 0.65,
            "adaptive_max_spread_pct": 1.5,
            "adaptive_volatility_multiplier": 4.0,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
        },
    )
    strategy.start()
    strategy._config["_mid_price"] = 100.0
    strategy.observe()
    strategy._config["_mid_price"] = 101.0
    strategy.observe()

    assert strategy._config["_adaptive_samples"] == 1
    assert om.open_orders("MarketMaker") == []


def test_sniper_observe_warms_reference_without_order(tmp_path):
    om = OrderManager()
    strategy = SniperBot(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {"enabled": True},
    )
    strategy.start()
    strategy._config["_current_price"] = 2.0
    strategy.observe()

    assert strategy._prev_price == 2.0
    assert strategy._config["_warmup_samples"] == 1
    assert om.open_orders("SniperBot") == []
