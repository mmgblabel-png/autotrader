from autotrader.core.coinbase_strategy_v2 import DirectionalEntryController


def _route_resolver_factory(scores):
    def resolve(*, decision, diagnostics, **kwargs):
        diagnostics["routes_considered"] += 1
        product = decision["product_id"]
        if product not in scores:
            diagnostics["rejects"]["missing"] = diagnostics["rejects"].get("missing", 0) + 1
            return None
        diagnostics["accepted_routes"] += 1
        return {
            "product_id": product,
            "score": scores[product],
            "after_cost_edge_bps": scores[product],
            "risk_tier": decision.get("risk_tier", "normal"),
        }
    return resolve


def test_controller_emits_best_normal_executor_proposal():
    controller = DirectionalEntryController()
    decisions = [
        {
            "decision": "LONG",
            "product_id": "BTC-USDC",
            "window_key": "a",
            "forecast_move_bps": 30,
            "risk_tier": "normal",
        },
        {
            "decision": "LONG",
            "product_id": "ETH-USDC",
            "window_key": "b",
            "forecast_move_bps": 35,
            "risk_tier": "normal",
        },
    ]

    result = controller.evaluate(
        decisions=decisions,
        seen_windows=set(),
        route_resolver=_route_resolver_factory({"BTC-USDC": 18, "ETH-USDC": 27}),
        high_risk_fallback=False,
        exploration_enabled=False,
        exploration_min_forecast_bps=5,
        exploration_trade_eur=2,
        exploration_max_negative_edge_bps=0,
        exploration_max_spread_bps=15,
        day_settled_trades=0,
        daily_trade_target=10,
    )

    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.controller_id == "coinbase_directional_v2"
    assert proposal.action == "CREATE_POSITION_EXECUTOR"
    assert proposal.product_id == "ETH-USDC"
    assert proposal.score == 27
    assert result.diagnostics["selected_product"] == "ETH-USDC"
    assert result.diagnostics["executor_action"] == "CREATE_POSITION_EXECUTOR"


def test_controller_ignores_seen_windows_and_high_risk_when_disabled():
    controller = DirectionalEntryController()
    decisions = [
        {
            "decision": "LONG",
            "product_id": "BTC-USDC",
            "window_key": "seen",
            "forecast_move_bps": 50,
            "risk_tier": "normal",
        },
        {
            "decision": "LONG",
            "product_id": "SOL-USDC",
            "window_key": "new",
            "forecast_move_bps": 60,
            "risk_tier": "high",
        },
    ]

    result = controller.evaluate(
        decisions=decisions,
        seen_windows={"seen"},
        route_resolver=_route_resolver_factory({"BTC-USDC": 40, "SOL-USDC": 50}),
        high_risk_fallback=False,
        exploration_enabled=False,
        exploration_min_forecast_bps=5,
        exploration_trade_eur=2,
        exploration_max_negative_edge_bps=0,
        exploration_max_spread_bps=15,
        day_settled_trades=0,
        daily_trade_target=10,
    )

    assert result.proposals == []
    assert result.diagnostics["decisions_seen"] == 1
    assert result.diagnostics["normal_decisions"] == 0
    assert result.diagnostics["high_risk_decisions"] == 1


def test_controller_high_risk_fallback_is_explicit():
    controller = DirectionalEntryController()
    decision = {
        "decision": "LONG",
        "product_id": "SOL-USDC",
        "window_key": "risk",
        "forecast_move_bps": 60,
        "risk_tier": "high",
    }

    result = controller.evaluate(
        decisions=[decision],
        seen_windows=set(),
        route_resolver=_route_resolver_factory({"SOL-USDC": 21}),
        high_risk_fallback=True,
        exploration_enabled=False,
        exploration_min_forecast_bps=5,
        exploration_trade_eur=2,
        exploration_max_negative_edge_bps=0,
        exploration_max_spread_bps=15,
        day_settled_trades=0,
        daily_trade_target=10,
    )

    assert result.proposals[0].product_id == "SOL-USDC"
    assert result.proposals[0].decision["risk_tier"] == "high"
