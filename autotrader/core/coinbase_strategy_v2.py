"""Strategy V2-style controller primitives for the Coinbase RiskTrader.

Inspired by Hummingbot's Controller -> ExecutorAction -> Executor separation,
without importing Hummingbot or coupling the local runtime to its client.
The controller owns signal selection; the autonomous executor keeps ownership
of exchange previews, order submission, persistence, recovery and lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


RouteResolver = Callable[..., dict[str, Any] | None]


@dataclass(frozen=True)
class ExecutionProposal:
    """Immutable request produced by a strategy controller for an executor."""

    controller_id: str
    action: str
    decision: dict[str, Any]
    route: dict[str, Any]

    @property
    def score(self) -> float:
        return float(self.route.get("score") or 0.0)

    @property
    def product_id(self) -> str:
        return str(self.route.get("product_id") or "")

    @property
    def after_cost_edge_bps(self) -> float:
        return float(self.route.get("after_cost_edge_bps") or 0.0)


@dataclass
class ControllerResult:
    """Controller output plus diagnostics for dashboard/audit visibility."""

    proposals: list[ExecutionProposal]
    diagnostics: dict[str, Any]


class DirectionalEntryController:
    """Select the best directional entry and emit an executor action.

    The controller deliberately does not place orders. It consumes normalized
    opportunity decisions and asks a supplied route resolver to validate
    executable venue routes, fees, spread, slippage and sizing.
    """

    controller_id = "coinbase_directional_v2"

    def evaluate(
        self,
        *,
        decisions: list[dict[str, Any]],
        seen_windows: set[str],
        route_resolver: RouteResolver,
        high_risk_fallback: bool,
        exploration_enabled: bool,
        exploration_min_forecast_bps: float,
        exploration_trade_eur: float,
        exploration_max_negative_edge_bps: float,
        exploration_max_spread_bps: float,
        day_settled_trades: int,
        daily_trade_target: int,
    ) -> ControllerResult:
        longs = [
            row
            for row in decisions
            if isinstance(row, dict)
            and row.get("decision") == "LONG"
            and str(row.get("window_key") or "") not in seen_windows
        ]
        normal_longs = [
            row
            for row in longs
            if str(row.get("risk_tier") or "normal").lower() != "high"
        ]
        high_longs = [
            row
            for row in longs
            if str(row.get("risk_tier") or "").lower() == "high"
        ]

        diagnostics: dict[str, Any] = {
            "controller_id": self.controller_id,
            "decisions_seen": len(longs),
            "normal_decisions": len(normal_longs),
            "high_risk_decisions": len(high_longs),
            "routes_considered": 0,
            "accepted_routes": 0,
            "rejects": {},
            "exploration_attempted": False,
        }

        def best_proposal(
            rows: list[dict[str, Any]],
            *,
            min_edge_override_bps: float | None = None,
            max_trade_override_eur: float | None = None,
            max_spread_override_bps: float | None = None,
            force_market: bool = False,
        ) -> ExecutionProposal | None:
            best: ExecutionProposal | None = None
            for decision in rows:
                route = route_resolver(
                    decision=decision,
                    diagnostics=diagnostics,
                    min_edge_override_bps=min_edge_override_bps,
                    max_trade_override_eur=max_trade_override_eur,
                    max_spread_override_bps=max_spread_override_bps,
                    force_market=force_market,
                )
                if route is None:
                    continue
                proposal = ExecutionProposal(
                    controller_id=self.controller_id,
                    action="CREATE_POSITION_EXECUTOR",
                    decision=dict(decision),
                    route=dict(route),
                )
                if best is None or proposal.score > best.score:
                    best = proposal
            return best

        selected = best_proposal(normal_longs)
        if selected is None and high_risk_fallback:
            selected = best_proposal(high_longs)

        if (
            selected is None
            and exploration_enabled
            and day_settled_trades < daily_trade_target
        ):
            exploration_rows = [
                row
                for row in longs
                if float(row.get("forecast_move_bps") or 0.0)
                >= exploration_min_forecast_bps
            ]
            if exploration_rows:
                diagnostics["exploration_attempted"] = True
                proposal = best_proposal(
                    exploration_rows,
                    min_edge_override_bps=-exploration_max_negative_edge_bps,
                    max_trade_override_eur=exploration_trade_eur,
                    max_spread_override_bps=exploration_max_spread_bps,
                    force_market=True,
                )
                if proposal is not None:
                    decision = {
                        **proposal.decision,
                        "risk_tier": "exploration",
                        "reason": "daily_learning_exploration",
                    }
                    route = {**proposal.route, "risk_tier": "exploration"}
                    selected = ExecutionProposal(
                        controller_id=self.controller_id,
                        action=proposal.action,
                        decision=decision,
                        route=route,
                    )
                    diagnostics["exploration_selected"] = True
                    diagnostics["exploration_notional_eur"] = round(
                        float(route.get("notional_eur") or 0.0), 8
                    )

        if selected is not None:
            diagnostics["selected_product"] = selected.product_id
            diagnostics["selected_risk_tier"] = selected.decision.get("risk_tier")
            diagnostics["selected_after_cost_edge_bps"] = round(
                selected.after_cost_edge_bps, 4
            )
            diagnostics["executor_action"] = selected.action
            return ControllerResult([selected], diagnostics)

        return ControllerResult([], diagnostics)
