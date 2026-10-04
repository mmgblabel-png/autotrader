"""Read-only Coinbase derivatives market-data adapter.

The retail Coinbase account exposes derivatives through Coinbase's broker UI.
Direct CDE participant REST/FIX credentials are separate from the existing CDP
Advanced Trade key, so AutoTrader uses the Advanced public market-data surface
for derivative curve/order-book intelligence. This module never submits orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from autotrader.connectors.coinbase_advanced import (
    CoinbaseAdvancedMarketData,
    CoinbaseMarketDataError,
)


class CoinbaseDerivativesError(RuntimeError):
    def __init__(self, message: str, *, category: str = "derivatives_request_failed") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class CoinbaseDerivativesTicker:
    instrument_name: str
    underlying: str
    spot_product_id: str
    mark_price: float
    index_price: float
    best_bid_price: float
    best_ask_price: float
    open_interest: float
    price_change_pct: float
    contract_size: float
    long_margin_rate: float
    short_margin_rate: float
    contract_expiry: str
    session_open: bool

    @property
    def mid_price(self) -> float:
        if self.best_bid_price > 0 and self.best_ask_price > 0:
            return (self.best_bid_price + self.best_ask_price) / 2.0
        return self.mark_price

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        if mid <= 0 or self.best_ask_price <= 0 or self.best_bid_price <= 0:
            return 0.0
        return max(0.0, (self.best_ask_price - self.best_bid_price) / mid * 10000.0)

    @property
    def basis_bps(self) -> float:
        if self.index_price <= 0 or self.mid_price <= 0:
            return 0.0
        return (self.mid_price - self.index_price) / self.index_price * 10000.0


class CoinbaseDerivativesGateway:
    """Read-only futures curve and order-book adapter on Coinbase Advanced."""

    PRODUCTS_PATH = CoinbaseAdvancedMarketData.PRODUCTS_PATH
    UNDERLYING_PREFIXES = {
        "BTC": ("BIT-", "BTC-"),
        "ETH": ("ET-", "ETH-"),
        "SOL": ("SOL-",),
        "XRP": ("XRP-",),
    }
    SPOT_PRODUCTS = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD",
        "SOL": "SOL-USD",
        "XRP": "XRP-USD",
    }

    def __init__(
        self,
        *,
        timeout: float = 5.0,
        client: CoinbaseAdvancedMarketData | None = None,
    ) -> None:
        self.client = client or CoinbaseAdvancedMarketData(timeout=timeout)

    @staticmethod
    def _number(raw: Any, default: float = 0.0) -> float:
        try:
            return float(raw if raw is not None else default)
        except (TypeError, ValueError):
            return default

    def list_futures(self, *, page_size: int = 250, max_pages: int = 10) -> list[dict[str, Any]]:
        page_size = max(1, min(250, int(page_size)))
        max_pages = max(1, min(50, int(max_pages)))
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {
                "limit": str(page_size),
                "product_type": "FUTURE",
            }
            if cursor:
                params["cursor"] = cursor
            try:
                payload = self.client._get(self.PRODUCTS_PATH, params)
            except CoinbaseMarketDataError as exc:
                raise CoinbaseDerivativesError(
                    "Coinbase futures market-data request failed",
                    category="market_data_unavailable",
                ) from exc
            page = payload.get("products") if isinstance(payload, dict) else None
            if not isinstance(page, list):
                raise CoinbaseDerivativesError(
                    "Unexpected Coinbase futures products response",
                    category="unexpected_response",
                )
            for row in page:
                if not isinstance(row, dict):
                    continue
                product_id = str(row.get("product_id") or "").upper().strip()
                if not product_id or product_id in seen:
                    continue
                seen.add(product_id)
                rows.append(dict(row))
            has_next = bool(payload.get("has_next")) if isinstance(payload, dict) else False
            next_cursor = str(payload.get("cursor") or "") if isinstance(payload, dict) else ""
            if not has_next or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return rows

    @classmethod
    def _underlying(cls, product_id: str) -> str | None:
        product_id = str(product_id).upper().strip()
        for underlying, prefixes in cls.UNDERLYING_PREFIXES.items():
            if any(product_id.startswith(prefix) for prefix in prefixes):
                return underlying
        return None

    @staticmethod
    def _expiry_timestamp(row: dict[str, Any]) -> float:
        details = row.get("future_product_details")
        if not isinstance(details, dict):
            return float("inf")
        raw = str(details.get("contract_expiry") or "").strip()
        if not raw:
            return float("inf")
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return float("inf")

    def nearest_crypto_futures(self) -> list[dict[str, Any]]:
        now = datetime.now(tz=timezone.utc).timestamp()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self.list_futures():
            product_id = str(row.get("product_id") or "").upper()
            underlying = self._underlying(product_id)
            if underlying is None:
                continue
            details = row.get("future_product_details")
            session = row.get("fcm_trading_session_details")
            if not isinstance(details, dict):
                continue
            expiry = self._expiry_timestamp(row)
            if expiry <= now:
                continue
            if isinstance(session, dict) and not bool(session.get("is_session_open", True)):
                continue
            grouped.setdefault(underlying, []).append(row)

        selected: list[dict[str, Any]] = []
        for underlying in sorted(grouped):
            candidates = grouped[underlying]
            candidates.sort(
                key=lambda row: (
                    self._expiry_timestamp(row),
                    -self._number(
                        (row.get("future_product_details") or {}).get("open_interest")
                        if isinstance(row.get("future_product_details"), dict) else 0.0
                    ),
                )
            )
            selected.append(dict(candidates[0]))
        return selected

    def ticker_from_product(self, row: dict[str, Any]) -> CoinbaseDerivativesTicker:
        product_id = str(row.get("product_id") or "").upper().strip()
        underlying = self._underlying(product_id)
        if not product_id or underlying is None:
            raise CoinbaseDerivativesError(
                "Unsupported crypto futures product",
                category="unsupported_product",
            )
        spot_product = self.SPOT_PRODUCTS[underlying]
        try:
            future_book = self.client.top_of_book(product_id)
            spot_book = self.client.top_of_book(spot_product)
        except CoinbaseMarketDataError as exc:
            raise CoinbaseDerivativesError(
                "Coinbase futures or spot order book unavailable",
                category="market_data_unavailable",
            ) from exc

        details = row.get("future_product_details")
        details = details if isinstance(details, dict) else {}
        session = row.get("fcm_trading_session_details")
        session = session if isinstance(session, dict) else {}
        intraday = details.get("intraday_margin_rate")
        intraday = intraday if isinstance(intraday, dict) else {}
        future_mid = float(future_book.mid_price)
        spot_mid = float(spot_book.mid_price)
        return CoinbaseDerivativesTicker(
            instrument_name=product_id,
            underlying=underlying,
            spot_product_id=spot_product,
            mark_price=future_mid,
            index_price=spot_mid,
            best_bid_price=float(future_book.bid_price),
            best_ask_price=float(future_book.ask_price),
            open_interest=self._number(details.get("open_interest")),
            price_change_pct=self._number(row.get("price_percentage_change_24h")),
            contract_size=self._number(details.get("contract_size")),
            long_margin_rate=self._number(intraday.get("long_margin_rate")),
            short_margin_rate=self._number(intraday.get("short_margin_rate")),
            contract_expiry=str(details.get("contract_expiry") or ""),
            session_open=bool(session.get("is_session_open", True)),
        )

    def auth_probe(self) -> dict[str, Any]:
        """Report execution boundary without attempting a derivative order."""
        return {
            "authenticated": False,
            "risk_profile_readable": False,
            "positions_readable": False,
            "error_category": "market_data_only_consumer_derivatives_route",
            "order_sent": False,
            "public_advanced_futures_data_available": True,
        }
