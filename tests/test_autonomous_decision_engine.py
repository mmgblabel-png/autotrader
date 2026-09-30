from __future__ import annotations

from types import SimpleNamespace

from autotrader.core.autonomous_decision_engine import AutonomousDecisionEngine


class FakeOM:
    def __init__(self, open_by_strategy=None):
        self.open_by_strategy = open_by_strategy or {}

    def open_orders(self, strategy=None):
        if strategy is None:
            return []
        return list(self.open_by_strategy.get(strategy, []))


class FakeJournal:
    def __init__(self, inventory=None, nonterminal=None):
        self.inventory = inventory or {}
        self.nonterminal = nonterminal or {}

    def inventory_cost_basis(self, market, strategy):
        return {"quantity": float(self.inventory.get((market, strategy), 0.0))}

    def strategy_state(self, market, strategy):
        return {"nonterminal_count": int(self.nonterminal.get((market, strategy), 0))}


class FakeStrategy:
    def __init__(self, name, symbol, allocation, max_order, order_value=6.0):
        self.name = name
        self.is_enabled = True
        self.is_running = True
        self._config = {
            "enabled": True,
            "symbol": symbol,
            "exchange": "bitvavo",
            "allocation_eur": allocation,
            "max_order_eur": max_order,
            "order_value_eur": order_value,
        }


def _agent(*, inventory=None, nonterminal=None, open_by_strategy=None):
    strategies = {
        "market_maker": FakeStrategy("MarketMaker", "BTC-EUR", 15, 10, 0),
        "grid": FakeStrategy("GridRunner", "SOL-EUR", 15, 7, 6),
        "sniper": FakeStrategy("SniperBot", "XRP-EUR", 10, 7, 6),
    }
    return SimpleNamespace(
        _strategies=strategies,
        _om=FakeOM(open_by_strategy),
        _bitvavo=SimpleNamespace(journal=FakeJournal(inventory, nonterminal)),
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
