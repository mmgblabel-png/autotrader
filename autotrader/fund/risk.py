"""Portfolio-level capital preservation controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Dict

from autotrader.fund.models import FundMandate, RiskDecision


@dataclass
class FundRiskState:
    current_nav_eur: float
    peak_nav_eur: float
    day_start_nav_eur: float
    daily_realized_pnl_eur: float = 0.0
    strategy_exposure_eur: Dict[str, float] = field(default_factory=dict)
    asset_exposure_eur: Dict[str, float] = field(default_factory=dict)
    day_key: str = ""


class FundRiskEngine:
    """Hard fund-level risk layer for a long-only spot portfolio."""

    def __init__(self, mandate: FundMandate) -> None:
        self.mandate = mandate
        initial = float(mandate.initial_nav_eur)
        self.state = FundRiskState(
            current_nav_eur=initial,
            peak_nav_eur=initial,
            day_start_nav_eur=initial,
            day_key=self._utc_day_key(),
        )

    @staticmethod
    def _utc_day_key() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _roll_day_if_needed(self) -> None:
        current = self._utc_day_key()
        if current == self.state.day_key:
            return
        self.state.day_key = current
        self.state.day_start_nav_eur = self.state.current_nav_eur
        self.state.daily_realized_pnl_eur = 0.0

    @property
    def gross_exposure_eur(self) -> float:
        return sum(max(0.0, value) for value in self.state.asset_exposure_eur.values())

    def record_nav(self, nav_eur: float) -> None:
        value = float(nav_eur)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("nav_eur must be positive and finite")
        self._roll_day_if_needed()
        self.state.current_nav_eur = value
        self.state.peak_nav_eur = max(self.state.peak_nav_eur, value)

    def record_realized_pnl(self, pnl_delta_eur: float) -> None:
        value = float(pnl_delta_eur)
        if not math.isfinite(value):
            raise ValueError("pnl_delta_eur must be finite")
        self._roll_day_if_needed()
        self.state.daily_realized_pnl_eur += value

    def record_fill(
        self,
        *,
        strategy: str,
        symbol: str,
        side: str,
        notional_eur: float,
    ) -> None:
        notional = max(0.0, float(notional_eur))
        if notional <= 0:
            return
        strategy_key = str(strategy).strip()
        symbol_key = str(symbol).upper().replace("/", "-").strip()
        side_key = str(side).upper().strip()
        if not strategy_key or not symbol_key or side_key not in {"BUY", "SELL"}:
            return

        sign = 1.0 if side_key == "BUY" else -1.0
        strategy_value = max(
            0.0,
            self.state.strategy_exposure_eur.get(strategy_key, 0.0) + sign * notional,
        )
        asset_value = max(
            0.0,
            self.state.asset_exposure_eur.get(symbol_key, 0.0) + sign * notional,
        )
        self.state.strategy_exposure_eur[strategy_key] = strategy_value
        self.state.asset_exposure_eur[symbol_key] = asset_value

    def drawdown_pct(self) -> float:
        peak = max(self.state.peak_nav_eur, 1e-12)
        return max(0.0, (peak - self.state.current_nav_eur) / peak * 100.0)

    def daily_loss_pct(self) -> float:
        base = max(self.state.day_start_nav_eur, 1e-12)
        return max(0.0, -self.state.daily_realized_pnl_eur / base * 100.0)

    def pretrade_check(
        self,
        *,
        strategy: str,
        notional_eur: float,
        symbol: str = "",
        risk_reducing: bool = False,
    ) -> RiskDecision:
        self._roll_day_if_needed()
        nav = max(self.state.current_nav_eur, 1e-12)
        notional = max(0.0, float(notional_eur))
        strategy_key = str(strategy).strip()
        symbol_key = str(symbol).upper().replace("/", "-").strip()

        drawdown = self.drawdown_pct()
        daily_loss = self.daily_loss_pct()
        gross = self.gross_exposure_eur / nav * 100.0
        strategy_exposure = self.state.strategy_exposure_eur.get(strategy_key, 0.0) / nav * 100.0
        asset_exposure = (
            self.state.asset_exposure_eur.get(symbol_key, 0.0) / nav * 100.0
            if symbol_key
            else 0.0
        )

        def decision(accepted: bool, reason: str) -> RiskDecision:
            return RiskDecision(
                accepted=accepted,
                reason=reason,
                risk_reducing=bool(risk_reducing),
                nav_eur=nav,
                drawdown_pct=drawdown,
                daily_loss_pct=daily_loss,
                gross_exposure_pct=gross,
                strategy_exposure_pct=strategy_exposure,
                asset_exposure_pct=asset_exposure,
            )

        if not self.mandate.enabled:
            return decision(True, "fund risk layer disabled")
        if risk_reducing:
            return decision(True, "risk-reducing order allowed")
        if notional <= 0:
            return decision(False, "notional must be positive")
        if drawdown >= self.mandate.max_portfolio_drawdown_pct:
            return decision(False, "maximum portfolio drawdown reached")
        if daily_loss >= self.mandate.max_daily_loss_pct:
            return decision(False, "maximum daily fund loss reached")

        trade_pct = notional / nav * 100.0
        if trade_pct > self.mandate.max_single_trade_pct:
            return decision(False, "single-trade fund limit exceeded")
        if gross + trade_pct > self.mandate.max_gross_exposure_pct:
            return decision(False, "maximum gross exposure exceeded")
        if strategy_exposure + trade_pct > self.mandate.max_strategy_exposure_pct:
            return decision(False, "maximum strategy exposure exceeded")
        if symbol_key and asset_exposure + trade_pct > self.mandate.max_asset_exposure_pct:
            return decision(False, "maximum asset exposure exceeded")

        return decision(True, "fund risk checks passed")

    def status(self) -> dict[str, object]:
        self._roll_day_if_needed()
        nav = max(self.state.current_nav_eur, 1e-12)
        return {
            "nav_eur": round(self.state.current_nav_eur, 6),
            "peak_nav_eur": round(self.state.peak_nav_eur, 6),
            "day_start_nav_eur": round(self.state.day_start_nav_eur, 6),
            "daily_realized_pnl_eur": round(self.state.daily_realized_pnl_eur, 6),
            "drawdown_pct": round(self.drawdown_pct(), 6),
            "daily_loss_pct": round(self.daily_loss_pct(), 6),
            "gross_exposure_eur": round(self.gross_exposure_eur, 6),
            "gross_exposure_pct": round(self.gross_exposure_eur / nav * 100.0, 6),
            "strategy_exposure_eur": {
                key: round(value, 6)
                for key, value in sorted(self.state.strategy_exposure_eur.items())
            },
            "asset_exposure_eur": {
                key: round(value, 6)
                for key, value in sorted(self.state.asset_exposure_eur.items())
            },
            "limits": {
                "max_portfolio_drawdown_pct": self.mandate.max_portfolio_drawdown_pct,
                "max_daily_loss_pct": self.mandate.max_daily_loss_pct,
                "max_single_trade_pct": self.mandate.max_single_trade_pct,
                "max_gross_exposure_pct": self.mandate.max_gross_exposure_pct,
                "max_strategy_exposure_pct": self.mandate.max_strategy_exposure_pct,
                "max_asset_exposure_pct": self.mandate.max_asset_exposure_pct,
                "min_cash_reserve_pct": self.mandate.min_cash_reserve_pct,
            },
        }
