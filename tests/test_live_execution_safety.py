from autotrader.core.execution_coordinator import ExecutionCoordinator
from autotrader.core.order_manager import Order, OrderManager, OrderSide, OrderStatus, OrderType
from autotrader.core.profit_engine import ProfitEngine
from autotrader.strategies.market_maker import MarketMaker


class AllowRisk:
    def is_killed(self, _name):
        return False

    def check_order(self, _name, _notional):
        return True


class DummyProfit:
    pass


def test_live_market_maker_with_only_eur_quotes_buy_side():
    om = OrderManager()
    strategy = MarketMaker(
        order_manager=om,
        risk_manager=AllowRisk(),
        profit_engine=DummyProfit(),
        config={
            "enabled": True,
            "symbol": "BTC-EUR",
            "exchange": "bitvavo",
            "order_size": 0.0001,
            "min_order_size": 0.0001,
            "max_order_size": 0.0001,
            "target_spread": 0.80,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "quote_refresh_seconds": 0,
            "_mid_price": 70000.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 0.0,
        },
    )
    strategy.start()
    strategy.tick()

    orders = list(om._orders.values())
    assert len(orders) == 1
    assert orders[0].side is OrderSide.BUY


class FakeJournal:
    def __init__(self):
        self.strategies = {}

    def set_strategy(self, client_order_id, strategy):
        self.strategies[client_order_id] = strategy

    def get(self, _client_order_id):
        return None


class FilledAdapter:
    def __init__(self):
        self.journal = FakeJournal()

    def place_limit_order(self, market, side, amount, price, client_order_id):
        return {
            "clientOrderId": client_order_id,
            "market": market,
            "side": side,
            "status": "filled",
            "filledAmount": str(amount),
            "feePaid": "0.01",
            "fills": [
                {
                    "id": "fill-1",
                    "timestamp": 1700000000000,
                    "amount": str(amount),
                    "price": str(price),
                    "fee": "0.01",
                    "feeCurrency": "EUR",
                    "settled": True,
                }
            ],
        }


def test_real_exchange_fill_is_recorded_as_trade():
    om = OrderManager()
    pe = ProfitEngine(export_dir="/tmp/autotrader-test-exports")
    adapter = FilledAdapter()
    coordinator = ExecutionCoordinator(
        om,
        adapter,
        is_armed=lambda: True,
        profit_engine=pe,
    )
    order = om.register(
        Order(
            exchange="bitvavo",
            symbol="BTC-EUR",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.0001,
            price=70000.0,
            strategy="MarketMaker",
        )
    )

    result = coordinator.submit_pending()

    assert result[0]["status"] == "filled"
    assert order.status is OrderStatus.FILLED
    assert pe.as_summary()["trade_count"] == 1
    trade = pe.recent_trades(1)[0]
    assert trade["strategy"] == "MarketMaker"
    assert trade["symbol"] == "BTC-EUR"
    assert trade["side"] == "BUY"
    assert trade["quantity"] == 0.0001


def test_market_maker_sells_only_bot_owned_inventory():
    om = OrderManager()
    strategy = MarketMaker(
        order_manager=om,
        risk_manager=AllowRisk(),
        profit_engine=DummyProfit(),
        config={
            "enabled": True,
            "symbol": "BTC-EUR",
            "exchange": "bitvavo",
            "order_size": 0.0001,
            "min_order_size": 0.0001,
            "max_order_size": 0.0001,
            "target_spread": 0.80,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "quote_refresh_seconds": 0,
            "inventory_cycle_mode": True,
            "_mid_price": 70000.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 42.0,
            "_available_base": 0.0001,
            "_bot_base_inventory": 0.0001,
        },
    )
    strategy.start()
    strategy.tick()

    orders = list(om._orders.values())
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL


