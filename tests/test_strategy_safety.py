import time

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


def test_grid_pauses_buy_during_execution_cancel_cooldown(tmp_path):
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
            "_execution_cancel_cooldown_until": time.time() + 90.0,
        },
    )
    strategy.start()
    strategy.tick()
    assert om.open_orders("GridRunner") == []


def test_grid_clears_stale_protection_before_flat_reentry(tmp_path):
    om = OrderManager()
    strategy = GridRunner(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "ADA-EUR",
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
            "_protective_exit_requested": True,
            "_protection_pending_action": "stop_loss",
            "_protection_entry_price": 220.0,
            "_protection_peak_price": 225.0,
        },
    )
    strategy.start()
    strategy.tick()
    orders = om.open_orders("GridRunner")
    assert len(orders) == 1
    assert orders[0].side is OrderSide.BUY
    assert strategy._config["_protective_exit_requested"] is False
    assert strategy._config["_protection_pending_action"] == ""
    assert strategy._config["_protection_entry_price"] == 0.0


def test_market_switch_resets_market_specific_protection_state(tmp_path):
    strategy = GridRunner(
        OrderManager(),
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "QNT-EUR",
            "_bot_base_inventory": 0.0,
            "_protective_exit_requested": True,
            "_protection_pending_action": "trailing_protection",
            "_protection_entry_price": 220.0,
            "_protection_peak_price": 230.0,
            "_protection_partial_taken": True,
        },
    )
    strategy.on_market_switch("QNT-EUR", "ADA-EUR")
    assert strategy._config["_protective_exit_requested"] is False
    assert strategy._config["_protection_pending_action"] == ""
    assert strategy._config["_protection_entry_price"] == 0.0
    assert strategy._config["_protection_peak_price"] == 0.0
    assert strategy._config["_protection_partial_taken"] is False


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


def test_grid_ignores_subminimum_dust_instead_of_retrying_sell(tmp_path):
    om = OrderManager()
    strategy = GridRunner(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "DOGE-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 0.8,
            "_current_price": 0.085,
            "_min_order_base": 0.0,
            "_min_order_quote": 5.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 11.8,
            "_bot_base_inventory": 11.8,
            "_bot_average_entry_price": 0.084,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
            "_autonomous_entry_allowed": False,
        },
    )
    strategy.start()
    strategy.tick()
    assert om.open_orders("GridRunner") == []
    assert strategy._config["_dust_inventory_ignored"] is True
    assert strategy._config["_dust_base_inventory"] == 11.8


def test_grid_kill_switch_blocks_entries_but_allows_owned_exit(tmp_path):
    from autotrader.core.risk_manager import StrategyRiskConfig

    om = OrderManager()
    rm = RiskManager({"GridRunner": StrategyRiskConfig(max_daily_loss=0.01)})
    rm.record_loss("GridRunner", 0.02)
    strategy = GridRunner(
        om,
        rm,
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "SOL-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 0.8,
            "_current_price": 100.0,
            "_min_order_base": 0.01,
            "_min_order_quote": 5.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 0.1,
            "_bot_base_inventory": 0.1,
            "_bot_average_entry_price": 95.0,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
        },
    )
    strategy.start()
    strategy.tick()
    orders = om.open_orders("GridRunner")
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL


def test_market_maker_kill_switch_allows_risk_reducing_sell(tmp_path):
    from autotrader.core.risk_manager import StrategyRiskConfig
    from autotrader.strategies.market_maker import MarketMaker

    om = OrderManager()
    rm = RiskManager({"MarketMaker": StrategyRiskConfig(max_daily_loss=0.01)})
    rm.record_loss("MarketMaker", 0.02)
    strategy = MarketMaker(
        om,
        rm,
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "SUI-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "target_spread": 0.8,
            "cycle_exit_markup_pct": 0.8,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "inventory_cycle_mode": True,
            "quote_refresh_seconds": 0,
            "_mid_price": 1.0,
            "_current_price": 1.0,
            "_min_order_base": 1.0,
            "_min_order_quote": 5.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 8.0,
            "_bot_base_inventory": 8.0,
            "_bot_average_entry_price": 0.95,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
        },
    )
    strategy.start()
    strategy.tick()
    orders = om.open_orders("MarketMaker")
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL


