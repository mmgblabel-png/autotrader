#!/usr/bin/env python3
"""Offline Gate 2 test: stop blocks, recovery only reaches a fake transport."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter  # noqa: E402


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"id":"fake-order","status":"accepted"}'


calls = []

def fake_opener(request, timeout=0):
    calls.append({"method": request.method, "path": request.full_url.split(".com", 1)[-1]})
    return FakeResponse()

for key, value in {
    "BITPANDA_FUSION_DRY_RUN": "false",
    "EXECUTION_MODE": "live",
    "BITPANDA_FUSION_LIVE_ORDERS_ENABLED": "true",
    "LIVE_EXECUTION_APPROVED": "true",
    "LIVE_EXECUTION_ADAPTER_INSTALLED": "true",
    "LIVE_TRADING_CONFIRMATION": "I_UNDERSTAND_LIVE_ORDERS",
    "BITPANDA_FUSION_SELL_ONLY": "true",
}.items():
    os.environ[key] = value

adapter = BitpandaFusionAdapter(api_key="placeholder", opener=fake_opener)
os.environ["EMERGENCY_STOP"] = "true"
blocked = adapter.place_market_order("BTC-EUR", "sell", amount="30")
assert blocked["status"] == "SHADOW"
assert not calls, "emergency stop must prevent transport calls"

os.environ["EMERGENCY_STOP"] = "false"
recovered = adapter.place_market_order("BTC-EUR", "sell", amount="30")
assert recovered["id"] == "fake-order"
assert len(calls) == 1

os.environ["EMERGENCY_STOP"] = "true"
blocked_again = adapter.place_market_order("BTC-EUR", "sell", amount="30")
assert blocked_again["status"] == "SHADOW"
assert len(calls) == 1, "re-enabled stop must prevent subsequent transport calls"

print(json.dumps({
    "gate": 2,
    "status": "PASS",
    "stop_blocked_before": True,
    "recovery_reached_fake_transport": True,
    "stop_blocked_after": True,
    "real_exchange_calls": 0,
    "fake_transport_calls": len(calls),
    "live_orders_sent": False,
}))
