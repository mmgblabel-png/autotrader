"""Read-only Coinbase futures confirmation scanner.

It ranks the nearest BTC/ETH/SOL/XRP futures from Coinbase Advanced public
market data and turns basis/order-book information into a bounded research
overlay for the existing SPOT execution engine. It never places futures orders.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from autotrader.connectors.coinbase_derivatives import (
    CoinbaseDerivativesGateway,
    CoinbaseDerivativesTicker,
)


@dataclass(frozen=True)
class CoinbaseDerivativesShadowConfig:
    enabled: bool = True
    interval_seconds: float = 60.0
    max_abs_basis_bps: float = 500.0
    max_spread_bps: float = 100.0
    min_open_interest: float = 10.0
    top_n: int = 4
    score_adjustment_max: float = 2.0

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "CoinbaseDerivativesShadowConfig":
        raw = raw or {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            interval_seconds=max(15.0, float(raw.get("interval_seconds", 60.0))),
            max_abs_basis_bps=max(25.0, float(raw.get("max_abs_basis_bps", 500.0))),
            max_spread_bps=max(5.0, float(raw.get("max_spread_bps", 100.0))),
            min_open_interest=max(0.0, float(raw.get("min_open_interest", 10.0))),
            top_n=max(1, min(10, int(raw.get("top_n", 4)))),
            score_adjustment_max=max(0.0, min(5.0, float(raw.get("score_adjustment_max", 2.0)))),
        )


class CoinbaseDerivativesShadowScanner:
    SPOT_MARKETS = {
        "BTC": "BTC-EUR",
        "ETH": "ETH-EUR",
        "SOL": "SOL-EUR",
        "XRP": "XRP-EUR",
    }

    def __init__(
        self,
        config: CoinbaseDerivativesShadowConfig | dict[str, Any] | None = None,
        *,
        client: CoinbaseDerivativesGateway | None = None,
    ) -> None:
        self.config = (
            config
            if isinstance(config, CoinbaseDerivativesShadowConfig)
            else CoinbaseDerivativesShadowConfig.from_mapping(config)
        )
        self.client = client or CoinbaseDerivativesGateway(timeout=5.0)
        self._status: dict[str, Any] = {
            "enabled": self.config.enabled,
            "mode": "shadow_confirmation",
            "venue": "coinbase_advanced_futures",
            "live_orders_sent": False,
            "order_capability_implemented": False,
            "instrument_count": 0,
            "candidate_count": 0,
            "candidates": [],
            "last_error": None,
            "updated_at": None,
        }

    @staticmethod
    def _direction(ticker: CoinbaseDerivativesTicker) -> tuple[str, str]:
        # This is deliberately a confirmation signal, not a return forecast.
        # Futures trend and basis must broadly agree before the direction is
        # treated as strong.
        change = ticker.price_change_pct
        basis = ticker.basis_bps
        if change > 0.15 and basis >= -15.0:
            return "LONG_BIAS", "positive_futures_trend"
        if change < -0.15 and basis <= 15.0:
            return "SHORT_BIAS", "negative_futures_trend"
        if basis > 35.0 and change >= 0:
            return "LONG_BIAS", "positive_basis"
        if basis < -35.0 and change <= 0:
            return "SHORT_BIAS", "negative_basis"
        return "NEUTRAL", "mixed_derivatives_signal"

    @staticmethod
    def _score(ticker: CoinbaseDerivativesTicker) -> float:
        oi_quality = min(25.0, max(0.0, math.log10(max(1.0, ticker.open_interest)) * 6.0))
        trend_quality = min(20.0, abs(ticker.price_change_pct) * 6.0)
        basis_quality = max(0.0, 15.0 - min(15.0, abs(ticker.basis_bps) * 0.06))
        spread_penalty = min(30.0, ticker.spread_bps * 0.35)
        margin_rate = max(ticker.long_margin_rate, ticker.short_margin_rate)
        margin_penalty = min(15.0, max(0.0, margin_rate - 0.10) * 60.0)
        return max(
            0.0,
            min(100.0, 45.0 + oi_quality + trend_quality + basis_quality - spread_penalty - margin_penalty),
        )

    def tick(self) -> dict[str, Any]:
        if not self.config.enabled:
            self._status.update({"enabled": False, "updated_at": time.time()})
            return self.status()

        instruments = self.client.nearest_crypto_futures()
        candidates: list[dict[str, Any]] = []
        skipped: dict[str, str] = {}
        for row in instruments:
            product_id = str(row.get("product_id") or "").upper().strip()
            try:
                ticker = self.client.ticker_from_product(row)
            except Exception as exc:
                skipped[product_id or "unknown"] = getattr(exc, "category", type(exc).__name__)
                continue

            if not ticker.session_open:
                skipped[product_id] = "session_closed"
                continue
            if ticker.open_interest < self.config.min_open_interest:
                skipped[product_id] = "open_interest_too_low"
                continue
            if ticker.spread_bps > self.config.max_spread_bps:
                skipped[product_id] = "spread_too_wide"
                continue
            if abs(ticker.basis_bps) > self.config.max_abs_basis_bps:
                skipped[product_id] = "basis_outlier"
                continue

            direction, reason = self._direction(ticker)
            score = self._score(ticker)
            strength = max(0.0, min(1.0, abs(score - 50.0) / 50.0))
            max_adjustment = self.config.score_adjustment_max
            signed_adjustment = (
                max_adjustment * strength
                if direction == "LONG_BIAS"
                else (-max_adjustment * strength if direction == "SHORT_BIAS" else 0.0)
            )
            candidates.append(
                {
                    "instrument": ticker.instrument_name,
                    "underlying": ticker.underlying,
                    "spot_market": self.SPOT_MARKETS.get(ticker.underlying),
                    "spot_reference_product": ticker.spot_product_id,
                    "direction": direction,
                    "signal_reason": reason,
                    "score": round(score, 3),
                    "score_adjustment_hint": round(signed_adjustment, 4),
                    "future_mid": round(ticker.mid_price, 10),
                    "spot_mid": round(ticker.index_price, 10),
                    "basis_bps": round(ticker.basis_bps, 4),
                    "spread_bps": round(ticker.spread_bps, 4),
                    "open_interest": round(ticker.open_interest, 8),
                    "price_change_pct_24h": round(ticker.price_change_pct, 6),
                    "contract_size": round(ticker.contract_size, 10),
                    "long_margin_rate": round(ticker.long_margin_rate, 8),
                    "short_margin_rate": round(ticker.short_margin_rate, 8),
                    "contract_expiry": ticker.contract_expiry,
                    "shadow_only": True,
                }
            )

        candidates.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
        self._status = {
            "enabled": True,
            "mode": "shadow_confirmation",
            "venue": "coinbase_advanced_futures",
            "instrument_count": len(instruments),
            "candidate_count": len(candidates),
            "candidates": candidates[: self.config.top_n],
            "skipped": skipped,
            "auth_probe": self.client.auth_probe(),
            "live_orders_sent": False,
            "order_capability_implemented": False,
            "signal_usage": "spot_confirmation_overlay",
            "score_adjustment_max": self.config.score_adjustment_max,
            "policy": {
                "live_derivatives_enabled": False,
                "spot_policy_unchanged": True,
                "leverage_used": False,
                "margin_orders_sent": False,
                "futures_orders_sent": False,
            },
            "last_error": None,
            "updated_at": time.time(),
        }
        return self.status()

    def status(self) -> dict[str, Any]:
        return dict(self._status)
