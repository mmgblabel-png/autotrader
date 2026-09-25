"""Bitpanda Fusion REST adapter.

Fusion uses an ``x-api-key`` header. This adapter supports authenticated
read-only calls and deterministic shadow order validation. Live order sending
is fail-closed behind venue-specific and global execution gates.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)
_PAIR_RE = re.compile(r"^[A-Za-z0-9]{1,10}-[A-Za-z0-9]{1,10}$")
_ORDER_STATUSES = {
    "new", "filled", "filled-and-canceled", "partially-filled",
    "canceled", "done-for-day", "rejected",
}
_SAFE_ERROR_FIELDS = {
    "type", "title", "status", "detail", "instance", "error_code",
    "error_name", "error_category", "cloudflare_error", "retryable",
    "owner_action_required", "zone", "ray_id", "timestamp",
}


def _redacted_error_body(payload: Any) -> dict[str, Any] | None:
    """Keep only bounded, non-secret provider diagnostics."""
    if not isinstance(payload, dict):
        return None
    return {
        key: value for key, value in payload.items()
        if key.lower() in _SAFE_ERROR_FIELDS
    }


def _is_cloudflare_access_denied(payload: Any) -> bool:
    """Recognise Cloudflare 1010 without relying on a numeric JSON type."""
    if not isinstance(payload, dict):
        return False
    error_code = str(payload.get("error_code", "")).strip()
    error_name = str(payload.get("error_name", "")).strip().lower()
    cloudflare_flag = str(payload.get("cloudflare_error", "")).strip().lower()
    return error_code == "1010" or error_name == "browser_signature_banned" or cloudflare_flag == "true"


class BitpandaFusionError(RuntimeError):
    """Non-sensitive Fusion adapter error."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "bitpanda_fusion_error",
        status: int | None = None,
        response_code: str | int | None = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status = status
        self.response_code = response_code
        self.response_body = response_body