def test_market_maker_does_not_sell_unrelated_account_btc():
    om = OrderManager()
    strategy = MarketMaker(
        order_manager=om,
        risk_manager=AllowRisk(),
        profit_engine=DummyProfit(),
        config={
            "enabled": True,
            "symbol": "BTC-EUR",
            "exchange": "bitvavo",
            "order_size": 0.0001,
            "min_order_size": 0.0001,
            "max_order_size": 0.0001,
            "target_spread": 0.80,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "quote_refresh_seconds": 0,
            "inventory_cycle_mode": True,
            "_mid_price": 70000.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 42.0,
            "_available_base": 1.0,
            "_bot_base_inventory": 0.0,
        },
    )
    strategy.start()
    strategy.tick()

    orders = list(om._orders.values())
    assert len(orders) == 1
    assert orders[0].side is OrderSide.BUY


def test_market_maker_exit_never_below_entry_markup():
    om = OrderManager()
    strategy = MarketMaker(
        order_manager=om,
        risk_manager=AllowRisk(),
        profit_engine=DummyProfit(),
        config={
            "enabled": True,
            "symbol": "BTC-EUR",
            "exchange": "bitvavo",
            "order_size": 0.0001,
            "min_order_size": 0.0001,
            "max_order_size": 0.0001,
            "target_spread": 0.80,
            "cycle_exit_markup_pct": 0.80,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "quote_refresh_seconds": 0,
            "inventory_cycle_mode": True,
            "_mid_price": 73000.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 42.0,
            "_available_base": 0.0001,
            "_bot_base_inventory": 0.0001,
            "_bot_average_entry_price": 73539.0,
        },
    )
    strategy.start()
    strategy.tick()
    orders = list(om._orders.values())
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].price >= round(73539.0 * 1.008, 2)


def test_adaptive_spread_widens_after_price_shock():
    strategy = MarketMaker(
        order_manager=OrderManager(),
        risk_manager=AllowRisk(),
        profit_engine=DummyProfit(),
        config={
            "target_spread": 0.80,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "adaptive_enabled": True,
            "adaptive_ema_alpha": 1.0,
            "adaptive_min_spread_pct": 0.65,
            "adaptive_max_spread_pct": 2.0,
            "adaptive_volatility_multiplier": 4.0,
        },
    )
    first, _ = strategy._update_adaptive_state(70000.0)
    second, _ = strategy._update_adaptive_state(70700.0)
    assert first == 0.008
    assert second > first
    assert second <= 0.02


def test_adaptive_downtrend_guard_blocks_new_buy():
    om = OrderManager()
    strategy = MarketMaker(
        order_manager=om,
        risk_manager=AllowRisk(),
        profit_engine=DummyProfit(),
        config={
            "enabled": True,
            "symbol": "BTC-EUR",
            "exchange": "bitvavo",
            "order_size": 0.0001,
            "min_order_size": 0.0001,
            "max_order_size": 0.0001,
            "target_spread": 0.80,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "quote_refresh_seconds": 0,
            "inventory_cycle_mode": True,
            "adaptive_enabled": True,
            "adaptive_ema_alpha": 1.0,
            "adaptive_min_samples": 1,
            "adaptive_downtrend_guard_pct": 0.12,
            "_adaptive_prev_mid": 70000.0,
            "_mid_price": 69000.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 0.0,
            "_bot_base_inventory": 0.0,
            "_last_bot_sell_fill_at": 0.0,
        },
    )
    strategy.start()
    strategy.tick()
    assert list(om._orders.values()) == []


def test_market_maker_cooldown_blocks_immediate_rebuy(monkeypatch):
    import time
    om = OrderManager()
    now = time.time()
    strategy = MarketMaker(
        order_manager=om,
        risk_manager=AllowRisk(),
        profit_engine=DummyProfit(),
        config={
            "enabled": True,
            "symbol": "BTC-EUR",
            "exchange": "bitvavo",
            "order_size": 0.0001,
            "min_order_size": 0.0001,
            "max_order_size": 0.0001,
            "target_spread": 0.80,
            "estimated_fee_pct": 0.25,
            "estimated_slippage_pct": 0.05,
            "quote_refresh_seconds": 0,
            "cycle_cooldown_seconds": 60,
            "inventory_cycle_mode": True,
            "adaptive_enabled": False,
            "_mid_price": 74000.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 50.0,
            "_available_base": 0.0,
            "_bot_base_inventory": 0.0,
            "_last_bot_sell_fill_at": now,
        },
    )
    strategy.start()
    strategy.tick()
    assert list(om._orders.values()) == []