def _autonomous_sniper_config(momentum_pct: float) -> dict:
    return {
        "enabled": True,
        "symbol": "AXS-EUR",
        "exchange": "bitvavo",
        "order_value_eur": 6.0,
        "momentum_pct": 0.5,
        "take_profit_pct": 1.5,
        "stop_loss_pct": 0.35,
        "cooldown_seconds": 0,
        "entry_attempt_cooldown_seconds": 1,
        "entry_max_slippage_pct": 0.12,
        "autonomous_min_momentum_pct": 0.12,
        "autonomous_max_momentum_pct": 0.80,
        "max_slippage_pct": 0.12,
        "_current_price": 1.1110,
        "_autonomous_entry_allowed": True,
        "_autonomous_signal_direction": "LONG",
        "_autonomous_signal_strength": 84.0,
        "_autonomous_min_signal_strength": 80.0,
        "_autonomous_momentum_pct": momentum_pct,
        "_required_entry_edge_pct": 0.75,
        "_live_balance_snapshot_ready": True,
        "_available_quote": 50.0,
        "_available_base": 0.0,
        "_bot_base_inventory": 0.0,
        "_bot_average_entry_price": 0.0,
        "_exchange_open_orders_snapshot_ready": True,
        "_exchange_open_order_count": 0,
    }


def test_sniper_high_router_score_without_real_momentum_does_not_enter(tmp_path):
    om = OrderManager()
    strategy = SniperBot(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        _autonomous_sniper_config(0.02),
    )
    strategy.start()
    strategy.tick()
    assert om.open_orders("SniperBot") == []


def test_sniper_uses_bounded_ioc_limit_entry_instead_of_market_chase(tmp_path):
    om = OrderManager()
    strategy = SniperBot(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        _autonomous_sniper_config(0.20),
    )
    strategy.start()
    strategy.tick()
    orders = om.open_orders("SniperBot")
    assert len(orders) == 1
    order = orders[0]
    assert order.side is OrderSide.BUY
    assert order.order_type is OrderType.LIMIT
    assert order.time_in_force == "IOC"
    assert order.post_only is False
    assert order.price <= 1.1110 * 1.0012 + 1e-12
    assert order.quantity * order.price <= 6.000001


def test_grid_recovery_canary_is_capped_to_small_notional(tmp_path):
    om = OrderManager()
    strategy = GridRunner(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "SOL-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 12.0,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 1.0,
            "_current_price": 100.0,
            "_min_order_quote": 5.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 0.0,
            "_bot_base_inventory": 0.0,
            "_bot_average_entry_price": 0.0,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
            "_autonomous_entry_allowed": True,
            "_evidence_entry_blocked": True,
            "_evidence_recovery_allowed": True,
            "_evidence_recovery_order_eur": 5.5,
            "_autonomous_score": 95.0,
            "_autonomous_confidence": 0.85,
            "_autonomous_signal_strength": 90.0,
        },
    )
    strategy.start()
    strategy.tick()

    orders = om.open_orders("GridRunner")
    assert len(orders) == 1
    order = orders[0]
    assert order.side is OrderSide.BUY
    assert order.quantity * order.price <= 5.500001
    assert order.quantity * order.price >= 5.0
    assert strategy._config["_evidence_recovery_last_attempt_at"] > 0
    assert strategy._config["_evidence_recovery_allowed"] is False


def test_grid_tighter_stop_loss_triggers_protective_exit(tmp_path):
    om = OrderManager()
    strategy = GridRunner(
        om,
        RiskManager(),
        ProfitEngine(export_dir=str(tmp_path)),
        {
            "enabled": True,
            "symbol": "W-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 1.0,
            "protection_stop_loss_pct": 1.25,
            "protection_trailing_activation_pct": 0.90,
            "protection_trailing_drawdown_pct": 0.75,
            "_current_price": 98.70,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 0.10,
            "_bot_base_inventory": 0.10,
            "_bot_average_entry_price": 100.0,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
        },
    )
    strategy.start()
    strategy.tick()

    orders = om.open_orders("GridRunner")
    assert len(orders) == 1
    order = orders[0]
    assert order.side is OrderSide.SELL
    assert order.order_type is OrderType.MARKET
    assert strategy._config["_protection_pending_action"] == "stop_loss"
