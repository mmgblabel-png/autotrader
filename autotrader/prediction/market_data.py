"""Read-only market discovery and order-book helpers for Polymarket.

Market discovery uses the public Gamma API and book reads use the public CLOB
endpoint.  There are deliberately no authentication headers and no HTTP methods
other than GET in this module.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BinaryMarket:
    market_id: str
    slug: str
    question: str
    duration_seconds: int
    window_start: float
    window_end: float
    up_token_id: str
    down_token_id: str
    min_order_size: float
    fees_enabled: bool
    resolution_source: str


@dataclass(frozen=True)
class TopOfBook:
    best_bid: float | None
    best_ask: float | None


class PolymarketPublicData:
    GAMMA_BASE = "https://gamma-api.polymarket.com"
    CLOB_BASE = "https://clob.polymarket.com"

    def __init__(self, timeout_seconds: float = 4.0) -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    def _get_json(self, url: str) -> Any:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "AutoTraderPredictionShadow/1.0"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def slug_for_window(duration_seconds: int, epoch_seconds: float) -> str:
        if duration_seconds not in {300, 900}:
            raise ValueError("supported durations are 300 and 900 seconds")
        start = int(epoch_seconds) // duration_seconds * duration_seconds
        return f"btc-updown-{duration_seconds // 60}m-{start}"

    def get_btc_updown_market(self, duration_seconds: int, epoch_seconds: float) -> BinaryMarket | None:
        slug = self.slug_for_window(duration_seconds, epoch_seconds)
        query = urllib.parse.urlencode({"slug": slug})
        payload = self._get_json(f"{self.GAMMA_BASE}/markets?{query}")
        if not isinstance(payload, list) or not payload:
            return None
        row = payload[0]
        if not isinstance(row, dict):
            return None
        question = str(row.get("question") or "")
        description = str(row.get("description") or "")
        resolution_source = str(row.get("resolutionSource") or "")
        if "up or down" not in question.lower():
            return None
        # Current 5m/15m products resolve from Chainlink TWAP.  Reject a market
        # instead of silently substituting Binance when the contract changes.
        contract_text = f"{description} {resolution_source}".lower()
        if "chainlink" not in contract_text or "twap" not in contract_text:
            return None
        try:
            tokens_raw = row.get("clobTokenIds")
            tokens = json.loads(tokens_raw) if isinstance(tokens_raw, str) else list(tokens_raw or [])
        except (json.JSONDecodeError, TypeError):
            return None
        outcomes_raw = row.get("outcomes")
        try:
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else list(outcomes_raw or [])
        except (json.JSONDecodeError, TypeError):
            return None
        if len(tokens) != 2 or len(outcomes) != 2:
            return None
        mapping = {str(outcome).strip().lower(): str(token) for outcome, token in zip(outcomes, tokens)}
        up_token = mapping.get("up") or mapping.get("yes")
        down_token = mapping.get("down") or mapping.get("no")
        if not up_token or not down_token:
            return None
        start = int(slug.rsplit("-", 1)[-1])
        return BinaryMarket(
            market_id=str(row.get("id") or ""),
            slug=slug,
            question=question,
            duration_seconds=duration_seconds,
            window_start=float(start),
            window_end=float(start + duration_seconds),
            up_token_id=up_token,
            down_token_id=down_token,
            min_order_size=float(row.get("orderMinSize") or 0.0),
            fees_enabled=bool(row.get("feesEnabled", False)),
            resolution_source=resolution_source or "Chainlink BTC/USD TWAP 60s",
        )

    @staticmethod
    def _top_of_book(payload: Any) -> TopOfBook:
        if not isinstance(payload, dict):
            raise ValueError("unexpected CLOB order-book response")
        bids = payload.get("bids") or []
        asks = payload.get("asks") or []

        def prices(rows: Any) -> list[float]:
            values: list[float] = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                try:
                    price = float(row.get("price"))
                except (TypeError, ValueError):
                    continue
                if 0 < price < 1:
                    values.append(price)
            return values

        bid_prices = prices(bids)
        ask_prices = prices(asks)
        return TopOfBook(
            best_bid=max(bid_prices) if bid_prices else None,
            best_ask=min(ask_prices) if ask_prices else None,
        )

    def order_book(self, token_id: str) -> TopOfBook:
        if not token_id or not str(token_id).isdigit():
            raise ValueError("numeric token_id is required")
        query = urllib.parse.urlencode({"token_id": str(token_id)})
        return self._top_of_book(self._get_json(f"{self.CLOB_BASE}/book?{query}"))
