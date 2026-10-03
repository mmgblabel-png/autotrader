"""Quant primitives for short-horizon binary BTC direction markets.

The X-post that motivated this module describes a Z-score based fair-value
model.  This implementation uses log-price distance, realized volatility and
remaining time, then applies explicit transaction-cost and sizing gates.
Nothing in this module submits orders.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Sequence

SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60


@dataclass(frozen=True)
class ZScoreConfig:
    min_sigma_annual: float = 0.10
    max_sigma_annual: float = 3.00
    min_seconds_to_expiry: float = 20.0
    twap_window_seconds: float = 60.0
    log_drift_annual: float = 0.0
    min_after_cost_edge: float = 0.025
    safety_margin_bps: float = 75.0
    kelly_fraction: float = 0.25
    max_bankroll_fraction: float = 0.05
    max_stake: float = 5.0
    min_stake: float = 1.0


@dataclass(frozen=True)
class RealizedVolatility:
    sigma_annual: float
    observations: int
    elapsed_seconds: float


@dataclass(frozen=True)
class ProbabilityEstimate:
    fair_up: float
    fair_down: float
    z_score: float
    sigma_annual: float
    effective_seconds: float


@dataclass(frozen=True)
class EdgeDecision:
    side: str
    probability: float
    entry_price: float
    gross_edge: float
    after_cost_edge: float
    friction: float
    reason: str

    @property
    def tradable(self) -> bool:
        return self.side in {"UP", "DOWN"} and self.after_cost_edge > 0.0


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def annualized_realized_volatility(
    timestamped_prices: Sequence[tuple[float, float]],
    *,
    min_observations: int = 12,
    min_sigma_annual: float = 0.10,
    max_sigma_annual: float = 3.00,
) -> RealizedVolatility:
    """Estimate annualized sigma from irregularly sampled log returns.

    Variance is accumulated in event time and normalized by actual elapsed
    seconds, making the estimator suitable for 1-10 second research feeds.
    Extreme single-tick log returns are Winsorized at six median absolute
    deviations to reduce bad-tick sensitivity without hiding broad volatility.
    """
    rows = [(float(ts), float(price)) for ts, price in timestamped_prices if price > 0]
    rows.sort(key=lambda item: item[0])
    if len(rows) < min_observations:
        raise ValueError("insufficient price observations for realized volatility")

    returns: list[tuple[float, float]] = []
    for (t0, p0), (t1, p1) in zip(rows, rows[1:]):
        dt = t1 - t0
        if dt <= 0 or p0 <= 0 or p1 <= 0:
            continue
        returns.append((dt, math.log(p1 / p0)))
    if len(returns) < min_observations - 1:
        raise ValueError("insufficient monotonic price observations")

    raw = [ret for _, ret in returns]
    median = statistics.median(raw)
    deviations = [abs(x - median) for x in raw]
    mad = statistics.median(deviations)
    if mad > 0:
        cap = 6.0 * 1.4826 * mad
        clipped = [max(median - cap, min(median + cap, x)) for x in raw]
    else:
        clipped = raw

    elapsed = sum(dt for dt, _ in returns)
    if elapsed <= 0:
        raise ValueError("non-positive observation horizon")
    mean_return = statistics.fmean(clipped)
    centered_ss = sum((ret - mean_return) ** 2 for ret in clipped)
    variance_per_second = centered_ss / elapsed
    sigma = math.sqrt(max(0.0, variance_per_second) * SECONDS_PER_YEAR)
    sigma = max(float(min_sigma_annual), min(float(max_sigma_annual), sigma))
    return RealizedVolatility(sigma_annual=sigma, observations=len(rows), elapsed_seconds=elapsed)


def fair_up_probability(
    *,
    spot: float,
    strike: float,
    sigma_annual: float,
    seconds_to_expiry: float,
    config: ZScoreConfig | None = None,
) -> ProbabilityEstimate:
    """Return a lognormal Z-score approximation for ``P(settlement >= strike)``.

    ``spot`` should be the latest settlement-source proxy (Chainlink 60-second
    TWAP for the current Polymarket BTC 5m/15m contracts).  The model uses a
    log-price drift parameter rather than an arithmetic-price drift, so a zero
    drift gives exactly 50% when spot equals strike.
    """
    cfg = config or ZScoreConfig()
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if seconds_to_expiry < cfg.min_seconds_to_expiry:
        raise ValueError("too close to expiry for configured model")
    sigma = max(cfg.min_sigma_annual, min(cfg.max_sigma_annual, float(sigma_annual)))
    # A 60s TWAP contains information from an interval rather than a point.
    # Reducing the effective horizon by half that window avoids pretending the
    # full remaining interval is unobserved while staying deliberately simple.
    effective_seconds = max(
        cfg.min_seconds_to_expiry,
        float(seconds_to_expiry) - max(0.0, cfg.twap_window_seconds) / 2.0,
    )
    years = effective_seconds / SECONDS_PER_YEAR
    denom = sigma * math.sqrt(years)
    if denom <= 0:
        raise ValueError("invalid volatility/time denominator")
    z = (math.log(spot / strike) + cfg.log_drift_annual * years) / denom
    fair_up = max(0.000001, min(0.999999, _normal_cdf(z)))
    return ProbabilityEstimate(
        fair_up=fair_up,
        fair_down=1.0 - fair_up,
        z_score=z,
        sigma_annual=sigma,
        effective_seconds=effective_seconds,
    )


def evaluate_binary_edge(
    *,
    estimate: ProbabilityEstimate,
    up_ask: float,
    down_ask: float,
    fee_bps: float,
    slippage_bps: float,
    config: ZScoreConfig | None = None,
) -> EdgeDecision:
    """Choose the stronger BUY side after conservative all-in entry friction."""
    cfg = config or ZScoreConfig()
    for name, price in (("up_ask", up_ask), ("down_ask", down_ask)):
        if not 0.0 < float(price) < 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
    friction = max(0.0, float(fee_bps) + float(slippage_bps) + cfg.safety_margin_bps) / 10_000.0
    candidates = [
        ("UP", estimate.fair_up, float(up_ask)),
        ("DOWN", estimate.fair_down, float(down_ask)),
    ]
    scored = []
    for side, probability, ask in candidates:
        gross = probability - ask
        scored.append((gross - friction, side, probability, ask, gross))
    after, side, probability, ask, gross = max(scored, key=lambda row: row[0])
    if after < cfg.min_after_cost_edge:
        return EdgeDecision(
            side="HOLD",
            probability=probability,
            entry_price=ask,
            gross_edge=gross,
            after_cost_edge=after,
            friction=friction,
            reason=f"edge_below_threshold:{after:.6f}<{cfg.min_after_cost_edge:.6f}",
        )
    return EdgeDecision(
        side=side,
        probability=probability,
        entry_price=ask,
        gross_edge=gross,
        after_cost_edge=after,
        friction=friction,
        reason=f"after_cost_edge_{after:.6f}",
    )


def fractional_kelly_stake(
    *,
    bankroll: float,
    probability: float,
    entry_price: float,
    config: ZScoreConfig | None = None,
) -> float:
    """Size a $1 binary payout with fractional Kelly and hard notional caps."""
    cfg = config or ZScoreConfig()
    bankroll = max(0.0, float(bankroll))
    probability = max(0.0, min(1.0, float(probability)))
    entry = float(entry_price)
    if bankroll <= 0 or not 0 < entry < 1:
        return 0.0
    b = (1.0 - entry) / entry
    if b <= 0:
        return 0.0
    raw_fraction = (b * probability - (1.0 - probability)) / b
    if raw_fraction <= 0:
        return 0.0
    fraction = min(cfg.max_bankroll_fraction, raw_fraction * cfg.kelly_fraction)
    stake = min(cfg.max_stake, bankroll * fraction)
    return 0.0 if stake < cfg.min_stake else stake
