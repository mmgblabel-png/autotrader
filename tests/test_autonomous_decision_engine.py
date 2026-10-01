from __future__ import annotations

from types import SimpleNamespace

from autotrader.core.autonomous_decision_engine import AutonomousDecisionEngine


class FakeOM:
    def __init__(self, open_by_strategy=None):
        self.open_by_strategy = open_by_strategy or {}

    def open_orders(self, strategy=None):
        if strategy is None:
            rows = []
            for values in self.open_by_strategy.values():
                rows.extend(values)
            return rows
        return list(self.open_by_strategy.get(strategy, []))


class FakeJournal:
    def __init__(self, inventory=None, nonterminal=None):
        self.inventory = inventory or {}
        self.nonterminal = nonterminal or {}

    def inventory_cost_basis(self, market, strategy):
        return {"quantity": float(self.inventory.get((market, strategy), 0.0))}

    def strategy_market_state(self, market, strategy):
        return {"nonterminal_count": int(self.nonterminal.get((market, strategy), 0))}


class FakeGateway:
    def __init__(self, exposure=0.0, max_exposure=50.0):
        self.exposure = exposure
        self.max_exposure = max_exposure

    def status(self):
        return {
            "daily_exposure_eur": str(self.exposure),
            "limits": {"max_daily_exposure_eur": str(self.max_exposure)},
        }


class FakeBitvavo:
    def __init__(self, journal, gateway=None):
        self.journal = journal
        self.gateway = gateway or FakeGateway()

    def markets(self, market):
        return [{
            "market": market,
            "status": "trading",
            "orderTypes": ["limit", "market"],
            "minOrderInQuoteAsset": "5",
        }]


class FakeStrategy:
    def __init__(self, name, symbol, allocation, max_order, order_value=6.0):
        self.name = name
        self.is_enabled = True
        self.is_running = True
        self.switched = []
        self._config = {
            "enabled": True,
            "symbol": symbol,
            "exchange": "bitvavo",
            "allocation_eur": allocation,
            "max_order_eur": max_order,
            "order_value_eur": order_value,
            "exit_markup_pct": 0.80,
            "take_profit_pct": 0.80,
            "cycle_exit_markup_pct": 0.80,
        }

    def on_market_switch(self, old_market, new_market):
        self.switched.append((old_market, new_market))
        self._config["_current_price"] = 0.0
        self._config["_live_balance_snapshot_ready"] = False


def _agent(*, inventory=None, nonterminal=None, open_by_strategy=None, exposure=0.0, max_exposure=50.0):
    strategies = {
        "market_maker": FakeStrategy("MarketMaker", "BTC-EUR", 15, 10, 0),
        "grid": FakeStrategy("GridRunner", "SOL-EUR", 15, 7, 6),
        "sniper": FakeStrategy("SniperBot", "XRP-EUR", 10, 7, 6),
    }
    return SimpleNamespace(
        _strategies=strategies,
        _om=FakeOM(open_by_strategy),
        _bitvavo=FakeBitvavo(
            FakeJournal(inventory, nonterminal),
            FakeGateway(exposure=exposure, max_exposure=max_exposure),
        ),
    )


def _router():
    return {
        "rankings": {
            "market_maker": [{"market": "BTC-EUR", "score": 90, "eligible": True}],
            "grid": [
                {"market": "ETH-EUR", "score": 88, "eligible": True},
                {"market": "SOL-EUR", "score": 75, "eligible": True},
            ],
            "sniper": [
                {"market": "ADA-EUR", "score": 91, "eligible": True},
                {"market": "XRP-EUR", "score": 73, "eligible": True},
            ],
        }
    }


def _risk():
    return {
        "rows": [
            {"strategy": "MarketMaker", "confidence": 0.90, "recommended_order_eur": 10},
            {"strategy": "GridRunner", "confidence": 0.85, "recommended_order_eur": 7},
            {"strategy": "SniperBot", "confidence": 0.88, "recommended_order_eur": 7},
        ]
    }


