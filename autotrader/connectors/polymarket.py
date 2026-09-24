"""Polymarket adapter using the current official ``polymarket-client`` SDK.

All methods are dry-run unless the process is explicitly configured for live
execution and all risk gates pass. Never place a live order from a test shell.
"""
from __future__ import annotations

import os
import time
from decimal import Decimal
from typing import Any

from autotrader.core.execution_gateway import ExecutionGateway, ExecutionRequest


class PolymarketError(RuntimeError):
    pass


class PolymarketAdapter:
    def __init__(self, gateway: ExecutionGateway | None = None) -> None:
        self.gateway = gateway or ExecutionGateway()
        self.wallet = os.getenv("POLYMARKET_WALLET_ADDRESS", "").strip()
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "").strip()
        self.dry_run = os.getenv("POLYMARKET_DRY_RUN", "true").lower() in {"1", "true", "yes"}
        self._client = None

    async def _secure_client(self):
        if self._client is None:
            if not self.private_key or not self.wallet:
                raise PolymarketError("POLYMARKET_PRIVATE_KEY and POLYMARKET_WALLET_ADDRESS are required")
            try:
                from polymarket import AsyncSecureClient
            except ImportError as exc:
                raise PolymarketError("Install the official polymarket-client package before using live mode") from exc
            self._client = await AsyncSecureClient.create(private_key=self.private_key, wallet=self.wallet)
        return self._client

    async def place_market_order(self, token_id: str, side: str, amount_eur: Decimal, expected_price: Decimal, client_order_id: str) -> dict[str, Any]:
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise PolymarketError("side must be BUY or SELL")
        if not token_id or expected_price <= 0:
            raise PolymarketError("token_id and positive expected_price are required")
        decision = self.gateway.evaluate(ExecutionRequest("polymarket", token_id, side, amount_eur, expected_price, expected_price, client_order_id, time.time()))
        proposal = {"venue": "polymarket", "token_id": token_id, "side": side, "amount_eur": str(amount_eur), "expected_price": str(expected_price), "client_order_id": client_order_id}
        if not decision.accepted:
            raise PolymarketError(decision.reason)
        if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
            return {"status": "SHADOW", "would_place": proposal}
        if os.getenv("LIVE_EXECUTION_APPROVED") != "true" or os.getenv("LIVE_EXECUTION_ADAPTER_INSTALLED") != "true" or os.getenv("EMERGENCY_STOP", "true") == "true" or os.getenv("LIVE_TRADING_CONFIRMATION") != "I_UNDERSTAND_LIVE_ORDERS":
            raise PolymarketError("Live gates are not satisfied; no order was sent")
        client = await self._secure_client()
        try:
            response = await client.place_market_order(token_id=token_id, side=side, amount=str(amount_eur))
        except Exception as exc:
            raise PolymarketError(f"Polymarket order failed: {exc}") from exc
        if not getattr(response, "ok", False):
            raise PolymarketError(str(getattr(response, "message", "order rejected")))
        return {"status": "SUBMITTED", "order_id": getattr(response, "order_id", None), "raw": str(response)}
