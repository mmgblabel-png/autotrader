"""Safe Bitvavo REST adapter for EUR markets.

Bitvavo is used instead of Binance for users who can access Bitvavo in the
Netherlands. The adapter defaults to shadow/dry-run and never supports
withdrawals. API keys are read only from environment variables unless a
caller explicitly supplies short-lived credentials for local validation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

from autotrader.core.execution_gateway import ExecutionGateway, ExecutionRequest


class BitvavoError(RuntimeError):
    """Safe adapter error with a non-sensitive category for the UI."""

    def __init__(self, message: str, *, category: str = "bitvavo_error", status: int | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.status = status


class BitvavoAdapter:
    BASE_URL = "https://api.bitvavo.com/v2"

    def __init__(self, gateway: ExecutionGateway | None = None, *, timeout: float = 10.0, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("BITVAVO_API_KEY", "")).strip()
        self.api_secret = (api_secret if api_secret is not None else os.getenv("BITVAVO_API_SECRET", "")).strip()
        self.access_window = int(os.getenv("BITVAVO_ACCESS_WINDOW", "10000"))
        self.dry_run = os.getenv("BITVAVO_DRY_RUN", "true").lower() in {"1", "true", "yes"}
        self.timeout = timeout
        self.gateway = gateway or ExecutionGateway()

    def _private_request(self, method: str, endpoint: str, body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> Any:
        if not self.api_key or not self.api_secret:
            raise BitvavoError("BITVAVO_API_KEY and BITVAVO_API_SECRET are required")
        method = method.upper()
        body_text = "" if method == "GET" else json.dumps(body or {}, separators=(",", ":"))
        timestamp = str(int(time.time() * 1000))
        payload = f"{timestamp}{method}/v2{endpoint}{body_text}"
        signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {
            "Bitvavo-Access-Key": self.api_key,
            "Bitvavo-Access-Timestamp": timestamp,
            "Bitvavo-Access-Signature": signature,
            "Bitvavo-Access-Window": str(self.access_window),
            "Content-Type": "application/json",
        }
        url = self.BASE_URL + endpoint
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, data=body_text.encode() if body_text else None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            category = "invalid_credentials" if exc.code in {401, 403} else "bitvavo_http_error"
            raise BitvavoError(
                "Bitvavo private request was rejected",
                category=category,
                status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BitvavoError("Bitvavo private request could not reach the service", category="network_error") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BitvavoError("Bitvavo returned an invalid response", category="invalid_response") from exc
        except BitvavoError:
            raise
        except Exception as exc:
            raise BitvavoError("Bitvavo private request failed", category="bitvavo_error") from exc

    def ticker_price(self, market: str) -> Decimal:
        query = urllib.parse.urlencode({"market": market.upper()})
        try:
            with urllib.request.urlopen(f"{self.BASE_URL}/ticker/price?{query}", timeout=self.timeout) as response:
                payload = json.loads(response.read().decode())
            return Decimal(str(payload["price"]))
        except Exception as exc:
            raise BitvavoError(f"Bitvavo ticker failed: {exc}") from exc

    def account(self) -> dict[str, Any]:
        return self._private_request("GET", "/account")

    def balance(self, symbol: str | None = None) -> list[dict[str, Any]]:
        query = {"symbol": symbol.upper()} if symbol else None
        result = self._private_request("GET", "/balance", query=query)
        if not isinstance(result, list):
            raise BitvavoError("Unexpected Bitvavo balance response")
        return result

    def place_limit_order(self, market: str, side: str, amount: Decimal, price: Decimal, client_order_id: str, operator_id: int = 0) -> dict[str, Any]:
        return self._place(market, side, amount, price, client_order_id, operator_id, "limit")

    def place_market_order(self, market: str, side: str, amount: Decimal, client_order_id: str, operator_id: int = 0) -> dict[str, Any]:
        return self._place(market, side, amount, None, client_order_id, operator_id, "market")

    def _place(self, market: str, side: str, amount: Decimal, price: Decimal | None, client_order_id: str, operator_id: int, order_type: str) -> dict[str, Any]:
        side = side.lower()
        market = market.upper()
        observed = self.ticker_price(market)
        expected = price or observed
        notional_eur = amount * expected if side == "buy" else amount * observed
        decision = self.gateway.evaluate(ExecutionRequest("bitvavo", market, side.upper(), notional_eur, expected, observed, client_order_id, time.time()))
        proposal = {"venue": "bitvavo", "market": market, "side": side, "orderType": order_type, "amount": str(amount), "price": str(price) if price else None, "clientOrderId": client_order_id}
        if not decision.accepted:
            raise BitvavoError(decision.reason)
        if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
            return {"status": "SHADOW", "would_place": proposal}
        if os.getenv("LIVE_EXECUTION_APPROVED") != "true" or os.getenv("LIVE_EXECUTION_ADAPTER_INSTALLED") != "true" or os.getenv("EMERGENCY_STOP", "true") == "true" or os.getenv("LIVE_TRADING_CONFIRMATION") != "I_UNDERSTAND_LIVE_ORDERS":
            raise BitvavoError("Live gates are not satisfied; no order was sent")
        body: dict[str, Any] = {"market": market, "side": side, "orderType": order_type, "operatorId": operator_id, "clientOrderId": client_order_id, "amount": str(amount), "responseRequired": True}
        if order_type == "limit":
            body.update({"price": str(price), "timeInForce": "GTC"})
        return self._private_request("POST", "/order", body)

    def cancel_order(self, market: str, order_id: str) -> dict[str, Any]:
        if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
            return {"status": "SHADOW", "would_cancel": {"market": market, "orderId": order_id}}
        return self._private_request("DELETE", f"/order/{urllib.parse.quote(market.upper())}/{urllib.parse.quote(order_id)}")