def test_autonomous_engine_never_arms_and_respects_hard_rules():
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "switch_cooldown_seconds": 30,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=_agent(), router_payload=_router(), risk_payload=_risk(), armed=False)
    assert plan["hard_rules"]["can_arm_itself"] is False
    assert plan["hard_rules"]["can_raise_global_budget"] is False
    assert plan["hard_rules"]["can_raise_hard_risk_limits"] is False
    assert plan["hard_rules"]["can_use_leverage"] is False
    assert plan["hard_rules"]["can_use_martingale"] is False
    result = engine.apply(agent=_agent(), plan=plan, armed=False)
    assert result["applied"] is False


def test_autonomous_engine_switches_only_flat_order_free_strategy():
    agent = _agent()
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "switch_cooldown_seconds": 30,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    rows = {row["strategy"]: row for row in plan["rows"]}
    assert rows["GridRunner"]["desired_market"] == "ETH-EUR"
    assert rows["GridRunner"]["may_switch"] is True
    assert rows["SniperBot"]["desired_market"] == "ADA-EUR"
    result = engine.apply(agent=agent, plan=plan, armed=True)
    assert result["applied"] is True
    assert agent._strategies["grid"]._config["symbol"] == "ETH-EUR"
    assert agent._strategies["sniper"]._config["symbol"] == "ADA-EUR"
    assert agent._strategies["grid"]._config["order_value_eur"] <= 7.0
    assert agent._strategies["sniper"]._config["order_value_eur"] <= 7.0
    assert agent._strategies["market_maker"]._config["symbol"] == "BTC-EUR"