class BitpandaFusionAdapter:
    """Safe Fusion client with authenticated account and order support."""

    name = "bitpanda_fusion"
    BASE_URL = "https://api.fusion.bitpanda.com"
    BALANCES_PATH = "/v1/account/balances"
    TICKERS_PATH = "/v1/tickers"
    PAIRS_PATH = "/v1/pairs"
    ORDERS_PATH = "/v1/account/orders"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
        opener: Any = urllib.request.urlopen,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("BITPANDA_FUSION_API_KEY", "")).strip()
        self.base_url = (base_url or os.getenv("BITPANDA_FUSION_BASE_URL", self.BASE_URL)).rstrip("/")
        self.timeout = timeout
        self._opener = opener
        self.dry_run = os.getenv("BITPANDA_FUSION_DRY_RUN", "true").lower() in {"1", "true", "yes"}

    @property
    def credentials_present(self) -> bool:
        return bool(self.api_key)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Any:
        if not self.api_key:
            raise BitpandaFusionError("BITPANDA_FUSION_API_KEY is not configured", category="credentials_missing")
        method = method.upper()
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        body_text = json.dumps(body, separators=(",", ":")) if body is not None else ""
        user_agent = os.getenv("BITPANDA_FUSION_USER_AGENT", "AutoTrader/1.0 (+https://github.com/mmgblabel-png/autotrader)").strip()
        headers = {"Accept": "application/json", "User-Agent": user_agent, "x-api-key": self.api_key}
        if body_text:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=body_text.encode("utf-8") if body_text else None,
            method=method,
            headers=headers,
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            response_code: str | int | None = None
            response_body: Any = None
            payload: Any = None
            try:
                raw_body = exc.read().decode("utf-8", "replace")
                payload = json.loads(raw_body)
                if isinstance(payload, dict):
                    response_code = payload.get("code") or payload.get("error_code") or payload.get("error") or payload.get("message")
                    response_body = _redacted_error_body(payload)
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                pass
            if _is_cloudflare_access_denied(payload):
                category = "upstream_access_denied"
            else:
                category = "invalid_credentials" if exc.code in {401, 403} else "fusion_http_error"
            raise BitpandaFusionError(
                "Bitpanda Fusion request was rejected",
                category=category,
                status=exc.code,
                response_code=response_code,
                response_body=response_body,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BitpandaFusionError("Bitpanda Fusion request could not reach the service", category="network_error") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BitpandaFusionError("Bitpanda Fusion returned an invalid response", category="invalid_response") from exc

    def authenticate(self) -> dict[str, Any]:
        """Validate the key using Fusion's documented balances endpoint."""
        payload = self._request("GET", self.BALANCES_PATH)
        if not isinstance(payload, (dict, list)):
            raise BitpandaFusionError("Unexpected Fusion balances response", category="invalid_response")
        return {
            "venue": self.name,
            "credentials_present": True,
            "authenticated": True,
            "endpoint": self.BALANCES_PATH,
            "response_type": type(payload).__name__,
            "balance_entries": len(payload) if isinstance(payload, list) else None,
        }

    def balances(self) -> Any:
        return self._request("GET", self.BALANCES_PATH)

    def get_tickers(self, *, pair: str | None = None) -> Any:
        """Return current Fusion mid-price statistics; read-only."""
        query = {"pair": pair.upper()} if pair else None
        return self._request("GET", self.TICKERS_PATH, query=query)

    def get_pairs(self, *, pair: str | None = None) -> Any:
        """Return active Fusion pairs and their trading constraints; read-only."""
        query = {"pair": pair.upper()} if pair else None
        return self._request("GET", self.PAIRS_PATH, query=query)

    def list_orders(self, *, status: str | None = None, pair: str | None = None, limit: int = 100, cursor: str | None = None) -> Any:
        if not 1 <= limit <= 1000:
            raise BitpandaFusionError("Fusion order limit must be between 1 and 1000", category="invalid_request")
        query: dict[str, str] = {"limit": str(limit)}
        if status:
            status = status.lower()
            if status not in _ORDER_STATUSES and status not in {"open", "closed"}:
                raise BitpandaFusionError("Unsupported Fusion order status", category="invalid_request")
            query["status"] = status
        if pair:
            self._validate_pair(pair)
            query["pair"] = pair.upper()
        if cursor:
            query["cursor"] = cursor
        return self._request("GET", self.ORDERS_PATH, query=query)

    def get_order(self, order_id: str) -> Any:
        if not order_id or "/" in order_id:
            raise BitpandaFusionError("A valid Fusion order ID is required", category="invalid_request")
        return self._request("GET", f"{self.ORDERS_PATH}/{urllib.parse.quote(order_id, safe='')}")

    def open_orders(self, *, pair: str | None = None, limit: int = 100) -> Any:
        """Return open orders using Fusion's read-only order endpoint."""
        return self.list_orders(status="open", pair=pair, limit=limit)

    def ordersOpen(self, *, pair: str | None = None, limit: int = 100) -> Any:
        """Compatibility alias used by the execution reconciliation layer."""
        return self.open_orders(pair=pair, limit=limit)

    @staticmethod
    def record_fill(journal: Any, client_order_id: str, fill: dict[str, Any]) -> None:
        """Persist one fill through the durable OrderJournal interface."""
        journal.record_fill(client_order_id, fill)

    def reconcile_order(
        self,
        order_id: str,
        *,
        journal: Any | None = None,
        client_order_id: str | None = None,
    ) -> Any:
        """Fetch an order and optionally persist its status and fills."""
        order = self.get_order(order_id)
        if journal is None or not isinstance(order, dict):
            return order
        cid = client_order_id or str(order.get("clientOrderId") or order.get("client_order_id") or "")
        if not cid:
            return order
        status = str(order.get("status") or "unknown").lower()
        journal.update(cid, status, order, exchange_order_id=order_id)
        fills = order.get("fills") or order.get("trades") or []
        if isinstance(fills, list):
            for fill in fills:
                if isinstance(fill, dict):
                    self.record_fill(journal, cid, fill)
        return order

    def reconcile_inflight(self, journal: Any) -> list[Any]:
        """Reconcile journal rows that have an exchange order ID after restart."""
        results: list[Any] = []
        for row in journal.inflight():
            exchange_order_id = row.get("exchange_order_id")
            if not exchange_order_id:
                continue
            results.append(self.reconcile_order(
                str(exchange_order_id),
                journal=journal,
                client_order_id=str(row.get("client_order_id") or ""),
            ))
        return results

    def cancel_order(self, order_id: str) -> Any:
        if not order_id or "/" in order_id:
            raise BitpandaFusionError("A valid Fusion order ID is required", category="invalid_request")
        if not self._live_orders_enabled():
            return {"status": "SHADOW", "would_cancel": {"order_id": order_id}}
        return self._request("DELETE", f"{self.ORDERS_PATH}/{urllib.parse.quote(order_id, safe='')}")

    @staticmethod
    def _validate_pair(pair: str) -> str:
        normalized = pair.upper().strip()
        if not _PAIR_RE.fullmatch(normalized):
            raise BitpandaFusionError("Fusion pair must use the ASSET-QUOTE format", category="invalid_request")
        return normalized

    @staticmethod
    def _decimal(value: Any, field: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise BitpandaFusionError(f"Fusion {field} must be numeric", category="invalid_request") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise BitpandaFusionError(f"Fusion {field} must be positive", category="invalid_request")
        return parsed

    def shadow_validate_order(
        self,
        *,
        pair: str,
        side: str,
        order_type: str,
        quantity: Any = None,
        amount: Any = None,
        limit_price: Any = None,
        trigger_price: Any = None,
        time_in_force: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        """Validate and return the exact Fusion JSON order proposal without network I/O."""
        normalized_pair = self._validate_pair(pair)
        normalized_side = str(side).capitalize()
        normalized_type = str(order_type).replace("_", "").replace("-", "").lower()
        type_map = {"limit": "Limit", "market": "Market", "stoplimit": "StopLimit", "stopmarket": "StopMarket"}
        if normalized_side not in {"Buy", "Sell"} or normalized_type not in type_map:
            raise BitpandaFusionError("Unsupported Fusion order side or type", category="invalid_request")
        fusion_type = type_map[normalized_type]
        if (quantity is None) == (amount is None):
            raise BitpandaFusionError("Provide exactly one of quantity or amount", category="invalid_request")
        payload: dict[str, Any] = {"pair": normalized_pair, "side": normalized_side, "type": fusion_type}
        if quantity is not None:
            payload["quantity"] = str(self._decimal(quantity, "quantity"))
        if amount is not None:
            payload["amount"] = str(self._decimal(amount, "amount"))
        if fusion_type in {"Limit", "StopLimit"}:
            if limit_price is None:
                raise BitpandaFusionError("limitPrice is required for this order type", category="invalid_request")
            payload["limitPrice"] = str(self._decimal(limit_price, "limitPrice"))
        elif limit_price is not None:
            raise BitpandaFusionError("limitPrice is not valid for this order type", category="invalid_request")
        if fusion_type in {"StopLimit", "StopMarket"}:
            if trigger_price is None:
                raise BitpandaFusionError("triggerPrice is required for this order type", category="invalid_request")
            payload["triggerPrice"] = str(self._decimal(trigger_price, "triggerPrice"))
        elif trigger_price is not None:
            raise BitpandaFusionError("triggerPrice is not valid for this order type", category="invalid_request")
        if time_in_force:
            tif = time_in_force.upper()
            if tif not in {"GTC", "GTD", "IOC", "FOK"}:
                raise BitpandaFusionError("Unsupported Fusion timeInForce", category="invalid_request")
            if tif == "GTD" and not end_time:
                raise BitpandaFusionError("endTime is required for GTD orders", category="invalid_request")
            payload["timeInForce"] = tif
        if end_time:
            payload["endTime"] = end_time
        return payload

    def _live_orders_enabled(self) -> bool:
        return (
            not self.dry_run
            and os.getenv("EXECUTION_MODE", "paper") == "live"
            and os.getenv("BITPANDA_FUSION_LIVE_ORDERS_ENABLED", "false").lower() == "true"
            and os.getenv("LIVE_EXECUTION_APPROVED") == "true"
            and os.getenv("LIVE_EXECUTION_ADAPTER_INSTALLED") == "true"
            and os.getenv("LIVE_TRADING_CONFIRMATION") == "I_UNDERSTAND_LIVE_ORDERS"
            and os.getenv("EMERGENCY_STOP", "true").lower() != "true"
        )

    @staticmethod
    def _sell_only() -> bool:
        return os.getenv("BITPANDA_FUSION_SELL_ONLY", "false").lower() == "true"

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        """Validate an order, return shadow output by default, or submit only when all gates pass."""
        if self._sell_only() and str(kwargs.get("side", "")).lower() != "sell":
            return {"status": "BLOCKED", "reason": "sell_only_policy", "live_orders_sent": False}
        payload = self.shadow_validate_order(**kwargs)
        if not self._live_orders_enabled():
            return {"status": "SHADOW", "would_place": payload, "live_orders_sent": False}
        response = self._request("POST", self.ORDERS_PATH, body=payload)
        if not isinstance(response, dict):
            raise BitpandaFusionError("Unexpected Fusion create-order response", category="invalid_response")
        return response

    def place_limit_order(self, pair: str, side: str, *, quantity: Any = None, amount: Any = None, limit_price: Any = None, time_in_force: str | None = None, end_time: str | None = None) -> dict[str, Any]:
        return self.create_order(pair=pair, side=side, order_type="limit", quantity=quantity, amount=amount, limit_price=limit_price, time_in_force=time_in_force, end_time=end_time)

    def place_market_order(self, pair: str, side: str, *, quantity: Any = None, amount: Any = None, time_in_force: str | None = None) -> dict[str, Any]:
        return self.create_order(pair=pair, side=side, order_type="market", quantity=quantity, amount=amount, time_in_force=time_in_force)

    def redacted_status(self) -> dict[str, Any]:
        return {"venue": self.name, "credentials_present": self.credentials_present}


__all__ = ["BitpandaFusionAdapter", "BitpandaFusionError"]
