"""Institutional-style fund policy and hard risk gates."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from autotrader.fund.models import RiskDecision


@dataclass(frozen=True)
class FundRiskLimits:
    stage: str
    max_portfolio_drawdown_pct: float
    max_daily_loss_pct: float
    max_risk_per_trade_pct: float
    max_asset_exposure_pct: float
    max_sector_exposure_pct: float
    max_gross_exposure_pct: float
    min_cash_pct: float
    target_annualized_volatility_pct: float
    hard_annualized_volatility_pct: float
    max_single_venue_pct: float


_STAGE_LIMITS = (
    (1_000_000.0, FundRiskLimits("institutional", 7.0, 0.75, 0.25, 10.0, 25.0, 85.0, 15.0, 12.0, 22.0, 35.0)),
    (100_000.0, FundRiskLimits("large", 8.0, 1.00, 0.30, 15.0, 30.0, 85.0, 15.0, 14.0, 25.0, 45.0)),
    (10_000.0, FundRiskLimits("medium", 8.0, 1.25, 0.35, 20.0, 35.0, 82.0, 18.0, 16.0, 28.0, 55.0)),
    (1_000.0, FundRiskLimits("emerging", 7.0, 1.50, 0.35, 25.0, 40.0, 80.0, 20.0, 18.0, 32.0, 65.0)),
    (0.0, FundRiskLimits("micro", 6.0, 1.50, 0.35, 35.0, 50.0, 70.0, 30.0, 18.0, 35.0, 75.0)),
)


def risk_limits_for_equity(equity_eur: float) -> FundRiskLimits:
    equity = float(equity_eur)
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError("equity_eur must be positive and finite")
    for threshold, limits in _STAGE_LIMITS:
        if equity >= threshold:
            return limits
    raise AssertionError("unreachable")


class FundPolicy:
    """Fail-closed portfolio risk policy.

    AI/strategy confidence can reduce risk or leave it unchanged. It cannot
    enlarge these hard limits.
    """

    def __init__(self, limits: FundRiskLimits) -> None:
        self.limits = limits

    @classmethod
    def for_equity(cls, equity_eur: float) -> "FundPolicy":
        return cls(risk_limits_for_equity(equity_eur))

    def evaluate(
        self,
        *,
        equity_eur: float,
        peak_equity_eur: float,
        daily_start_equity_eur: float,
        asset_weights: Mapping[str, float],
        sector_weights: Mapping[str, float],
        annualized_volatility_pct: float = 0.0,
        venue_weights: Mapping[str, float] | None = None,
    ) -> RiskDecision:
        if equity_eur <= 0 or peak_equity_eur <= 0 or daily_start_equity_eur <= 0:
            return RiskDecision(False, "HALT", 100.0, 100.0, ("invalid or depleted equity",))

        drawdown = max(0.0, (peak_equity_eur - equity_eur) / peak_equity_eur * 100.0)
        daily_loss = max(0.0, (daily_start_equity_eur - equity_eur) / daily_start_equity_eur * 100.0)
        gross = sum(max(0.0, float(v)) for v in asset_weights.values()) * 100.0
        breaches: list[str] = []
        hard_halt = False

        if drawdown >= self.limits.max_portfolio_drawdown_pct:
            breaches.append("portfolio drawdown limit breached")
            hard_halt = True
        if daily_loss >= self.limits.max_daily_loss_pct:
            breaches.append("daily loss limit breached")
            hard_halt = True
        if gross > self.limits.max_gross_exposure_pct + 1e-9:
            breaches.append("gross exposure limit breached")
        if any(float(v) * 100.0 > self.limits.max_asset_exposure_pct + 1e-9 for v in asset_weights.values()):
            breaches.append("single-asset exposure limit breached")
        if any(float(v) * 100.0 > self.limits.max_sector_exposure_pct + 1e-9 for v in sector_weights.values()):
            breaches.append("sector exposure limit breached")
        if venue_weights and any(float(v) * 100.0 > self.limits.max_single_venue_pct + 1e-9 for v in venue_weights.values()):
            breaches.append("single-venue exposure limit breached")
        if annualized_volatility_pct > self.limits.hard_annualized_volatility_pct:
            breaches.append("hard volatility limit breached")
            hard_halt = True

        severity = max(
            drawdown / max(self.limits.max_portfolio_drawdown_pct, 1e-9),
            daily_loss / max(self.limits.max_daily_loss_pct, 1e-9),
            annualized_volatility_pct / max(self.limits.hard_annualized_volatility_pct, 1e-9),
        )
        if hard_halt:
            level = "HALT"
        elif breaches or severity >= 0.80:
            level = "HIGH"
        elif severity >= 0.55:
            level = "ELEVATED"
        else:
            level = "NORMAL"
        return RiskDecision(not breaches and not hard_halt, level, drawdown, daily_loss, tuple(breaches))

    def max_position_notional(
        self,
        *,
        equity_eur: float,
        stop_distance_pct: float,
        annualized_volatility_pct: float,
        current_asset_notional_eur: float = 0.0,
    ) -> float:
        """Return a conservative maximum entry notional."""
        if equity_eur <= 0 or stop_distance_pct <= 0:
            return 0.0
        risk_budget = equity_eur * self.limits.max_risk_per_trade_pct / 100.0
        stop_based = risk_budget / (stop_distance_pct / 100.0)
        asset_cap = equity_eur * self.limits.max_asset_exposure_pct / 100.0
        remaining_asset_cap = max(0.0, asset_cap - max(0.0, current_asset_notional_eur))
        vol = max(annualized_volatility_pct, 0.01)
        vol_scale = min(1.0, self.limits.target_annualized_volatility_pct / vol)
        return max(0.0, min(stop_based, remaining_asset_cap) * vol_scale)
