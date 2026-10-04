"""Read-only Coinbase derivatives opportunity scanner.

This module never submits orders. It ranks perpetual/future contracts from the
Coinbase Global Derivatives market-data gateway and performs a read-only auth
probe so production can determine what derivative capabilities the current CDP
key actually has.
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
    max_instruments: int = 24
    min_volume_usd: float = 100_000.0
    max_spread_bps: float = 40.0
    max_abs_funding: float = 0.01
    top_n: int = 10

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "CoinbaseDerivativesShadowConfig":
        raw = raw or {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            interval_seconds=max(15.0, float(raw.get("interval_seconds", 60.0))),
            max_instruments=max(4, min(100, int(raw.get("max_instruments", 24)))),
            min_volume_usd=max(0.0, float(raw.get("min_volume_usd", 100_000.0))),
            max_spread_bps=max(1.0, float(raw.get("max_spread_bps", 40.0))),
            max_abs_funding=max(0.000001, float(raw.get("max_abs_funding", 0.01))),
            top_n=max(1, min(25, int(raw.get("top_n", 10)))),
        )


class CoinbaseDerivativesShadowScanner:
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
            "mode": "shadow_only",
            "venue": "coinbase_global_derivatives",
            "live_orders_sent": False,
            "instrument_count": 0,
            "candidates": [],
            "auth_probe": {
                "authenticated": False,
                "risk_profile_readable": False,
                "positions_readable": False,
                "error_category": "not_probed",
                "order_sent": False,
            },
            "last_error": None,
            "updated_at": None,
        }

    @staticmethod
    def _perpetual_like(row: dict[str, Any]) -> bool:
        name = str(row.get("instrument_name") or "").upper()
        settlement = str(row.get("settlement_period") or "").lower()
        future_type = str(row.get("future_type") or "").lower()
        expiration = row.get("expiration_timestamp")
        return (
            "PERPETUAL" in name
            or "PERP" in name
            or settlement == "perpetual"
            or future_type == "perpetual"
            or expiration in {None, 0, "0"}
        )

    @staticmethod
    def _score(ticker: CoinbaseDerivativesTicker) -> float:
        volume_component = min(35.0, max(0.0, math.log10(max(1.0, ticker.volume_usd)) - 4.0) * 10.0)
        oi_component = min(20.0, max(0.0, math.log10(max(1.0, ticker.open_interest)) - 1.0) * 6.0)
        trend_component = min(20.0, abs(ticker.price_change_pct) * 4.0)
        spread_penalty = min(25.0, ticker.spread_bps * 0.8)
        funding_penalty = min(20.0, abs(ticker.current_funding) * 10000.0 * 0.25)
        return max(0.0, min(100.0, 50.0 + volume_component + oi_component + trend_component - spread_penalty - funding_penalty))

    def tick(self) -> dict[str, Any]:
        if not self.config.enabled:
            self._status.update({"enabled": False, "updated_at": time.time()})
            return self.status()

        rows = self.client.list_futures(currency="any")
        active = [
            row
            for row in rows
            if bool(row.get("is_active", True))
            and self._perpetual_like(row)
            and str(row.get("instrument_name") or "").strip()
        ]
        # Deterministic cap before ticker fan-out. Prefer instruments advertising
        # larger leverage caps only as a liquidity proxy; leverage is never used.
        active.sort(
            key=lambda row: (
                float(row.get("max_leverage") or 0.0),
                str(row.get("instrument_name") or ""),
            ),
            reverse=True,
        )
        active = active[: self.config.max_instruments]

        candidates: list[dict[str, Any]] = []
        for row in active:
            name = str(row.get("instrument_name") or "")
            try:
                tick = self.client.ticker(name)
            except Exception:
                continue
            if tick.volume_usd < self.config.min_volume_usd:
                continue
            if tick.spread_bps > self.config.max_spread_bps:
                continue
            if abs(tick.current_funding) > self.config.max_abs_funding:
                continue
            score = self._score(tick)
            direction = "LONG_BIAS" if tick.price_change_pct > 0 else ("SHORT_BIAS" if tick.price_change_pct < 0 else "NEUTRAL")
            candidates.append(
                {
                    "instrument": name,
                    "direction": direction,
                    "score": round(score, 3),
                    "mark_price": round(tick.mark_price, 10),
                    "index_price": round(tick.index_price, 10),
                    "spread_bps": round(tick.spread_bps, 4),
                    "volume_usd_24h": round(tick.volume_usd, 2),
                    "open_interest": round(tick.open_interest, 8),
                    "price_change_pct_24h": round(tick.price_change_pct, 6),
                    "current_funding": round(tick.current_funding, 10),
                    "contract_size": row.get("contract_size"),
                    "max_leverage_venue": row.get("max_leverage"),
                    "shadow_only": True,
                }
            )

        candidates.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
        auth_probe = self.client.auth_probe()
        self._status = {
            "enabled": True,
            "mode": "shadow_only",
            "venue": "coinbase_global_derivatives",
            "api_host": "https://drb.coinbase.com/api/v2",
            "instrument_count": len(rows),
            "perpetual_like_count": len(active),
            "candidate_count": len(candidates),
            "candidates": candidates[: self.config.top_n],
            "auth_probe": auth_probe,
            "live_orders_sent": False,
            "order_capability_implemented": False,
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
