"""Read-only prediction-market research components.

The package contains no order submission path.  It is intentionally isolated
from :mod:`autotrader.connectors.polymarket`, which owns the separately gated
execution adapter.
"""

from .model import (
    EdgeDecision,
    ProbabilityEstimate,
    RealizedVolatility,
    ZScoreConfig,
    annualized_realized_volatility,
    evaluate_binary_edge,
    fair_up_probability,
    fractional_kelly_stake,
)
from .shadow import PolymarketShadowLedger, ShadowPosition, ShadowStats

__all__ = [
    "EdgeDecision",
    "ProbabilityEstimate",
    "RealizedVolatility",
    "ZScoreConfig",
    "annualized_realized_volatility",
    "evaluate_binary_edge",
    "fair_up_probability",
    "fractional_kelly_stake",
    "PolymarketShadowLedger",
    "ShadowPosition",
    "ShadowStats",
]
