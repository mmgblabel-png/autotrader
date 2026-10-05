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


def test_allocator_exposes_resizable_entry_capacity():
    allocator = StrategyAllocator(config())
    order = Order(
        "bitvavo", "SOL-EUR", OrderSide.BUY, OrderType.LIMIT,
        0.08, 100, strategy="GridRunner",
    )
    assert allocator.max_entry_notional(order, []) == Decimal("7")


def test_allocator_allows_risk_reducing_sell_above_entry_caps():
    allocator = StrategyAllocator(config())
    order = Order(
        "bitvavo", "SOL-EUR", OrderSide.SELL, OrderType.LIMIT,
        0.20, 100, strategy="GridRunner",
    )
    decision = allocator.evaluate(order, [], observed_price=Decimal("100"))
    assert decision.accepted is True


def test_dynamic_allocator_uses_verified_nav_and_keeps_cash_reserve():
    cfg = config()
    cfg["portfolio"].update({
        "initial_live_capital_eur": 80,
        "global_live_budget_eur": 80,
        "dynamic_with_verified_nav": True,
        "max_deployable_pct": 80,
        "min_cash_reserve_pct": 20,
    })
    allocator = StrategyAllocator(cfg)

    assert allocator.global_budget_eur == Decimal("64")
    bootstrap = allocator.capital_status()
    assert bootstrap["managed_nav_eur"] == 80.0
    assert bootstrap["cash_reserve_eur"] == 16.0

    assert allocator.set_verified_nav(250) is True
    assert allocator.global_budget_eur == Decimal("200")
    status = allocator.capital_status()
    assert status["managed_nav_eur"] == 250.0
    assert status["cash_reserve_eur"] == 50.0


def test_dynamic_allocator_scales_strategy_and_order_caps_with_nav():
    cfg = config()
    cfg["portfolio"].update({
        "initial_live_capital_eur": 80,
        "global_live_budget_eur": 80,
        "dynamic_with_verified_nav": True,
        "max_deployable_pct": 80,
        "min_cash_reserve_pct": 20,
    })
    allocator = StrategyAllocator(cfg)

    start = allocator.allocation_for("MarketMaker")
    assert start is not None
    assert start.max_order_eur == Decimal("10")

    allocator.set_verified_nav(160)
    scaled = allocator.allocation_for("MarketMaker")
    assert scaled is not None
    assert scaled.max_order_eur == Decimal("20")
    assert scaled.allocation_eur > start.allocation_eur


def test_dynamic_allocator_does_not_double_shrink_small_nav_order_cap():
    cfg = config()
    cfg["portfolio"].update({
        "initial_live_capital_eur": 80,
        "global_live_budget_eur": 80,
        "dynamic_with_verified_nav": True,
        "max_deployable_pct": 80,
        "min_cash_reserve_pct": 20,
    })
    allocator = StrategyAllocator(cfg)
    assert allocator.set_verified_nav(30) is True

    grid = allocator.allocation_for("GridRunner")
    assert grid is not None
    assert grid.allocation_eur == Decimal("4.8")
    assert grid.max_order_eur == Decimal("4.8")
