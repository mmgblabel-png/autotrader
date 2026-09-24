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
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

from autotrader.core.execution_gateway import ExecutionGateway, ExecutionRequest
from autotrader.core.order_journal import OrderJournal

LOGGER = logging.getLogger(__name__)


class BitvavoError(RuntimeError):
    """Safe adapter error with a non-sensitive category for the UI."""

    def __init__(self, message: str, *, category: str = "bitvavo_error", status: int | None = None, error_code: int | None = None, error_message: str | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.status = status
        self.error_code = error_code
        self.error_message = error_message


class BitvavoAdapter:
    BASE_URL = "https://api.bitvavo.com/v2"

    def __init__(self, gateway: ExecutionGateway | None = None, *, timeout: float = 10.0, api_key: str | None = None, api_secret: str | None = None, journal: OrderJournal | None = None) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("BITVAVO_API_KEY", "")).strip()
        self.api_secret = (api_secret if api_secret is not None else os.getenv("BITVAVO_API_SECRET", "")).strip()
        self.access_window = int(os.getenv("BITVAVO_ACCESS_WINDOW", "10000"))
        self.dry_run = os.getenv("BITVAVO_DRY_RUN", "true").lower() in {"1", "true", "yes"}
        self.timeout = timeout
        self.gateway = gateway or ExecutionGateway()
        self.journal = journal or OrderJournal()

    def _private_request(self, method: str, endpoint: str, body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> Any:
        if not self.api_key or not self.api_secret:
            raise BitvavoError("BITVAVO_API_KEY and BITVAVO_API_SECRET are required")
        method = method.upper()
        body_text = "" if method == "GET" else json.dumps(body or {}, separators=(",", ":"))
        timestamp = str(int(time.time() * 1000))
        payload = f"{timestamp}{method}/v2{endpoint}{body_text}"
        signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if os.getenv("BITVAVO_DEBUG_SIGNING", "false").lower() in {"1", "true", "yes"}:
            LOGGER.warning(
                "Bitvavo signing debug method=%s path=/v2%s timestamp=%s body_len=%d "
                "payload_sha256=%s signature_prefix=%s signature_suffix=%s",
                method,
                endpoint,
                timestamp,
                len(body_text.encode("utf-8")),
                hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                signature[:4],
                signature[-4:],
            )
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
            error_code = None
            error_message = None
            try:
                payload = json.loads(exc.read().decode())
                raw_code = payload.get("errorCode")
                error_code = int(raw_code) if raw_code is not None else None
                raw_message = payload.get("error")
                error_message = str(raw_message) if raw_message is not None else None
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                pass
            category = "invalid_credentials" if exc.code in {401, 403} else "bitvavo_http_error"
            raise BitvavoError(
                "Bitvavo private request was rejected",
                category=category,
                status=exc.code,
                error_code=error_code,
                error_message=error_message,
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

    def get_order(self, market: str, *, order_id: str | None = None, client_order_id: str | None = None) -> dict[str, Any]:
        if not order_id and not client_order_id:
            raise BitvavoError("order_id or client_order_id is required")
        query = {"orderId": order_id} if order_id else {"clientOrderId": client_order_id}
        return self._private_request("GET", f"/order/{urllib.parse.quote(market.upper())}", query=query)

    def open_orders(self, market: str | None = None) -> list[dict[str, Any]]:
        query = {"market": market.upper()} if market else None
        result = self._private_request("GET", "/ordersOpen", query=query)
        if not isinstance(result, list):
            raise BitvavoError("Unexpected Bitvavo open-orders response")
        return result

    def reconcile_order(self, client_order_id: str, market: str) -> dict[str, Any]:
        """Fetch exchange state and persist status/fills; safe to repeat after restart."""
        record = self.journal.get(client_order_id)
        if not record:
            raise BitvavoError("order is not present in the local journal")
        payload = self.get_order(market, order_id=record.get("exchange_order_id"), client_order_id=client_order_id)
        status = str(payload.get("status") or "unknown").lower()
        exchange_id = str(payload.get("orderId") or record.get("exchange_order_id") or "") or None
        self.journal.update(client_order_id, status, payload, exchange_order_id=exchange_id)
        for fill in payload.get("fills") or []:
            if isinstance(fill, dict):
                self.journal.record_fill(client_order_id, fill)
        return payload

    def reconcile_inflight(self) -> list[dict[str, Any]]:
        results = []
        for record in self.journal.inflight():
            try:
                results.append(self.reconcile_order(record["client_order_id"], record["market"]))
            except BitvavoError as exc:
                self.journal.update(record["client_order_id"], "error", {"category": exc.category}, error=exc.category)
        return results

    def kill_switch_close_all(self, *, markets: list[str] | None = None) -> dict[str, Any]:
        """Cancel open orders and optionally flatten allowlisted balances.

        This is deliberately dry-run unless all kill-switch liquidation gates
        are explicitly enabled. It never handles withdrawals.
        """
        open_orders = self.open_orders()
        report: dict[str, Any] = {"kill_switch": True, "orders_canceled": [], "positions_closed": [], "live_orders_sent": False}
        allowed_markets = {m.upper() for m in (markets or os.getenv("BITVAVO_KILL_SWITCH_MARKETS", "BTC-EUR").split(",")) if m.strip()}
        for order in open_orders:
            market = str(order.get("market") or "").upper()
            order_id = str(order.get("orderId") or "")
            client_id = str(order.get("clientOrderId") or "")
            if not market or not order_id:
                continue
            if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
                report["orders_canceled"].append({"market": market, "orderId": order_id, "status": "SHADOW"})
                if client_id and self.journal.get(client_id):
                    self.journal.update(client_id, "cancelled", {"reason": "kill_switch_shadow", "orderId": order_id})
                continue
            response = self._private_request("DELETE", f"/order/{urllib.parse.quote(market)}/{urllib.parse.quote(order_id)}")
            report["orders_canceled"].append({"market": market, "orderId": order_id, "status": "canceled", "response": response})
            if client_id and self.journal.get(client_id):
                self.journal.update(client_id, "canceled", response, exchange_order_id=order_id)
            report["live_orders_sent"] = True

        gates = (
            os.getenv("KILL_SWITCH_CLOSE_POSITIONS", "false").lower() == "true"
            and os.getenv("LIVE_EXECUTION_APPROVED") == "true"
            and os.getenv("LIVE_EXECUTION_ADAPTER_INSTALLED") == "true"
            and os.getenv("LIVE_TRADING_CONFIRMATION") == "I_UNDERSTAND_LIVE_ORDERS"
            and os.getenv("EMERGENCY_STOP", "true").lower() == "true"
        )
        if not gates:
            report["position_close_status"] = "blocked_fail_closed"
            return report

        balances = self.balance()
        max_eur = Decimal(os.getenv("KILL_SWITCH_MAX_LIQUIDATION_EUR", "50"))
        for market in sorted(allowed_markets):
            base = market.split("-", 1)[0]
            entry = next((item for item in balances if str(item.get("symbol", "")).upper() == base), None)
            available = Decimal(str((entry or {}).get("available", "0")))
            if available <= 0:
                continue
            price = self.ticker_price(market)
            amount = min(available, max_eur / price)
            if amount <= 0:
                continue
            client_id = f"kill-{int(time.time())}-{base.lower()}"
            body = {"market": market, "side": "sell", "orderType": "market", "amount": str(amount), "clientOrderId": client_id, "responseRequired": True}
            self.journal.record_intent(client_order_id=client_id, market=market, side="sell", order_type="market", amount=str(amount), price=None)
            response = self._private_request("POST", "/order", body)
            self.journal.update(client_id, str(response.get("status") or "submitted").lower(), response, exchange_order_id=str(response.get("orderId") or "") or None)
            report["positions_closed"].append({"market": market, "amount": str(amount), "response": response})
            report["live_orders_sent"] = True
        report["position_close_status"] = "completed"
        return report

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
        new_intent = self.journal.record_intent(client_order_id=client_order_id, market=market, side=side, order_type=order_type, amount=str(amount), price=str(price) if price else None)
        if not decision.accepted:
            if new_intent:
                self.journal.update(client_order_id, "rejected", {"reason": decision.reason}, error=decision.reason)
            raise BitvavoError(decision.reason)
        if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
            self.journal.update(client_order_id, "shadow", proposal)
            return {"status": "SHADOW", "would_place": proposal}
        if os.getenv("LIVE_EXECUTION_APPROVED") != "true" or os.getenv("LIVE_EXECUTION_ADAPTER_INSTALLED") != "true" or os.getenv("EMERGENCY_STOP", "true") == "true" or os.getenv("LIVE_TRADING_CONFIRMATION") != "I_UNDERSTAND_LIVE_ORDERS":
            self.journal.update(client_order_id, "blocked", proposal, error="live_gates_not_satisfied")
            raise BitvavoError("Live gates are not satisfied; no order was sent")
        body: dict[str, Any] = {"market": market, "side": side, "orderType": order_type, "operatorId": operator_id, "clientOrderId": client_order_id, "amount": str(amount), "responseRequired": True}
        if order_type == "limit":
            body.update({"price": str(price), "timeInForce": "GTC"})
        try:
            response = self._private_request("POST", "/order", body)
            self.journal.update(client_order_id, str(response.get("status") or "submitted").lower(), response, exchange_order_id=str(response.get("orderId") or "") or None)
            return response
        except BitvavoError as exc:
            self.journal.update(client_order_id, "error", {"category": exc.category}, error=exc.category)
            raise

    def cancel_order(self, market: str, order_id: str) -> dict[str, Any]:
        if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
            return {"status": "SHADOW", "would_cancel": {"market": market, "orderId": order_id}}
        response = self._private_request("DELETE", f"/order/{urllib.parse.quote(market.upper())}/{urllib.parse.quote(order_id)}")
        for record in self.journal.inflight():
            if record.get("exchange_order_id") == order_id:
                self.journal.update(record["client_order_id"], "canceled", response, exchange_order_id=order_id)
        return response
