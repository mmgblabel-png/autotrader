"""Portfolio-level capital preservation controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import time
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
    capital_floor_armed: bool = False
    nav_verified: bool = False
    nav_source: str = "initial_config"
    nav_updated_at: float | None = None


class FundRiskEngine:
    """Hard fund-level risk layer for a long-only spot portfolio.

    The protected-capital floor is deliberately conservative. It is dormant
    while the account grows toward its target. Once target NAV has been reached,
    the floor latches permanently and only capital above the protected zone may
    support risk-increasing exposure. Existing exposure above that surplus must
    be reduced before new risk can be added.

    This cannot guarantee a EUR balance against market gaps, venue insolvency,
    custody loss or execution slippage; it prevents the trading system itself
    from intentionally re-risking protected capital after the target is reached.
    """

    def __init__(self, mandate: FundMandate) -> None:
        self.mandate = mandate
        initial = float(mandate.initial_nav_eur)
        floor_armed = bool(
            mandate.lock_floor_after_target_reached
            and initial >= mandate.target_nav_eur
        )
        self.state = FundRiskState(
            current_nav_eur=initial,
            peak_nav_eur=initial,
            day_start_nav_eur=initial,
            day_key=self._utc_day_key(),
            capital_floor_armed=floor_armed,
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

    @property
    def protected_zone_eur(self) -> float:
        floor = float(self.mandate.protected_capital_floor_eur)
        buffer_pct = max(0.0, float(self.mandate.capital_floor_buffer_pct))
        return floor * (1.0 + buffer_pct / 100.0)

    @property
    def risk_capital_available_eur(self) -> float:
        if not self.state.capital_floor_armed:
            return max(0.0, self.state.current_nav_eur)
        return max(0.0, self.state.current_nav_eur - self.protected_zone_eur)

    @property
    def required_deleveraging_eur(self) -> float:
        if not self.state.capital_floor_armed:
            return 0.0
        return max(0.0, self.gross_exposure_eur - self.risk_capital_available_eur)

    def restore_capital_floor_armed(self) -> None:
        """Restore the latched floor and its minimum high-water mark after restart."""
        if self.mandate.lock_floor_after_target_reached:
            self.state.capital_floor_armed = True
            self.state.peak_nav_eur = max(
                self.state.peak_nav_eur,
                float(self.mandate.target_nav_eur),
            )

    def restore_peak_nav(self, peak_nav_eur: float) -> None:
        """Restore a durable historical high-water mark without changing current NAV."""
        value = float(peak_nav_eur)
        if not math.isfinite(value) or value <= 0:
            return
        self.state.peak_nav_eur = max(self.state.peak_nav_eur, value)
        if (
            self.mandate.lock_floor_after_target_reached
            and self.state.peak_nav_eur >= self.mandate.target_nav_eur
        ):
            self.state.capital_floor_armed = True

    def record_nav(
        self,
        nav_eur: float,
        *,
        source: str = "mark_to_market",
        verified: bool = False,
    ) -> bool:
        """Record NAV and provenance; return True only when the floor arms now."""
        value = float(nav_eur)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("nav_eur must be positive and finite")
        self._roll_day_if_needed()
        was_armed = self.state.capital_floor_armed
        self.state.current_nav_eur = value
        self.state.peak_nav_eur = max(self.state.peak_nav_eur, value)
        self.state.nav_verified = bool(verified)
        self.state.nav_source = str(source).strip() or "unknown"
        self.state.nav_updated_at = time.time()
        if (
            self.mandate.lock_floor_after_target_reached
            and self.state.peak_nav_eur >= self.mandate.target_nav_eur
        ):
            self.state.capital_floor_armed = True
        return self.state.capital_floor_armed and not was_armed

    def mark_nav_unverified(self, source: str = "unverified") -> None:
        """Invalidate NAV provenance without overwriting the last numeric NAV."""
        self.state.nav_verified = False
        self.state.nav_source = str(source).strip() or "unverified"

    def nav_age_seconds(self, *, now: float | None = None) -> float | None:
        if self.state.nav_updated_at is None:
            return None
        current = time.time() if now is None else float(now)
        return max(0.0, current - self.state.nav_updated_at)

    def live_nav_is_fresh(self, *, now: float | None = None) -> bool:
        age = self.nav_age_seconds(now=now)
        return bool(
            self.state.nav_verified
            and age is not None
            and age <= self.mandate.live_nav_max_age_seconds
        )

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
        require_verified_nav: bool = False,
    ) -> RiskDecision:
        self._roll_day_if_needed()
        nav = max(self.state.current_nav_eur, 1e-12)
        notional = max(0.0, float(notional_eur))
        strategy_key = str(strategy).strip()
        symbol_key = str(symbol).upper().replace("/", "-").strip()

        drawdown = self.drawdown_pct()
        daily_loss = self.daily_loss_pct()
        gross_exposure_eur = self.gross_exposure_eur
        gross = gross_exposure_eur / nav * 100.0
        strategy_exposure = self.state.strategy_exposure_eur.get(strategy_key, 0.0) / nav * 100.0
        asset_exposure = (
            self.state.asset_exposure_eur.get(symbol_key, 0.0) / nav * 100.0
            if symbol_key
            else 0.0
        )
        risk_capital = self.risk_capital_available_eur
        deleveraging = self.required_deleveraging_eur
        nav_age = self.nav_age_seconds()

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
                capital_floor_armed=self.state.capital_floor_armed,
                protected_capital_floor_eur=self.mandate.protected_capital_floor_eur,
                protected_zone_eur=self.protected_zone_eur,
                risk_capital_available_eur=risk_capital,
                required_deleveraging_eur=deleveraging,
                nav_verified=self.state.nav_verified,
                nav_source=self.state.nav_source,
                nav_age_seconds=nav_age,
            )

        if not self.mandate.enabled:
            return decision(True, "fund risk layer disabled")
        if risk_reducing:
            return decision(True, "risk-reducing order allowed")
        if notional <= 0:
            return decision(False, "notional must be positive")
        if require_verified_nav and not self.state.nav_verified:
            return decision(False, "live fund NAV is not verified")
        if (
            require_verified_nav
            and (
                nav_age is None
                or nav_age > self.mandate.live_nav_max_age_seconds
            )
        ):
            return decision(False, "live fund NAV is stale")

        if self.state.capital_floor_armed:
            if deleveraging > 1e-9:
                return decision(
                    False,
                    "protected capital floor active; existing exposure must be reduced",
                )
            if gross_exposure_eur + notional > risk_capital + 1e-9:
                return decision(
                    False,
                    "protected capital floor active; total exposure would exceed surplus risk capital",
                )

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
        target = max(float(self.mandate.target_nav_eur), 1e-12)
        risk_capital = self.risk_capital_available_eur
        required_deleveraging = self.required_deleveraging_eur
        return {
            "nav_eur": round(self.state.current_nav_eur, 6),
            "peak_nav_eur": round(self.state.peak_nav_eur, 6),
            "day_start_nav_eur": round(self.state.day_start_nav_eur, 6),
            "daily_realized_pnl_eur": round(self.state.daily_realized_pnl_eur, 6),
            "drawdown_pct": round(self.drawdown_pct(), 6),
            "daily_loss_pct": round(self.daily_loss_pct(), 6),
            "gross_exposure_eur": round(self.gross_exposure_eur, 6),
            "gross_exposure_pct": round(self.gross_exposure_eur / nav * 100.0, 6),
            "target_nav_eur": round(self.mandate.target_nav_eur, 6),
            "target_progress_pct": round(min(100.0, nav / target * 100.0), 6),
            "target_reached": self.state.peak_nav_eur >= self.mandate.target_nav_eur,
            "capital_floor_armed": self.state.capital_floor_armed,
            "protected_capital_floor_eur": round(self.mandate.protected_capital_floor_eur, 6),
            "capital_floor_buffer_pct": round(self.mandate.capital_floor_buffer_pct, 6),
            "protected_zone_eur": round(self.protected_zone_eur, 6),
            "risk_capital_available_eur": round(risk_capital, 6),
            "required_deleveraging_eur": round(required_deleveraging, 6),
            "nav_verified": self.state.nav_verified,
            "nav_source": self.state.nav_source,
            "nav_age_seconds": (
                None
                if self.nav_age_seconds() is None
                else round(float(self.nav_age_seconds()), 6)
            ),
            "live_nav_max_age_seconds": round(self.mandate.live_nav_max_age_seconds, 6),
            "capital_preservation_mode": bool(
                self.state.capital_floor_armed
                and (required_deleveraging > 1e-9 or risk_capital <= 1e-9)
            ),
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
