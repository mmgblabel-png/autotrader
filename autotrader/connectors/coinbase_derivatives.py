"""Read-only Coinbase Derivatives Exchange (CDE) public REST connector.

The consumer Coinbase derivatives UI exposes CDE perpetual-style nano futures
(BIP/ETP/SLP/XPP). This connector consumes CDE public instrument and funding
data only. It intentionally contains no order-entry method.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class CoinbaseDerivativesError(RuntimeError):
    def __init__(self, message: str, *, category: str = "derivatives_request_failed") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class CoinbaseDerivativesTicker:
    instrument_name: str
    mark_price: float
    index_price: float
    fair_value_price: float
    funding_rate: float
    contract_size: float
    long_initial_margin_bps: float
    short_initial_margin_bps: float
    trading_state: str
    funding_interval_minutes: int
    is_perp: bool

    @property
    def basis_bps(self) -> float:
        if self.index_price <= 0:
            return 0.0
        return (self.mark_price - self.index_price) / self.index_price * 10000.0


class CoinbaseDerivativesGateway:
    """Minimal fail-closed client for CDE public REST research endpoints."""

    BASE_URL = "https://api.exchange.fairx.net"
    PERP_PRODUCT_CODES = ("BIP", "ETP", "SLP", "XPP")

    def __init__(self, *, timeout: float = 5.0) -> None:
        self.timeout = max(1.0, float(timeout))

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        method = method.upper().strip()
        url = self.BASE_URL + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "autotrader-cde-research/1.0",
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise CoinbaseDerivativesError(
                "Coinbase CDE public REST request failed",
                category=f"http_{int(exc.code)}",
            ) from exc
        except urllib.error.URLError as exc:
            raise CoinbaseDerivativesError(
                "Coinbase CDE public REST transport failed",
                category="transport_error",
            ) from exc
        except Exception as exc:
            raise CoinbaseDerivativesError(
                "Coinbase CDE public REST request failed",
                category=type(exc).__name__,
            ) from exc
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError as exc:
            raise CoinbaseDerivativesError(
                "Coinbase CDE public REST returned invalid JSON",
                category="unexpected_response",
            ) from exc

    def list_futures(
        self,
        *,
        product_codes: tuple[str, ...] | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        codes = [
            str(x).upper().strip()
            for x in (product_codes or self.PERP_PRODUCT_CODES)
            if str(x).strip()
        ]
        result = self._request(
            "POST",
            "/rest/instruments",
            payload={
                "product_codes": codes,
                "trading_states": ["OPEN"],
            },
        )
        if not isinstance(result, list):
            raise CoinbaseDerivativesError(
                "Unexpected CDE instruments response",
                category="unexpected_response",
            )
        return [dict(row) for row in result if isinstance(row, dict)]

    def funding_history(self, symbol: str) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            "/rest/funding-rate",
            params={"symbol": str(symbol).upper().strip()},
        )
        if not isinstance(result, list):
            raise CoinbaseDerivativesError(
                "Unexpected CDE funding-rate response",
                category="unexpected_response",
            )
        return [dict(row) for row in result if isinstance(row, dict)]

    @staticmethod
    def _number(raw: Any, default: float = 0.0) -> float:
        try:
            return float(raw if raw is not None else default)
        except (TypeError, ValueError):
            return default

    def ticker_from_instrument(self, instrument: dict[str, Any]) -> CoinbaseDerivativesTicker:
        symbol = str(instrument.get("symbol") or "").upper().strip()
        if not symbol:
            raise CoinbaseDerivativesError("CDE instrument has no symbol", category="unexpected_response")
        funding_rows = self.funding_history(symbol)
        latest = funding_rows[-1] if funding_rows else {}
        mark = self._number(latest.get("future_mark_price"))
        spot = self._number(latest.get("spot_mark_price"))
        fair = self._number(latest.get("fair_value_price"))
        if mark <= 0:
            mark = self._number(instrument.get("price_band_reference_price"))
        if spot <= 0:
            spot = fair or mark
        if fair <= 0:
            fair = spot or mark
        return CoinbaseDerivativesTicker(
            instrument_name=symbol,
            mark_price=mark,
            index_price=spot,
            fair_value_price=fair,
            funding_rate=self._number(latest.get("funding_rate")),
            contract_size=self._number(instrument.get("contract_size")),
            long_initial_margin_bps=self._number(instrument.get("long_initial_margin")),
            short_initial_margin_bps=self._number(instrument.get("short_initial_margin")),
            trading_state=str(instrument.get("trading_state") or ""),
            funding_interval_minutes=max(0, int(self._number(instrument.get("funding_interval_minutes")))),
            is_perp=bool(instrument.get("is_perp", False)),
        )

    def auth_probe(self) -> dict[str, Any]:
        """Explain the broker boundary without attempting order entry.

        Retail Coinbase UI/CFM access does not imply a direct CDE participant
        API credential. The existing CDP Advanced Trade key is intentionally
        not repurposed as a CDE HMAC/FIX key.
        """
        return {
            "authenticated": False,
            "risk_profile_readable": False,
            "positions_readable": False,
            "error_category": "consumer_broker_order_api_not_exposed_by_current_cdp_key",
            "order_sent": False,
            "public_cde_data_available": True,
        }
