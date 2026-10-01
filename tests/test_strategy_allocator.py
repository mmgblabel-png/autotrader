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
                "allocation_eur": 8,
                "max_order_eur": 7,
                "max_open_orders": 1,
                "exclusive_symbol": True,
            },
            "grid_eth": {
                "symbol": "ETH-EUR",
                "live_capable": True,
                "allocation_eur": 7,
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


def test_allocator_values_each_active_asset_at_its_own_price():
    cfg = config()
    cfg["portfolio"]["global_live_budget_eur"] = 12
    allocator = StrategyAllocator(cfg)
    active_btc = Order(
        "bitvavo", "BTC-EUR", OrderSide.BUY, OrderType.LIMIT,
        0.0001, 70000, strategy="MarketMaker",
    )
    candidate_sol = Order(
        "bitvavo", "SOL-EUR", OrderSide.BUY, OrderType.LIMIT,
        0.06, 100, strategy="GridRunner",
    )
    decision = allocator.evaluate(
        candidate_sol, [active_btc], observed_price=Decimal("100")
    )
    assert not decision.accepted
    assert "global live budget" in decision.reason


def test_allocator_fails_closed_for_unknown_active_market_notional():
    allocator = StrategyAllocator(config())
    active = Order(
        "bitvavo", "SOL-EUR", OrderSide.BUY, OrderType.MARKET,
        0.05, None, strategy="GridRunner",
    )
    candidate = Order(
        "bitvavo", "XRP-EUR", OrderSide.BUY, OrderType.MARKET,
        3.0, 2.0, strategy="SniperBot",
    )
    decision = allocator.evaluate(candidate, [active], observed_price=Decimal("2"))
    assert not decision.accepted
    assert "notional is unknown" in decision.reason


def test_allocator_accepts_distinct_eth_grid_without_raising_global_budget():
    allocator = StrategyAllocator(config())
    sol = Order("bitvavo", "SOL-EUR", OrderSide.BUY, OrderType.LIMIT, 0.06, 100, strategy="GridRunner")
    eth = Order("bitvavo", "ETH-EUR", OrderSide.BUY, OrderType.LIMIT, 0.0025, 2400, strategy="GridRunnerETH")
    first = allocator.evaluate(sol, [], observed_price=Decimal("100"))
    second = allocator.evaluate(eth, [sol], observed_price=Decimal("2400"))
    assert first.accepted
    assert second.accepted
    assert allocator.global_budget_eur == Decimal("50")
    assert allocator.allocation_for("GridRunner").allocation_eur == Decimal("8")
    assert allocator.allocation_for("GridRunnerETH").allocation_eur == Decimal("7")


def test_allocator_wildcard_accepts_router_selected_market_with_same_caps():
    cfg = config()
    cfg["autonomous_execution"] = {
        "strategy_markets": {
            "grid_eth": ["*"],
        }
    }
    allocator = StrategyAllocator(cfg)
    order = Order(
        "bitvavo", "PEPE-EUR", OrderSide.BUY, OrderType.LIMIT,
        1790000, 0.0000039, strategy="GridRunnerETH",
    )
    decision = allocator.evaluate(
        order, [], observed_price=Decimal("0.0000039")
    )
    assert decision.accepted
    assert allocator.allocation_for("GridRunnerETH").max_order_eur == Decimal("7")
    assert allocator.global_budget_eur == Decimal("50")


def test_allocator_values_crypto_quote_order_in_eur():
    cfg = config()
    cfg["autonomous_execution"] = {"strategy_markets": {"grid": ["*"]}}
    allocator = StrategyAllocator(cfg)
    order = Order(
        "bitvavo",
        "ETH-BTC",
        OrderSide.BUY,
        OrderType.LIMIT,
        0.0017,
        0.05,
        strategy="GridRunner",
        quote_to_eur=70000.0,
        notional_eur=5.95,
    )
    decision = allocator.evaluate(order, [], observed_price=Decimal("0.05"))
    assert decision.accepted
