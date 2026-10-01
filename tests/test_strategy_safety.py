from autotrader.core.order_manager import OrderManager, OrderSide, OrderStatus, OrderType, Order
from autotrader.core.profit_engine import ProfitEngine
from autotrader.core.risk_manager import RiskManager
from autotrader.strategies.sniper_bot import SniperBot
from autotrader.strategies.grid_runner import GridRunner


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


def test_sniper_is_long_only_on_spot(tmp_path):
    om = OrderManager()
    strategy = SniperBot(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "XRP-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6,
            "momentum_pct": 0.5,
            "cooldown_seconds": 0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
        },
    )
    strategy.start()
    strategy._config["_current_price"] = 100.0
    strategy.tick()
    strategy._config["_current_price"] = 99.0
    strategy.tick()
    assert om.open_orders("SniperBot") == []


def test_sniper_tracks_confirmed_fill(tmp_path):
    strategy = SniperBot(
        OrderManager(),
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {"enabled": True},
    )
    order = Order("bitvavo", "XRP-EUR", OrderSide.BUY, OrderType.MARKET, 6.0, 1.0, strategy="SniperBot")
    strategy.on_fill(order, {"amount": "6", "price": "1.0"})
    assert strategy._position == 6.0
    assert strategy._entry_price == 1.0
    assert strategy._config["_bot_base_inventory"] == 6.0


def test_grid_buys_when_it_has_no_bot_inventory(tmp_path):
    om = OrderManager()
    strategy = GridRunner(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "SOL-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 0.8,
            "_current_price": 100.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 0.0,
            "_bot_base_inventory": 0.0,
            "_bot_average_entry_price": 0.0,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
        },
    )
    strategy.start()
    strategy.tick()
    orders = om.open_orders("GridRunner")
    assert len(orders) == 1
    assert orders[0].side is OrderSide.BUY


def test_grid_sells_only_bot_owned_inventory(tmp_path):
    om = OrderManager()
    strategy = GridRunner(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "SOL-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 0.8,
            "_current_price": 100.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 44.0,
            "_available_base": 0.06,
            "_bot_base_inventory": 0.06,
            "_bot_average_entry_price": 99.0,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
        },
    )
    strategy.start()
    strategy.tick()
    orders = om.open_orders("GridRunner")
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].quantity <= 0.06


def test_market_maker_dynamic_eur_sizing_supports_low_price_eur_market(tmp_path):
    from autotrader.strategies.market_maker import MarketMaker

    om = OrderManager()
    strategy = MarketMaker(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "DOGE-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "order_size": 0.0001,
            "min_order_size": 0.00000001,
            "max_order_size": 1000000000,
            "target_spread": 0.8,
            "cycle_exit_markup_pct": 0.8,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "inventory_cycle_mode": True,
            "quote_refresh_seconds": 0,
            "_mid_price": 0.08,
            "_current_price": 0.08,
            "_tick_size": 0.000001,
            "_min_order_base": 1.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 0.0,
            "_bot_base_inventory": 0.0,
            "_autonomous_entry_allowed": True,
        },
    )
    strategy.start()
    strategy.tick()
    orders = om.open_orders("MarketMaker")
    assert len(orders) == 1
    order = orders[0]
    assert order.side is OrderSide.BUY
    assert 5.0 <= order.quantity * order.price <= 7.0
    ratio = order.price / 0.000001
    assert abs(ratio - round(ratio)) < 1e-6
