from autotrader.core.order_manager import OrderManager, OrderSide, OrderType, OrderStatus
from autotrader.core.profit_engine import ProfitEngine
from autotrader.core.risk_manager import RiskManager
from autotrader.strategies.market_maker import MarketMaker
from autotrader.strategies.sniper_bot import SniperBot


def _deps():
    return OrderManager(), RiskManager(), ProfitEngine()


def test_market_maker_does_not_synthesize_pnl():
    om, rm, pe = _deps()
    s = MarketMaker(om, rm, pe, {
        "enabled": True,
        "symbol": "BTC-EUR",
        "exchange": "bitvavo",
        "order_size": 0.001,
        "target_spread": 1.0,
        "estimated_fee_pct": 0.1,
        "estimated_slippage_pct": 0.01,
    })
    s.start()
    s._config["_mid_price"] = 100000.0
    s.tick()
    assert pe.total_pnl() == 0
    assert len(om.open_orders("MarketMaker")) == 2


def test_disabled_strategy_does_not_run():
    om, rm, pe = _deps()
    s = SniperBot(om, rm, pe, {"enabled": False})
    assert not s.is_enabled
    s.start()
    assert not s.is_running


def test_order_manager_only_marks_fills_when_updated():
    om, rm, pe = _deps()
    o = om.register(Order(
        exchange="bitvavo", symbol="BTC-EUR", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=0.001
    ))
    assert o.status == OrderStatus.PENDING
    assert pe.total_pnl() == 0
