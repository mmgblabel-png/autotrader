"""Fail-closed execution gateway for paper, shadow and future live modes.

This module deliberately does not place orders. It validates an execution
request and returns a reviewable decision. A venue adapter must be separately
implemented and audited before live execution can be enabled.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class ExecutionMode(StrEnum):
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class ExecutionRejected(RuntimeError):
    """Raised when a request fails a safety gate."""


@dataclass(frozen=True)
class ExecutionLimits:
    max_trade_eur: Decimal = Decimal("10")
    max_daily_exposure_eur: Decimal = Decimal("50")
    max_daily_loss_eur: Decimal = Decimal("25")
    max_slippage_bps: int = 50


@dataclass(frozen=True)
class ExecutionRequest:
    venue: str
    symbol: str
    side: str
    notional_eur: Decimal
    expected_price: Decimal
    observed_price: Decimal
    client_order_id: str
    timestamp: float


@dataclass(frozen=True)
class ExecutionDecision:
    accepted: bool
    mode: ExecutionMode
    reason: str
    client_order_id: str
    venue: str
    notional_eur: str


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _decimal_env(name: str, default: Decimal) -> Decimal:
    try:
        value = Decimal(os.getenv(name, str(default)).strip())
        return value if value.is_finite() and value >= 0 else default
    except (InvalidOperation, AttributeError):
        return default


def limits_from_environment() -> ExecutionLimits:
    return ExecutionLimits(
        max_trade_eur=_decimal_env("MAX_TRADE_EUR", Decimal("10")),
        max_daily_exposure_eur=_decimal_env("MAX_DAILY_EXPOSURE_EUR", Decimal("50")),
        max_daily_loss_eur=_decimal_env("MAX_DAILY_LOSS_EUR", Decimal("25")),
        max_slippage_bps=max(0, min(100, int(os.getenv("MAX_SLIPPAGE_BPS", "50")))),
    )


class ExecutionGateway:
    """Validate requests; live mode remains unavailable by design."""

    def __init__(self, limits: ExecutionLimits | None = None) -> None:
        self.limits = limits or limits_from_environment()
        self.daily_exposure_eur = Decimal("0")
        self.daily_loss_eur = Decimal("0")
        self._seen_order_ids: set[str] = set()

    @property
    def mode(self) -> ExecutionMode:
        raw = os.getenv("EXECUTION_MODE", "paper").strip().lower()
        try:
            return ExecutionMode(raw)
        except ValueError:
            return ExecutionMode.PAPER

    def reset_daily(self) -> None:
        self.daily_exposure_eur = Decimal("0")
        self.daily_loss_eur = Decimal("0")
        self._seen_order_ids.clear()

    def evaluate(self, request: ExecutionRequest) -> ExecutionDecision:
        now = time.time()
        if not request.client_order_id or request.client_order_id in self._seen_order_ids:
            return self._reject(request, "missing or duplicate client_order_id")
        if request.timestamp > now + 5 or now - request.timestamp > 30:
            return self._reject(request, "request timestamp is stale or invalid")
        if request.venue not in {"binance_spot", "polymarket"}:
            return self._reject(request, "venue is not allowlisted")
        if request.side not in {"BUY", "SELL"}:
            return self._reject(request, "side is invalid")
        if request.notional_eur <= 0 or request.notional_eur > self.limits.max_trade_eur:
            return self._reject(request, "per-trade EUR limit exceeded")
        if self.daily_exposure_eur + request.notional_eur > self.limits.max_daily_exposure_eur:
            return self._reject(request, "daily exposure limit exceeded")
        if self.daily_loss_eur >= self.limits.max_daily_loss_eur:
            return self._reject(request, "daily loss stop is active")
        if request.expected_price <= 0 or request.observed_price <= 0:
            return self._reject(request, "price must be positive")
        slippage_bps = abs(request.observed_price - request.expected_price) / request.expected_price * 10000
        if slippage_bps > self.limits.max_slippage_bps:
            return self._reject(request, "slippage limit exceeded")
        self._seen_order_ids.add(request.client_order_id)
        if self.mode is ExecutionMode.LIVE:
            return self._reject(request, "live execution adapter is not installed; no order was sent")
        self.daily_exposure_eur += request.notional_eur
        return ExecutionDecision(True, self.mode, "validated without sending an order", request.client_order_id, request.venue, str(request.notional_eur))

    def record_loss(self, amount_eur: Decimal) -> None:
        if amount_eur > 0:
            self.daily_loss_eur += amount_eur

    @staticmethod
    def _reject(request: ExecutionRequest, reason: str) -> ExecutionDecision:
        return ExecutionDecision(False, ExecutionMode.PAPER, reason, request.client_order_id, request.venue, str(request.notional_eur))

    def status(self) -> dict:
        return {
            "mode": self.mode.value,
            "live_execution_capability": "not_installed",
            "daily_exposure_eur": str(self.daily_exposure_eur),
            "daily_loss_eur": str(self.daily_loss_eur),
            "limits": {"max_trade_eur": str(self.limits.max_trade_eur), "max_daily_exposure_eur": str(self.limits.max_daily_exposure_eur), "max_daily_loss_eur": str(self.limits.max_daily_loss_eur), "max_slippage_bps": self.limits.max_slippage_bps},
        }


def live_activation_is_allowed() -> bool:
    """Return False until an audited adapter and independent approval exist."""
    return _bool_env("LIVE_EXECUTION_APPROVED", False) and _bool_env("LIVE_EXECUTION_ADAPTER_INSTALLED", False) and not _bool_env("EMERGENCY_STOP", True)


__all__ = ["ExecutionDecision", "ExecutionGateway", "ExecutionLimits", "ExecutionMode", "ExecutionRejected", "ExecutionRequest", "live_activation_is_allowed"]
