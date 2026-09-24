"""Safe Binance Spot REST adapter.

Defaults to Spot Testnet and dry-run. Live orders require all independent
server-side gates and an exact confirmation phrase. Secrets are environment
variables only; withdrawals are never supported.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

from autotrader.core.execution_gateway import ExecutionGateway, ExecutionRequest


class BinanceSpotError(RuntimeError):
    pass


class BinanceSpotAdapter:
    TESTNET_URL = "https://testnet.binance.vision"
    LIVE_URL = "https://api.binance.com"

    def __init__(self, gateway: ExecutionGateway | None = None, *, timeout: float = 10.0) -> None:
        self.api_key = os.getenv("BINANCE_API_KEY", "").strip()
        self.api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
        self.base_url = self.TESTNET_URL if os.getenv("BINANCE_USE_TESTNET", "true").lower() in {"1", "true", "yes"} else self.LIVE_URL
        self.dry_run = os.getenv("BINANCE_DRY_RUN", "true").lower() in {"1", "true", "yes"}
        self.timeout = timeout
        self.gateway = gateway or ExecutionGateway()

    def _assert_credentials(self) -> None:
        if not self.api_key or not self.api_secret:
            raise BinanceSpotError("BINANCE_API_KEY and BINANCE_API_SECRET are required")

    def _signed_request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self._assert_credentials()
        params = {k: v for k, v in params.items() if v is not None}
        params.setdefault("timestamp", int(time.time() * 1000))
        params.setdefault("recvWindow", 5000)
        query = urllib.parse.urlencode(params)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base_url}{path}?{query}&signature={signature}"
        request = urllib.request.Request(url, method=method.upper(), headers={"X-MBX-APIKEY": self.api_key})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except Exception as exc:
            raise BinanceSpotError(f"Binance request failed: {exc}") from exc

    def ticker_price(self, symbol: str) -> Decimal:
        url = f"{self.base_url}/api/v3/ticker/price?{urllib.parse.urlencode({'symbol': symbol.upper()})}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode())
            return Decimal(str(payload["price"]))
        except Exception as exc:
            raise BinanceSpotError(f"Binance ticker failed: {exc}") from exc

    def account(self) -> dict[str, Any]:
        return self._signed_request("GET", "/api/v3/account", {})

    def place_limit_order(self, symbol: str, side: str, quantity: Decimal, price: Decimal, client_order_id: str) -> dict[str, Any]:
        return self._place(symbol, side, quantity, price, client_order_id, order_type="LIMIT")

    def place_market_order(self, symbol: str, side: str, quantity: Decimal, client_order_id: str) -> dict[str, Any]:
        return self._place(symbol, side, quantity, None, client_order_id, order_type="MARKET")

    def _place(self, symbol: str, side: str, quantity: Decimal, price: Decimal | None, client_order_id: str, *, order_type: str) -> dict[str, Any]:
        side = side.upper()
        observed = self.ticker_price(symbol)
        expected = price or observed
        decision = self.gateway.evaluate(ExecutionRequest("binance_spot", symbol.upper(), side, quantity * expected / Decimal(os.getenv("USD_EUR_RATE", "0.92")), expected, observed, client_order_id, time.time()))
        proposal = {"venue": "binance_spot", "symbol": symbol.upper(), "side": side, "type": order_type, "quantity": str(quantity), "price": str(price) if price else None, "clientOrderId": client_order_id, "decision": decision.reason}
        if not decision.accepted:
            raise BinanceSpotError(decision.reason)
        if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
            return {"status": "SHADOW", "would_place": proposal}
        if os.getenv("LIVE_EXECUTION_APPROVED") != "true" or os.getenv("LIVE_EXECUTION_ADAPTER_INSTALLED") != "true" or os.getenv("EMERGENCY_STOP", "true") == "true" or os.getenv("LIVE_TRADING_CONFIRMATION") != "I_UNDERSTAND_LIVE_ORDERS":
            raise BinanceSpotError("Live gates are not satisfied; no order was sent")
        params: dict[str, Any] = {"symbol": symbol.upper(), "side": side, "type": order_type, "quantity": str(quantity), "newClientOrderId": client_order_id}
        if order_type == "LIMIT":
            params.update({"timeInForce": "GTC", "price": str(price)})
        return self._signed_request("POST", "/api/v3/order", params)

    def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        if os.getenv("EXECUTION_MODE", "paper") != "live" or self.dry_run:
            return {"status": "SHADOW", "would_cancel": {"symbol": symbol, "orderId": order_id}}
        return self._signed_request("DELETE", "/api/v3/order", {"symbol": symbol.upper(), "orderId": order_id})
