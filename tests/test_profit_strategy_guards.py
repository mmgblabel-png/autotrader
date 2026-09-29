from autotrader.core.order_manager import OrderManager
from autotrader.core.profit_engine import ProfitEngine
from autotrader.core.risk_manager import RiskManager
from autotrader.strategies.grid_runner import GridRunner
from autotrader.strategies.market_maker import MarketMaker
from autotrader.strategies.sniper_bot import SniperBot


def _deps(tmp_path):
    return OrderManager(), RiskManager(), ProfitEngine(export_dir=str(tmp_path))


def test_market_maker_pauses_new_buy_when_target_edge_is_too_small(tmp_path):
    om, rm, pe = _deps(tmp_path)
    strategy = MarketMaker(
        om, rm, pe,
        {
            "enabled": True,
            "symbol": "BTC-EUR",
            "exchange": "bitvavo",
            "order_size": 0.0001,
            "min_order_size": 0.0001,
            "max_order_size": 0.0001,
            "target_spread": 0.80,
            "cycle_exit_markup_pct": 0.80,
            "inventory_cycle_mode": True,
            "quote_refresh_seconds": 0,
            "_mid_price": 74000,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50,
            "_available_base": 0,
            "_bot_base_inventory": 0,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
            "_required_entry_edge_pct": 0.90,
        },
    )
    strategy.start()
    strategy.tick()
    assert om.open_orders("MarketMaker") == []


def test_grid_pauses_new_buy_when_target_edge_is_too_small(tmp_path):
    om, rm, pe = _deps(tmp_path)
    strategy = GridRunner(
        om, rm, pe,
        {
            "enabled": True,
            "symbol": "SOL-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 0.8,
            "_current_price": 100,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50,
            "_available_base": 0,
            "_bot_base_inventory": 0,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
            "_required_entry_edge_pct": 0.90,
        },
    )
    strategy.start()
    strategy.tick()
    assert om.open_orders("GridRunner") == []


def test_sniper_pauses_entry_when_take_profit_cannot_cover_policy(tmp_path):
    om, rm, pe = _deps(tmp_path)
    strategy = SniperBot(
        om, rm, pe,
        {
            "enabled": True,
            "symbol": "XRP-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6,
            "momentum_pct": 0.5,
            "take_profit_pct": 1.0,
            "stop_loss_pct": 0.3,
            "cooldown_seconds": 0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50,
            "_available_base": 0,
            "_bot_base_inventory": 0,
            "_exchange_open_orders_snapshot_ready": True,
            "_exchange_open_order_count": 0,
            "_required_entry_edge_pct": 1.10,
        },
    )
    strategy.start()
    strategy._config["_current_price"] = 1.0
    strategy.tick()
    strategy._config["_current_price"] = 1.01
    strategy.tick()
    assert om.open_orders("SniperBot") == []
