"""Read-only Coinbase CDE derivatives opportunity scanner.

The scanner converts perpetual-style futures funding, basis and margin data
into an auxiliary market-regime signal. It never places derivatives orders.
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
    product_codes: tuple[str, ...] = ("BIP", "ETP", "SLP", "XPP")
    max_abs_basis_bps: float = 250.0
    max_abs_funding: float = 0.05
    top_n: int = 4

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "CoinbaseDerivativesShadowConfig":
        raw = raw or {}
        codes = tuple(
            str(x).upper().strip()
            for x in (raw.get("product_codes") or ("BIP", "ETP", "SLP", "XPP"))
            if str(x).strip()
        )
        return cls(
            enabled=bool(raw.get("enabled", True)),
            interval_seconds=max(15.0, float(raw.get("interval_seconds", 60.0))),
            product_codes=codes or ("BIP", "ETP", "SLP", "XPP"),
            max_abs_basis_bps=max(10.0, float(raw.get("max_abs_basis_bps", 250.0))),
            max_abs_funding=max(0.000001, float(raw.get("max_abs_funding", 0.05))),
            top_n=max(1, min(10, int(raw.get("top_n", 4)))),
        )


class CoinbaseDerivativesShadowScanner:
    PRODUCT_TO_SPOT = {
        "BIP": "BTC-EUR",
        "ETP": "ETH-EUR",
        "SLP": "SOL-EUR",
        "XPP": "XRP-EUR",
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
            "mode": "shadow_signal",
            "venue": "coinbase_derivatives_exchange",
            "live_orders_sent": False,
            "instrument_count": 0,
            "candidates": [],
            "auth_probe": self.client.auth_probe(),
            "last_error": None,
            "updated_at": None,
        }

    @staticmethod
    def _score(ticker: CoinbaseDerivativesTicker) -> float:
        # Research-quality score, not an execution score. Reward usable pricing
        # and meaningful (but not extreme) carry/basis while penalising high
        # margin requirements.
        funding_component = min(18.0, abs(ticker.funding_rate) * 100000.0)
        basis_component = min(18.0, abs(ticker.basis_bps) * 0.35)
        price_integrity = 12.0 if ticker.mark_price > 0 and ticker.index_price > 0 else 0.0
        margin_pct = min(
            ticker.long_initial_margin_bps if ticker.long_initial_margin_bps > 0 else 10000.0,
            ticker.short_initial_margin_bps if ticker.short_initial_margin_bps > 0 else 10000.0,
        ) / 100.0
        margin_penalty = min(20.0, max(0.0, margin_pct - 10.0) * 0.5)
        return max(0.0, min(100.0, 50.0 + funding_component + basis_component + price_integrity - margin_penalty))

    @staticmethod
    def _bias(ticker: CoinbaseDerivativesTicker) -> tuple[str, str]:
        funding = ticker.funding_rate
        basis = ticker.basis_bps
        # Positive funding means longs pay shorts. Negative funding means shorts
        # pay longs. Basis agreement strengthens the carry signal.
        if funding > 0 and basis >= 0:
            return "SHORT_BIAS", "positive_funding_and_premium"
        if funding < 0 and basis <= 0:
            return "LONG_BIAS", "negative_funding_and_discount"
        if funding > 0:
            return "SHORT_BIAS", "positive_funding"
        if funding < 0:
            return "LONG_BIAS", "negative_funding"
        if basis > 5.0:
            return "SHORT_BIAS", "futures_premium"
        if basis < -5.0:
            return "LONG_BIAS", "futures_discount"
        return "NEUTRAL", "no_material_carry_edge"

    def tick(self) -> dict[str, Any]:
        if not self.config.enabled:
            self._status.update({"enabled": False, "updated_at": time.time()})
            return self.status()

        instruments = self.client.list_futures(product_codes=list(self.config.product_codes))
        candidates: list[dict[str, Any]] = []
        for row in instruments:
            if not bool(row.get("is_perp", False)):
                continue
            if str(row.get("trading_state") or "").upper() != "OPEN":
                continue
            symbol = str(row.get("symbol") or "").upper().strip()
            product_code = str(row.get("product_code") or "").upper().strip()
            if not symbol or product_code not in self.config.product_codes:
                continue
            try:
                tick = self.client.ticker_from_instrument(row)
            except Exception:
                continue
            if abs(tick.basis_bps) > self.config.max_abs_basis_bps:
                continue
            if abs(tick.funding_rate) > self.config.max_abs_funding:
                continue
            bias, reason = self._bias(tick)
            score = self._score(tick)
            candidates.append(
                {
                    "instrument": symbol,
                    "product_code": product_code,
                    "spot_market": self.PRODUCT_TO_SPOT.get(product_code),
                    "direction": bias,
                    "signal_reason": reason,
                    "score": round(score, 3),
                    "future_mark_price": round(tick.mark_price, 10),
                    "spot_mark_price": round(tick.index_price, 10),
                    "fair_value_price": round(tick.fair_value_price, 10),
                    "basis_bps": round(tick.basis_bps, 4),
                    "funding_rate": round(tick.funding_rate, 10),
                    "contract_size": round(tick.contract_size, 10),
                    "long_initial_margin_pct": round(tick.long_initial_margin_bps / 100.0, 4),
                    "short_initial_margin_pct": round(tick.short_initial_margin_bps / 100.0, 4),
                    "funding_interval_minutes": tick.funding_interval_minutes,
                    "shadow_only": True,
                }
            )

        candidates.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
        auth_probe = self.client.auth_probe()
        self._status = {
            "enabled": True,
            "mode": "shadow_signal",
            "venue": "coinbase_derivatives_exchange",
            "api_host": "https://api.exchange.fairx.net",
            "instrument_count": len(instruments),
            "candidate_count": len(candidates),
            "candidates": candidates[: self.config.top_n],
            "auth_probe": auth_probe,
            "live_orders_sent": False,
            "order_capability_implemented": False,
            "signal_usage": "research_overlay_only",
            "policy": {
                "live_derivatives_enabled": False,
                "spot_policy_unchanged": True,
                "leverage_used": False,
                "margin_orders_sent": False,
            },
            "last_error": None,
            "updated_at": time.time(),
        }
        return self.status()

    def status(self) -> dict[str, Any]:
        return dict(self._status)
