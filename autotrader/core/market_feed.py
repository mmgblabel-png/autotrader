"""Read-only Bitpanda Fusion market feed with strict BTC-EUR validation."""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter, BitpandaFusionError


@dataclass(frozen=True)
class MarketTick:
    pair: str
    price: Decimal
    fetched_at: float
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "pair": self.pair,
            "price": str(self.price),
            "high": str(self.high) if self.high is not None else None,
            "low": str(self.low) if self.low is not None else None,
            "volume": str(self.volume) if self.volume is not None else None,
            "fetched_at": self.fetched_at,
            "age_seconds": max(0.0, time.time() - self.fetched_at),
            "stale": False,
        }


class BitpandaFusionMarketFeed:
    """Fetch current Fusion ticker and pair constraints without order access."""

    def __init__(self, adapter: BitpandaFusionAdapter | None = None, *, pair: str = "BTC-EUR", stale_after: float = 15.0) -> None:
        self.adapter = adapter or BitpandaFusionAdapter()
        self.pair = pair.upper().strip()
        self.stale_after = stale_after
        self.last_tick: MarketTick | None = None
        self.last_error: str | None = None

    @staticmethod
    def _positive(value: Any, field: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"invalid_{field}") from exc
        if not result.is_finite() or result <= 0:
            raise ValueError(f"invalid_{field}")
        return result

    def fetch_once(self) -> dict[str, Any]:
        try:
            pairs = self.adapter.get_pairs(pair=self.pair)
            if not isinstance(pairs, list) or not any(str(row.get("pair", "")).upper() == self.pair for row in pairs if isinstance(row, dict)):
                raise ValueError("pair_unavailable")
            tickers = self.adapter.get_tickers(pair=self.pair)
            if not isinstance(tickers, list):
                raise ValueError("invalid_ticker_response")
            row = next((row for row in tickers if isinstance(row, dict) and str(row.get("pair", "")).upper() == self.pair), None)
            if row is None:
                raise ValueError("ticker_missing")
            tick = MarketTick(
                pair=self.pair,
                price=self._positive(row.get("price"), "price"),
                fetched_at=time.time(),
                high=self._positive(row["high"], "high") if row.get("high") is not None else None,
                low=self._positive(row["low"], "low") if row.get("low") is not None else None,
                volume=self._positive(row["volume"], "volume") if row.get("volume") is not None else None,
            )
            if tick.high is not None and tick.low is not None and tick.low > tick.high:
                raise ValueError("invalid_high_low")
            self.last_tick = tick
            self.last_error = None
            result = tick.as_dict()
            result.update({"status": "live", "source": "bitpanda_fusion", "orders_enabled": False})
            return result
        except (BitpandaFusionError, ValueError) as exc:
            self.last_error = getattr(exc, "category", str(exc))
            return {
                "status": "unavailable",
                "source": "bitpanda_fusion",
                "pair": self.pair,
                "price": None,
                "stale": True,
                "orders_enabled": False,
                "error": self.last_error,
            }

    def status(self) -> dict[str, Any]:
        if self.last_tick is None:
            return {"status": "unavailable", "pair": self.pair, "price": None, "stale": True, "orders_enabled": False, "error": self.last_error or "not_checked"}
        result = self.last_tick.as_dict()
        result["status"] = "stale" if result["age_seconds"] > self.stale_after else "live"
        result["source"] = "bitpanda_fusion"
        result["orders_enabled"] = False
        if self.last_error:
            result["error"] = self.last_error
        return result
