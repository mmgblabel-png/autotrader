import time
from decimal import Decimal

from autotrader.core.execution_gateway import ExecutionGateway, ExecutionLimits, ExecutionRequest
from autotrader.core.order_manager import Order, OrderManager, OrderSide, OrderType
from autotrader.core.profit_engine import ProfitEngine
from autotrader.core.risk_manager import RiskManager
from autotrader.strategies.grid_runner import GridRunner


def _req(order_id: str, side: str, amount: str, *, risk_reducing: bool = False):
    return ExecutionRequest(
        "bitvavo",
        "SOL-EUR",
        side,
        Decimal(amount),
        Decimal("100"),
        Decimal("100"),
        order_id,
        time.time(),
        risk_reducing=risk_reducing,
    )


def test_risk_reducing_sell_bypasses_daily_exposure_and_does_not_increment():
    gateway = ExecutionGateway(
        ExecutionLimits(
            max_trade_eur=Decimal("10"),
            max_daily_exposure_eur=Decimal("10"),
            max_daily_loss_eur=Decimal("25"),
            max_slippage_bps=50,
        )
    )
    first = gateway.evaluate(_req("buy-0000000000000001", "BUY", "10"))
    assert first.accepted is True
    assert gateway.daily_exposure_eur == Decimal("10")

    blocked_buy = gateway.evaluate(_req("buy-0000000000000002", "BUY", "1"))
    assert blocked_buy.accepted is False
    assert blocked_buy.reason == "daily exposure limit exceeded"

    exit_sell = gateway.evaluate(
        _req("sell-000000000000001", "SELL", "7", risk_reducing=True)
    )
    assert exit_sell.accepted is True
    assert gateway.daily_exposure_eur == Decimal("10")


def test_non_reducing_sell_still_respects_daily_exposure():
    gateway = ExecutionGateway(
        ExecutionLimits(
            max_trade_eur=Decimal("10"),
            max_daily_exposure_eur=Decimal("10"),
            max_daily_loss_eur=Decimal("25"),
            max_slippage_bps=50,
        )
    )
    assert gateway.evaluate(_req("buy-0000000000000003", "BUY", "10")).accepted
    result = gateway.evaluate(_req("sell-000000000000002", "SELL", "1"))
    assert result.accepted is False
    assert result.reason == "daily exposure limit exceeded"


def test_grid_failure_enters_cooldown_and_prevents_immediate_entry_retry():
    om = OrderManager()
    strategy = GridRunner(
        order_manager=om,
        risk_manager=RiskManager(),
        profit_engine=ProfitEngine(),
        config={
            "enabled": True,
            "symbol": "SOL-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 0.8,
            "failure_cooldown_seconds": 60,
            "exposure_reject_cooldown_seconds": 300,
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
    failed = Order(
        exchange="bitvavo",
        symbol="SOL-EUR",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=0.06,
        price=99.0,
        strategy="GridRunner",
    )
    strategy.on_order_failure(
        failed,
        "bitvavo_error",
        "daily exposure limit exceeded",
    )
    assert strategy._config["_failure_cooldown_until"] > time.time() + 250

    strategy.tick()
    assert om.open_orders("GridRunner") == []


def test_grid_failure_cooldown_does_not_block_risk_reducing_exit():
    om = OrderManager()
    strategy = GridRunner(
        order_manager=om,
        risk_manager=RiskManager(),
        profit_engine=ProfitEngine(),
        config={
            "enabled": True,
            "symbol": "SOL-EUR",
            "exchange": "bitvavo",
            "order_value_eur": 6.0,
            "entry_offset_pct": 0.6,
            "exit_markup_pct": 0.8,
            "failure_cooldown_seconds": 60,
            "_failure_cooldown_until": time.time() + 300,
            "_current_price": 100.0,
            "_min_order_base": 0.01,
            "_min_order_quote": 5.0,
            "_live_balance_snapshot_ready": True,
            "_available_quote": 0.0,
            "_available_base": 0.10,
            "_bot_base_inventory": 0.10,
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


def test_risk_reducing_sell_bypasses_entry_trade_cap_and_loss_stop():
    gateway = ExecutionGateway(
        ExecutionLimits(
            max_trade_eur=Decimal("10"),
            max_daily_exposure_eur=Decimal("10"),
            max_daily_loss_eur=Decimal("5"),
            max_slippage_bps=50,
        )
    )
    gateway.daily_loss_eur = Decimal("5")
    result = gateway.evaluate(
        _req("sell-000000000000099", "SELL", "20", risk_reducing=True)
    )
    assert result.accepted is True


def test_grid_allocation_failure_uses_short_retry_cooldown():
    om = OrderManager()
    strategy = GridRunner(
        order_manager=om,
        risk_manager=RiskManager(),
        profit_engine=ProfitEngine(),
        config={
            "enabled": True,
            "allocation_failure_cooldown_seconds": 5,
        },
    )
    failed = Order(
        exchange="bitvavo",
        symbol="DOGE-EUR",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=70,
        price=0.085,
        strategy="GridRunner",
    )
    before = time.time()
    strategy.on_order_failure(failed, "allocation", "strategy per-order allocation exceeded")
    remaining = strategy._config["_failure_cooldown_until"] - before
    assert 4.0 <= remaining <= 6.0
