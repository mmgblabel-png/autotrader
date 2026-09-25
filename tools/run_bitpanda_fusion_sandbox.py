#!/usr/bin/env python3
"""Offline Bitpanda Fusion protocol simulator.

This exercises the adapter's gated create/get/cancel order flow with an
in-memory fake transport. It is not Bitpanda's venue sandbox and therefore
must never be used to mark the real venue Gate 2 as passed.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


orders: dict[str, dict[str, object]] = {}


def fake_opener(request, timeout=0):  # noqa: ANN001
    path = urlparse(request.full_url).path
    if request.method == "POST" and path == "/v1/account/orders":
        order = json.loads((request.data or b"{}").decode("utf-8"))
        order_id = "sandbox-order-1"
        stored = {"id": order_id, "status": "accepted", **order}
        orders[order_id] = stored
        return FakeResponse(stored)
    if request.method == "GET" and path.endswith("/v1/account/orders/sandbox-order-1"):
        return FakeResponse(orders["sandbox-order-1"])
    if request.method == "DELETE" and path.endswith("/v1/account/orders/sandbox-order-1"):
        orders["sandbox-order-1"]["status"] = "canceled"
        return FakeResponse(orders["sandbox-order-1"])
    raise AssertionError(f"unexpected simulated request: {request.method} {path}")


for name, value in {
    "BITPANDA_FUSION_DRY_RUN": "false",
    "EXECUTION_MODE": "live",
    "BITPANDA_FUSION_LIVE_ORDERS_ENABLED": "true",
    "LIVE_EXECUTION_APPROVED": "true",
    "LIVE_EXECUTION_ADAPTER_INSTALLED": "true",
    "LIVE_TRADING_CONFIRMATION": "I_UNDERSTAND_LIVE_ORDERS",
    "BITPANDA_FUSION_SELL_ONLY": "true",
    "EMERGENCY_STOP": "false",
}.items():
    os.environ[name] = value

adapter = BitpandaFusionAdapter(api_key="offline-placeholder", opener=fake_opener)
placed = adapter.place_limit_order("BTC-EUR", "sell", amount="10", limit_price="70000", time_in_force="GTC")
assert placed["id"] == "sandbox-order-1"
observed = adapter.get_order("sandbox-order-1")
assert observed["status"] == "accepted"
canceled = adapter.cancel_order("sandbox-order-1")
assert canceled["status"] == "canceled"

print(json.dumps({
    "status": "PASS",
    "simulation": True,
    "venue_sandbox": False,
    "network_calls": 0,
    "real_orders_sent": False,
    "flow": ["gated_sell_order", "get_order", "cancel_order"],
    "note": "Offline simulator only; does not satisfy Bitpanda venue Gate 2.",
}, indent=2))
