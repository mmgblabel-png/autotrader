from decimal import Decimal

from autotrader.core.order_manager import Order, OrderManager, OrderSide, OrderType
from autotrader.core.strategy_allocator import StrategyAllocator


def config():
    return {
        "portfolio": {"global_live_budget_eur": 50, "max_total_open_orders": 4},
        "strategies": {
            "market_maker": {
                "symbol": "BTC-EUR",
                "live_capable": True,
                "allocation_eur": 15,
                "max_order_eur": 10,
                "max_open_orders": 1,
                "exclusive_symbol": True,
            },
            "grid": {
                "symbol": "SOL-EUR",
                "live_capable": True,
                "allocation_eur": 15,
                "max_order_eur": 7,
                "max_open_orders": 1,
                "exclusive_symbol": True,
            },
            "sniper": {
                "symbol": "XRP-EUR",
                "live_capable": True,
                "allocation_eur": 10,
                "max_order_eur": 7,
                "max_open_orders": 1,
                "exclusive_symbol": True,
            },
            "arbitrage": {
                "symbol": "ETH-EUR",
                "live_capable": False,
                "allocation_eur": 10,
                "max_order_eur": 7,
                "max_open_orders": 2,
            },
        },
    }


def test_allocator_accepts_separate_strategy_budgets():
    allocator = StrategyAllocator(config())
    om = OrderManager()
    btc = om.register(Order("bitvavo", "BTC-EUR", OrderSide.BUY, OrderType.LIMIT, 0.0001, 70000, strategy="MarketMaker"))
    decision = allocator.evaluate(btc, om.open_orders(), observed_price=Decimal("70000"))
    assert decision.accepted


def test_allocator_rejects_per_order_budget():
    allocator = StrategyAllocator(config())
    order = Order("bitvavo", "SOL-EUR", OrderSide.BUY, OrderType.LIMIT, 0.08, 100, strategy="GridRunner")
    decision = allocator.evaluate(order, [], observed_price=Decimal("100"))
    assert not decision.accepted
    assert "per-order" in decision.reason


def test_allocator_rejects_symbol_conflict():
    cfg = config()
    cfg["strategies"]["sniper"]["symbol"] = "BTC-EUR"
    allocator = StrategyAllocator(cfg)
    active = Order("bitvavo", "BTC-EUR", OrderSide.BUY, OrderType.LIMIT, 0.0001, 70000, strategy="MarketMaker")
    candidate = Order("bitvavo", "BTC-EUR", OrderSide.BUY, OrderType.MARKET, 0.00008, 70000, strategy="SniperBot")
    decision = allocator.evaluate(candidate, [active], observed_price=Decimal("70000"))
    assert not decision.accepted
    assert "owned by another strategy" in decision.reason


def test_allocator_blocks_non_live_capable_strategy():
    allocator = StrategyAllocator(config())
    order = Order("bitvavo", "ETH-EUR", OrderSide.BUY, OrderType.MARKET, 0.002, 3000, strategy="ArbitrageHunter")
    decision = allocator.evaluate(order, [], observed_price=Decimal("3000"))
    assert not decision.accepted
    assert "not approved" in decision.reason
