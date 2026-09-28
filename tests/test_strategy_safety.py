from autotrader.core.order_manager import OrderManager, OrderSide, OrderStatus, OrderType, Order
from autotrader.core.profit_engine import ProfitEngine
from autotrader.core.risk_manager import RiskManager
from autotrader.strategies.sniper_bot import SniperBot


def test_disabled_strategy_cannot_start(tmp_path):
    strategy = SniperBot(OrderManager(), RiskManager(), ProfitEngine(export_dir=str(tmp_path)), {"enabled": False})
    strategy.start()
    assert strategy.is_enabled is False
    assert strategy.is_running is False


def test_order_registration_is_not_a_fill():
    om = OrderManager()
    order = om.register(Order("bitvavo", "BTC-EUR", OrderSide.BUY, OrderType.MARKET, 0.001))
    assert order.status == OrderStatus.PENDING
    assert not order.is_filled