def test_autonomous_engine_refuses_switch_with_inventory_or_durable_order():
    agent = _agent(
        inventory={("SOL-EUR", "GridRunner"): 0.1},
        nonterminal={("XRP-EUR", "SniperBot"): 1},
    )
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "switch_cooldown_seconds": 30,
        "strategy_markets": {
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
            "market_maker": ["BTC-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    rows = {row["strategy"]: row for row in plan["rows"]}
    assert rows["GridRunner"]["may_switch"] is False
    assert rows["GridRunner"]["reason"] == "inventory_locked"
    assert rows["SniperBot"]["may_switch"] is False
    assert rows["SniperBot"]["reason"] == "open_order_locked"
    engine.apply(agent=agent, plan=plan, armed=True)
    assert agent._strategies["grid"]._config["symbol"] == "SOL-EUR"
    assert agent._strategies["sniper"]._config["symbol"] == "XRP-EUR"


def test_autonomous_engine_ignores_unapproved_market():
    agent = _agent()
    payload = _router()
    payload["rankings"]["grid"].insert(0, {"market": "MEME-EUR", "score": 99, "eligible": True})
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "strategy_markets": {
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
            "market_maker": ["BTC-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=payload, risk_payload=_risk(), armed=True)
    row = next(x for x in plan["rows"] if x["strategy"] == "GridRunner")
    assert row["desired_market"] == "ETH-EUR"


def test_max_size_requires_profit_gate_and_high_confidence():
    agent = _agent()
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "max_size_score": 82,
        "max_size_confidence": 0.75,
        "strategy_markets": {
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
            "market_maker": ["BTC-EUR"],
        },
    })
    agent._strategies["grid"]._config["_required_entry_edge_pct"] = 0.75
    agent._strategies["grid"]._config["exit_markup_pct"] = 0.80
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    row = next(x for x in plan["rows"] if x["strategy"] == "GridRunner")
    assert row["profit_gate"] is True
    assert row["max_size_signal"] is True
    assert row["recommended_order_eur"] == 7.0

    agent._strategies["grid"]._config["_required_entry_edge_pct"] = 0.95
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    row = next(x for x in plan["rows"] if x["strategy"] == "GridRunner")
    assert row["profit_gate"] is False
    assert row["quality_ok"] is False
    assert row["max_size_signal"] is False


def test_extended_market_requires_higher_quality_gate():
    agent = _agent()
    payload = _router()
    payload["rankings"]["sniper"] = [
        {"market": "PEPE-EUR", "score": 72, "eligible": True},
        {"market": "ADA-EUR", "score": 71, "eligible": True},
    ]
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "market_thresholds": {
            "PEPE-EUR": {"min_score": 74, "min_confidence": 0.66},
        },
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR", "PEPE-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=payload, risk_payload=_risk(), armed=True)
    row = next(x for x in plan["rows"] if x["strategy"] == "SniperBot")
    assert row["desired_market"] == "ADA-EUR"
    assert row["quality_ok"] is True


def test_market_switch_calls_reset_hook_and_exchange_rules():
    agent = _agent()
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    result = engine.apply(agent=agent, plan=plan, armed=True)
    assert result["applied"] is True
    assert ("SOL-EUR", "ETH-EUR") in agent._strategies["grid"].switched
    assert agent._strategies["grid"]._config["_live_balance_snapshot_ready"] is False


def test_daily_exposure_headroom_pauses_new_entries_below_exchange_minimum():
    agent = _agent(exposure=48.0, max_exposure=50.0)
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "minimum_live_order_eur": 5.0,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    rows = {row["strategy"]: row for row in plan["rows"]}
    assert rows["GridRunner"]["raw_daily_exposure_headroom_eur"] == 2.0
    assert rows["GridRunner"]["daily_exposure_headroom_eur"] == 1.75
    assert rows["GridRunner"]["exposure_headroom_ok"] is False
    assert rows["GridRunner"]["entry_allowed"] is False
    assert rows["GridRunner"]["reason"] == "daily_exposure_headroom_low"

    engine.apply(agent=agent, plan=plan, armed=True)
    assert agent._strategies["grid"]._config["_autonomous_entry_allowed"] is False
    assert agent._strategies["sniper"]._config["_autonomous_entry_allowed"] is False


def test_shared_exposure_headroom_is_reserved_across_strategies():
    agent = _agent(exposure=38.0, max_exposure=50.0)
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "minimum_live_order_eur": 5.0,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    rows = {row["strategy"]: row for row in plan["rows"]}
    # MarketMaker reserves first because it is also flat in this fixture.
    assert rows["MarketMaker"]["entry_allowed"] is True
    assert rows["MarketMaker"]["recommended_order_eur"] == 10.0
    assert rows["GridRunner"]["raw_daily_exposure_headroom_eur"] == 12.0
    assert rows["GridRunner"]["daily_exposure_headroom_eur"] == 1.75
    assert rows["GridRunner"]["entry_allowed"] is False


def test_grid_exit_path_ignores_entry_pause():
    from autotrader.core.order_manager import OrderManager, OrderSide
    from autotrader.core.profit_engine import ProfitEngine
    from autotrader.core.risk_manager import RiskManager
    from autotrader.strategies.grid_runner import GridRunner

    om = OrderManager()
    rm = RiskManager()
    pe = ProfitEngine()
    cfg = {
        "enabled": True,
        "symbol": "SOL-EUR",
        "exchange": "bitvavo",
        "order_value_eur": 6.0,
        "entry_offset_pct": 0.60,
        "exit_markup_pct": 0.80,
        "_current_price": 100.0,
        "_live_balance_snapshot_ready": True,
        "_available_base": 0.1,
        "_available_quote": 0.0,
        "_bot_base_inventory": 0.1,
        "_bot_average_entry_price": 95.0,
        "_autonomous_entry_allowed": False,
    }
    strategy = GridRunner(om, rm, pe, cfg)
    strategy.start()
    strategy.tick()
    orders = om.open_orders("GridRunner")
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL


def test_pending_buy_reservation_prevents_cross_strategy_exposure_race():
    from autotrader.core.order_manager import OrderSide, OrderStatus

    pending_mm_buy = SimpleNamespace(
        side=OrderSide.BUY,
        status=OrderStatus.PENDING,
        quantity=0.07,
        price=100.0,
        strategy="MarketMaker",
    )
    agent = _agent(
        exposure=38.0,
        max_exposure=50.0,
        open_by_strategy={"MarketMaker": [pending_mm_buy]},
    )
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "minimum_live_order_eur": 5.0,
        "exposure_safety_buffer_eur": 0.25,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    rows = {row["strategy"]: row for row in plan["rows"]}
    assert rows["GridRunner"]["raw_daily_exposure_headroom_eur"] == 12.0
    assert rows["GridRunner"]["pending_buy_reservation_eur"] == 7.0
    assert rows["GridRunner"]["daily_exposure_headroom_eur"] == 4.75
    assert rows["GridRunner"]["entry_allowed"] is False
    assert rows["GridRunner"]["reason"] == "daily_exposure_headroom_low"


def test_exposure_safety_buffer_blocks_borderline_minimum_order():
    agent = _agent(exposure=44.8, max_exposure=50.0)
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "minimum_live_order_eur": 5.0,
        "exposure_safety_buffer_eur": 0.25,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    rows = {row["strategy"]: row for row in plan["rows"]}
    assert rows["MarketMaker"]["raw_daily_exposure_headroom_eur"] == 5.2
    assert rows["MarketMaker"]["daily_exposure_headroom_eur"] == 4.95
    assert rows["MarketMaker"]["entry_allowed"] is False
    assert rows["GridRunner"]["entry_allowed"] is False


def test_apply_clears_stale_entry_permission_when_quality_drops():
    agent = _agent()
    agent._strategies["grid"]._config["_autonomous_entry_allowed"] = True
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 90,
        "min_confidence": 0.95,
        "min_signal_strength": 95,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=_router(), risk_payload=_risk(), armed=True)
    row = next(x for x in plan["rows"] if x["strategy"] == "GridRunner")
    assert row["quality_ok"] is False
    engine.apply(agent=agent, plan=plan, armed=True)
    assert agent._strategies["grid"]._config["_autonomous_entry_allowed"] is False


