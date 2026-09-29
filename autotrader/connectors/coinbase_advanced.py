"""Read-only Coinbase Advanced market-data connector.

Uses Coinbase's public Advanced Trade REST endpoints only. No API key is
required and this module contains no order-placement capability.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


class CoinbaseMarketDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoinbaseTopOfBook:
    product_id: str
    bid_price: Decimal
    bid_size: Decimal
    ask_price: Decimal
    ask_size: Decimal

    @property
    def mid_price(self) -> Decimal:
        return (self.bid_price + self.ask_price) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal:
        if self.mid_price <= 0:
            return Decimal("0")
        return (self.ask_price - self.bid_price) / self.mid_price * Decimal("10000")


class CoinbaseAdvancedMarketData:
    """Minimal fail-closed client for Coinbase Advanced public market data."""

    BASE_URL = "https://api.coinbase.com"
    BOOK_PATH = "/api/v3/brokerage/market/product_book"

    def __init__(self, *, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self.BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "autotrader-coinbase-marketdata/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CoinbaseMarketDataError("Coinbase public market-data request failed") from exc

    @staticmethod
    def normalize_product_id(symbol: str) -> str:
        return symbol.strip().upper().replace("/", "-")

    def top_of_book(self, symbol: str) -> CoinbaseTopOfBook:
        product_id = self.normalize_product_id(symbol)
        payload = self._get(
            self.BOOK_PATH,
            {"product_id": product_id, "limit": "1"},
        )
        pricebook = payload.get("pricebook") if isinstance(payload, dict) else None
        bids = pricebook.get("bids") if isinstance(pricebook, dict) else None
        asks = pricebook.get("asks") if isinstance(pricebook, dict) else None
        if not bids or not asks:
            raise CoinbaseMarketDataError("Coinbase product book has no bid/ask")

        bid = bids[0]
        ask = asks[0]
        try:
            bid_price = Decimal(str(bid["price"]))
            bid_size = Decimal(str(bid["size"]))
            ask_price = Decimal(str(ask["price"]))
            ask_size = Decimal(str(ask["size"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise CoinbaseMarketDataError("Unexpected Coinbase product-book response") from exc

        if bid_price <= 0 or ask_price <= 0 or bid_size <= 0 or ask_size <= 0:
            raise CoinbaseMarketDataError("Invalid Coinbase top-of-book values")
        if ask_price < bid_price:
            raise CoinbaseMarketDataError("Crossed Coinbase product book")

        return CoinbaseTopOfBook(
            product_id=product_id,
            bid_price=bid_price,
            bid_size=bid_size,
            ask_price=ask_price,
            ask_size=ask_size,
        )
