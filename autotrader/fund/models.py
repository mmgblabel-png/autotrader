"""Typed contracts shared by research, portfolio and risk layers."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Any, Mapping


def _bounded_float(name: str, value: object, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


@dataclass(frozen=True)
class FundMandate:
    """Hard fund-level operating mandate.

    Percentage fields use percentage points, so 8.0 means 8%.
    """

    fund_id: str = "autotrader-personal-fund"
    enabled: bool = True
    base_currency: str = "EUR"
    initial_nav_eur: float = 50.0
    target_nav_eur: float = 25000.0
    protected_capital_floor_eur: float = 25000.0
    lock_floor_after_target_reached: bool = True
    capital_floor_buffer_pct: float = 2.0
    max_portfolio_drawdown_pct: float = 8.0
    max_daily_loss_pct: float = 2.0
    max_single_trade_pct: float = 20.0
    max_gross_exposure_pct: float = 85.0
    max_strategy_exposure_pct: float = 40.0
    max_asset_exposure_pct: float = 35.0
    min_cash_reserve_pct: float = 15.0
    min_signal_confidence: float = 0.62
    signal_half_life_seconds: float = 900.0

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> "FundMandate":
        raw = dict(config or {})
        mandate = cls(
            fund_id=str(raw.get("fund_id", cls.fund_id)).strip() or cls.fund_id,
            enabled=bool(raw.get("enabled", True)),
            base_currency=str(raw.get("base_currency", "EUR")).upper().strip() or "EUR",
            initial_nav_eur=float(raw.get("initial_nav_eur", 50.0)),
            target_nav_eur=float(raw.get("target_nav_eur", 25000.0)),
            protected_capital_floor_eur=float(raw.get("protected_capital_floor_eur", 25000.0)),
            lock_floor_after_target_reached=bool(raw.get("lock_floor_after_target_reached", True)),
            capital_floor_buffer_pct=float(raw.get("capital_floor_buffer_pct", 2.0)),
            max_portfolio_drawdown_pct=float(raw.get("max_portfolio_drawdown_pct", 8.0)),
            max_daily_loss_pct=float(raw.get("max_daily_loss_pct", 2.0)),
            max_single_trade_pct=float(raw.get("max_single_trade_pct", 20.0)),
            max_gross_exposure_pct=float(raw.get("max_gross_exposure_pct", cls.max_gross_exposure_pct)),
            max_strategy_exposure_pct=float(raw.get("max_strategy_exposure_pct", 40.0)),
            max_asset_exposure_pct=float(raw.get("max_asset_exposure_pct", 35.0)),
            min_cash_reserve_pct=float(raw.get("min_cash_reserve_pct", 15.0)),
            min_signal_confidence=float(raw.get("min_signal_confidence", 0.62)),
            signal_half_life_seconds=float(raw.get("signal_half_life_seconds", 900.0)),
        )
        mandate.validate()
        return mandate

    def validate(self) -> None:
        if not self.fund_id:
            raise ValueError("fund_id must not be empty")
        if self.base_currency != "EUR":
            raise ValueError("AutoTrader Fund Core v1 currently requires EUR as base currency")
        if not math.isfinite(self.initial_nav_eur) or self.initial_nav_eur <= 0:
            raise ValueError("initial_nav_eur must be positive")
        if not math.isfinite(self.target_nav_eur) or self.target_nav_eur <= 0:
            raise ValueError("target_nav_eur must be positive")
        if (
            not math.isfinite(self.protected_capital_floor_eur)
            or self.protected_capital_floor_eur <= 0
        ):
            raise ValueError("protected_capital_floor_eur must be positive")
        if self.protected_capital_floor_eur > self.target_nav_eur:
            raise ValueError("protected_capital_floor_eur cannot exceed target_nav_eur")
        _bounded_float("capital_floor_buffer_pct", self.capital_floor_buffer_pct, 0.0, 100.0)
        for name in (
            "max_portfolio_drawdown_pct",
            "max_daily_loss_pct",
            "max_single_trade_pct",
            "max_gross_exposure_pct",
            "max_strategy_exposure_pct",
            "max_asset_exposure_pct",
            "min_cash_reserve_pct",
        ):
            _bounded_float(name, getattr(self, name), 0.0, 1000.0)
        _bounded_float("min_signal_confidence", self.min_signal_confidence, 0.0, 1.0)
        if self.signal_half_life_seconds <= 0 or not math.isfinite(self.signal_half_life_seconds):
            raise ValueError("signal_half_life_seconds must be positive")
        if self.min_cash_reserve_pct >= 100.0:
            raise ValueError("min_cash_reserve_pct must be below 100")
        if self.max_gross_exposure_pct > 100.0 - self.min_cash_reserve_pct:
            raise ValueError(
                "max_gross_exposure_pct cannot exceed the capital left after min_cash_reserve_pct"
            )


@dataclass(frozen=True)
class AgentSignal:
    """Normalized research output. Agents never submit exchange orders directly."""

    agent: str
    strategy: str
    symbol: str
    direction: float
    confidence: float
    score: float
    horizon_seconds: int
    timestamp: float = field(default_factory=time.time)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validated(self) -> "AgentSignal":
        agent = self.agent.strip()
        strategy = self.strategy.strip()
        symbol = self.symbol.upper().replace("/", "-").strip()
        if not agent or not strategy or not symbol:
            raise ValueError("agent, strategy and symbol are required")
        _bounded_float("direction", self.direction, -1.0, 1.0)
        _bounded_float("confidence", self.confidence, 0.0, 1.0)
        _bounded_float("score", self.score, 0.0, 100.0)
        if self.horizon_seconds <= 0:
            raise ValueError("horizon_seconds must be positive")
        if not math.isfinite(self.timestamp) or self.timestamp <= 0:
            raise ValueError("timestamp must be a positive unix timestamp")
        return AgentSignal(
            agent=agent,
            strategy=strategy,
            symbol=symbol,
            direction=float(self.direction),
            confidence=float(self.confidence),
            score=float(self.score),
            horizon_seconds=int(self.horizon_seconds),
            timestamp=float(self.timestamp),
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class BlendedSignal:
    strategy: str
    symbol: str
    direction: float
    confidence: float
    score: float
    source_count: int
    timestamp: float


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reason: str
    risk_reducing: bool
    nav_eur: float
    drawdown_pct: float
    daily_loss_pct: float
    gross_exposure_pct: float
    strategy_exposure_pct: float
    asset_exposure_pct: float
    capital_floor_armed: bool = False
    protected_capital_floor_eur: float = 0.0
    protected_zone_eur: float = 0.0
    risk_capital_available_eur: float = 0.0
    required_deleveraging_eur: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "risk_reducing": self.risk_reducing,
            "nav_eur": round(self.nav_eur, 6),
            "drawdown_pct": round(self.drawdown_pct, 6),
            "daily_loss_pct": round(self.daily_loss_pct, 6),
            "gross_exposure_pct": round(self.gross_exposure_pct, 6),
            "strategy_exposure_pct": round(self.strategy_exposure_pct, 6),
            "asset_exposure_pct": round(self.asset_exposure_pct, 6),
            "capital_floor_armed": self.capital_floor_armed,
            "protected_capital_floor_eur": round(self.protected_capital_floor_eur, 6),
            "protected_zone_eur": round(self.protected_zone_eur, 6),
            "risk_capital_available_eur": round(self.risk_capital_available_eur, 6),
            "required_deleveraging_eur": round(self.required_deleveraging_eur, 6),
        }
