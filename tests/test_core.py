"""Basic smoke tests for AutoTrader core modules."""

import pytest

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


def test_profit_engine_export_json(tmp_path):
    pe = ProfitEngine(export_dir=str(tmp_path))
    pe.record_realized_pnl("arb", 10.0)
    path = pe.export_json("test.json")
    import json
    import os
    assert os.path.exists(path)
    data = json.load(open(path))
    assert "arb" in data


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
    assert len(om.open_orders()) >= 0


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
