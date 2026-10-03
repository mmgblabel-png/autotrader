"""Read-only derivatives risk lab.

The lab models leverage, margin, fees, funding and liquidation distance without
providing any order-placement capability. It is deliberately separate from the
spot fund engine so derivatives cannot inherit spot-only risk assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DerivativesScenario:
    symbol: str
    side: str
    collateral_eur: float
    leverage: float
    initial_margin_pct: float
    maintenance_margin_pct: float
    fee_pct_each_leg: float
    funding_rate_8h_pct: float
    holding_hours: float
    stress_move_pct: float

    @property
    def notional_eur(self) -> float:
        return self.collateral_eur * self.leverage

    @property
    def liquidation_buffer_pct(self) -> float:
        # Approximation for an isolated linear position before fees/funding:
        # collateral/notional minus maintenance margin requirement.
        return max(0.0, (1.0 / self.leverage - self.maintenance_margin_pct / 100.0) * 100.0)

    @property
    def round_trip_fee_eur(self) -> float:
        return self.notional_eur * (2.0 * self.fee_pct_each_leg / 100.0)

    @property
    def funding_eur(self) -> float:
        intervals = max(0.0, self.holding_hours) / 8.0
        return self.notional_eur * (self.funding_rate_8h_pct / 100.0) * intervals

    @property
    def stress_price_pnl_eur(self) -> float:
        adverse = abs(self.stress_move_pct) / 100.0
        return -self.notional_eur * adverse

    @property
    def stressed_net_pnl_eur(self) -> float:
        # Positive funding means the modeled position pays funding.
        return self.stress_price_pnl_eur - self.round_trip_fee_eur - self.funding_eur

    @property
    def stressed_loss_pct_of_collateral(self) -> float:
        if self.collateral_eur <= 0:
            return 100.0
        return max(0.0, -self.stressed_net_pnl_eur / self.collateral_eur * 100.0)


class DerivativesRiskLab:
    """Fail-closed derivatives evaluator. Never creates or submits orders."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.max_research_leverage = max(
            1.0, min(10.0, float(self.config.get("max_research_leverage", 3.0)))
        )
        self.max_collateral_pct_of_nav = max(
            0.0, min(20.0, float(self.config.get("max_collateral_pct_of_nav", 5.0)))
        )
        self.min_liquidation_buffer_pct = max(
            1.0, float(self.config.get("min_liquidation_buffer_pct", 20.0))
        )
        self.max_stressed_loss_pct_of_collateral = max(
            1.0,
            min(
                100.0,
                float(self.config.get("max_stressed_loss_pct_of_collateral", 35.0)),
            ),
        )
        self.default_fee_pct_each_leg = max(
            0.0, float(self.config.get("fee_pct_each_leg", 0.25))
        )
        self.default_funding_rate_8h_pct = float(
            self.config.get("funding_rate_8h_pct", 0.01)
        )
        self.default_initial_margin_pct = max(
            0.1, float(self.config.get("initial_margin_pct", 50.0))
        )
        self.default_maintenance_margin_pct = max(
            0.0, float(self.config.get("maintenance_margin_pct", 10.0))
        )
        self.default_stress_move_pct = max(
            0.1, float(self.config.get("stress_move_pct", 8.0))
        )
        self.default_holding_hours = max(
            0.0, float(self.config.get("holding_hours", 8.0))
        )

    def evaluate(
        self,
        *,
        symbol: str,
        side: str,
        collateral_eur: float,
        leverage: float,
        initial_margin_pct: float | None = None,
        maintenance_margin_pct: float | None = None,
        fee_pct_each_leg: float | None = None,
        funding_rate_8h_pct: float | None = None,
        holding_hours: float | None = None,
        stress_move_pct: float | None = None,
        nav_eur: float | None = None,
    ) -> dict[str, Any]:
        lev = max(1.0, float(leverage))
        scenario = DerivativesScenario(
            symbol=str(symbol).upper(),
            side=str(side).upper(),
            collateral_eur=max(0.0, float(collateral_eur)),
            leverage=lev,
            initial_margin_pct=max(
                0.0,
                float(
                    self.default_initial_margin_pct
                    if initial_margin_pct is None
                    else initial_margin_pct
                ),
            ),
            maintenance_margin_pct=max(
                0.0,
                float(
                    self.default_maintenance_margin_pct
                    if maintenance_margin_pct is None
                    else maintenance_margin_pct
                ),
            ),
            fee_pct_each_leg=max(
                0.0,
                float(
                    self.default_fee_pct_each_leg
                    if fee_pct_each_leg is None
                    else fee_pct_each_leg
                ),
            ),
            funding_rate_8h_pct=float(
                self.default_funding_rate_8h_pct
                if funding_rate_8h_pct is None
                else funding_rate_8h_pct
            ),
            holding_hours=max(
                0.0,
                float(
                    self.default_holding_hours
                    if holding_hours is None
                    else holding_hours
                ),
            ),
            stress_move_pct=max(
                0.0,
                float(
                    self.default_stress_move_pct
                    if stress_move_pct is None
                    else stress_move_pct
                ),
            ),
        )

        reasons: list[str] = []
        if not self.enabled:
            reasons.append("lab_disabled")
        if scenario.collateral_eur <= 0:
            reasons.append("collateral_required")
        if scenario.leverage > self.max_research_leverage:
            reasons.append("research_leverage_cap")
        if scenario.initial_margin_pct > 0:
            leverage_from_margin = 100.0 / scenario.initial_margin_pct
            if scenario.leverage > leverage_from_margin + 1e-9:
                reasons.append("initial_margin_insufficient")
        if scenario.liquidation_buffer_pct < self.min_liquidation_buffer_pct:
            reasons.append("liquidation_buffer_low")
        if (
            scenario.stressed_loss_pct_of_collateral
            > self.max_stressed_loss_pct_of_collateral
        ):
            reasons.append("stress_loss_too_high")
        collateral_pct_of_nav = None
        if nav_eur is not None and float(nav_eur) > 0:
            collateral_pct_of_nav = scenario.collateral_eur / float(nav_eur) * 100.0
            if collateral_pct_of_nav > self.max_collateral_pct_of_nav:
                reasons.append("collateral_share_of_nav_too_high")

        return {
            "mode": "derivatives_shadow_risk_lab",
            "live_capable": False,
            "live_orders_sent": False,
            "symbol": scenario.symbol,
            "side": scenario.side,
            "collateral_eur": round(scenario.collateral_eur, 4),
            "leverage": round(scenario.leverage, 4),
            "notional_eur": round(scenario.notional_eur, 4),
            "initial_margin_pct": round(scenario.initial_margin_pct, 4),
            "maintenance_margin_pct": round(scenario.maintenance_margin_pct, 4),
            "liquidation_buffer_pct_approx": round(
                scenario.liquidation_buffer_pct, 4
            ),
            "round_trip_fee_eur": round(scenario.round_trip_fee_eur, 6),
            "funding_eur": round(scenario.funding_eur, 6),
            "stress_move_pct": round(scenario.stress_move_pct, 4),
            "stressed_net_pnl_eur": round(scenario.stressed_net_pnl_eur, 6),
            "stressed_loss_pct_of_collateral": round(
                scenario.stressed_loss_pct_of_collateral, 4
            ),
            "collateral_pct_of_nav": (
                round(collateral_pct_of_nav, 4)
                if collateral_pct_of_nav is not None
                else None
            ),
            "research_gate_passed": not reasons,
            "blockers": reasons,
            "promotion_ready": False,
            "note": (
                "Research only. Actual margin, liquidation, funding and fees must "
                "come from the eligible derivatives account/product before any "
                "future live implementation."
            ),
        }

    def status(self, *, nav_eur: float | None = None) -> dict[str, Any]:
        scenarios = []
        for leverage in self.config.get("research_leverage_scenarios", [1.0, 2.0, 3.0]):
            scenarios.append(
                self.evaluate(
                    symbol=str(self.config.get("symbol", "BTC-PERP")),
                    side="LONG",
                    collateral_eur=float(
                        self.config.get("shadow_collateral_eur", 4.0)
                    ),
                    leverage=float(leverage),
                    nav_eur=nav_eur,
                )
            )
        return {
            "enabled": self.enabled,
            "mode": "derivatives_shadow_risk_lab",
            "live_capable": False,
            "live_orders_sent": False,
            "account_eligibility_required": True,
            "scenarios": scenarios,
            "promotion_ready": False,
        }