def test_wildcard_market_universe_accepts_router_candidate():
    agent = _agent()
    payload = _router()
    payload["rankings"]["grid"].insert(
        0,
        {"market": "AAVE-EUR", "score": 95, "signal_strength": 90, "eligible": True},
    )
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "min_signal_strength": 62,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["*"],
            "sniper": ["*"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=payload, risk_payload=_risk(), armed=True)
    row = next(x for x in plan["rows"] if x["strategy"] == "GridRunner")
    assert row["desired_market"] == "AAVE-EUR"
    assert row["signal_strength"] == 90
    assert row["quality_ok"] is True


def test_below_minimum_recommendation_does_not_switch_or_mutate_order_value():
    agent = _agent()
    before = agent._strategies["sniper"]._config["order_value_eur"]
    payload = _router()
    risk = _risk()
    for row in risk["rows"]:
        if row["strategy"] == "SniperBot":
            row["recommended_order_eur"] = 3.90
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "minimum_live_order_eur": 5.0,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR", "ETH-EUR"],
            "sniper": ["XRP-EUR", "ADA-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=payload, risk_payload=risk, armed=True)
    row = next(x for x in plan["rows"] if x["strategy"] == "SniperBot")
    assert row["minimum_order_ok"] is False
    assert row["entry_allowed"] is False
    assert row["may_switch"] is False
    assert row["reason"] == "order_below_exchange_minimum"
    engine.apply(agent=agent, plan=plan, armed=True)
    assert agent._strategies["sniper"]._config["order_value_eur"] == before
    assert agent._strategies["sniper"]._config["symbol"] == "XRP-EUR"


def test_sniper_uses_stricter_strategy_specific_thresholds():
    agent = _agent()
    payload = _router()
    payload["rankings"]["sniper"][0].update({
        "score": 90,
        "signal_strength": 77,
        "signal_direction": "LONG",
    })
    agent._strategies["sniper"]._config.update({
        "autonomous_min_score": 82,
        "autonomous_min_signal_strength": 80,
        "autonomous_min_confidence": 0.75,
    })
    engine = AutonomousDecisionEngine({
        "enabled": True,
        "apply_live": True,
        "min_score": 68,
        "min_confidence": 0.62,
        "min_signal_strength": 62,
        "strategy_markets": {
            "market_maker": ["BTC-EUR"],
            "grid": ["SOL-EUR"],
            "sniper": ["XRP-EUR"],
        },
    })
    plan = engine.plan(agent=agent, router_payload=payload, risk_payload=_risk(), armed=True)
    row = next(x for x in plan["rows"] if x["strategy"] == "SniperBot")
    assert row["min_signal_strength"] == 80
    assert row["entry_allowed"] is False
    assert row["quality_ok"] is False
