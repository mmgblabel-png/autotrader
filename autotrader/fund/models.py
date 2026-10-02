"""Shared data contracts for the hedge-fund control plane."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


@dataclass(frozen=True)
class MarketObservation:
    symbol: str
    sector: str
    price: float
    returns: tuple[float, ...] = field(default_factory=tuple)
    volume_eur: float = 0.0
    spread_bps: float = 0.0
    sentiment_score: float = 0.0
    onchain_score: float = 0.0
    whale_score: float = 0.0

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper().replace("/", "-")
        sector = self.sector.strip().lower() or "other"
        if not symbol or "-" not in symbol:
            raise ValueError("symbol must be a normalized market such as BTC-EUR")
        price = _finite(self.price, "price")
        if price <= 0:
            raise ValueError("price must be positive")
        returns = tuple(_finite(x, "return") for x in self.returns)
        volume = max(0.0, _finite(self.volume_eur, "volume_eur"))
        spread = max(0.0, _finite(self.spread_bps, "spread_bps"))
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "sector", sector)
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "returns", returns)
        object.__setattr__(self, "volume_eur", volume)
        object.__setattr__(self, "spread_bps", spread)
        object.__setattr__(self, "sentiment_score", _clamp(self.sentiment_score, -1.0, 1.0))
        object.__setattr__(self, "onchain_score", _clamp(self.onchain_score, -1.0, 1.0))
        object.__setattr__(self, "whale_score", _clamp(self.whale_score, -1.0, 1.0))


@dataclass(frozen=True)
class AgentSignal:
    agent: str
    symbol: str
    score: float
    confidence: float
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", _clamp(self.score, -1.0, 1.0))
        object.__setattr__(self, "confidence", _clamp(self.confidence, 0.0, 1.0))


@dataclass(frozen=True)
class AlphaSignal:
    symbol: str
    sector: str
    score: float
    confidence: float
    expected_period_return: float
    annualized_volatility: float
    liquidity_score: float
    components: Mapping[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", _clamp(self.score, -1.0, 1.0))
        object.__setattr__(self, "confidence", _clamp(self.confidence, 0.0, 1.0))
        object.__setattr__(self, "liquidity_score", _clamp(self.liquidity_score, 0.0, 1.0))
        object.__setattr__(self, "expected_period_return", _finite(self.expected_period_return, "expected_period_return"))
        object.__setattr__(self, "annualized_volatility", max(0.0, _finite(self.annualized_volatility, "annualized_volatility")))


@dataclass(frozen=True)
class TargetAllocation:
    asset_weights: Mapping[str, float]
    cash_weight: float
    gross_exposure: float
    rationale: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    risk_level: str
    current_drawdown_pct: float
    daily_loss_pct: float
    breaches: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PerformanceMetrics:
    observations: int
    total_return_pct: float
    annualized_return_pct: float
    annualized_volatility_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    profit_factor: float
    max_drawdown_pct: float
    win_rate_pct: float
    expected_period_return_pct: float


@dataclass(frozen=True)
class NavSnapshot:
    observed_at: float
    equity_eur: float
    cash_eur: float
    gross_exposure_eur: float
    source: str = "system"

    def __post_init__(self) -> None:
        if _finite(self.equity_eur, "equity_eur") <= 0:
            raise ValueError("equity_eur must be positive")
        if _finite(self.cash_eur, "cash_eur") < 0:
            raise ValueError("cash_eur must be non-negative")
        if _finite(self.gross_exposure_eur, "gross_exposure_eur") < 0:
            raise ValueError("gross_exposure_eur must be non-negative")
        if not self.source.strip():
            raise ValueError("source must not be empty")


@dataclass(frozen=True)
class MarketBar:
    timestamp: float
    close: float
    volume_eur: float = 0.0
    spread_bps: float = 0.0

    def __post_init__(self) -> None:
        if _finite(self.close, "close") <= 0:
            raise ValueError("close must be positive")
        if _finite(self.volume_eur, "volume_eur") < 0:
            raise ValueError("volume_eur must be non-negative")
        if _finite(self.spread_bps, "spread_bps") < 0:
            raise ValueError("spread_bps must be non-negative")


def normalized_weights(weights: Mapping[str, float]) -> dict[str, float]:
    cleaned = {str(k): max(0.0, _finite(v, f"weight:{k}")) for k, v in weights.items()}
    total = sum(cleaned.values())
    return {k: v / total for k, v in cleaned.items()} if total > 0 else {k: 0.0 for k in cleaned}
