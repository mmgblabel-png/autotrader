#!/usr/bin/env python3
"""Run bounded synthetic BTC-EUR ticks through all agents in shadow mode.

No exchange connector, credentials, network or live-order path is used.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from autotrader.agent import AutoTrader


os.environ.update({
    "EXCHANGE_VENUE": "bitpanda",
    "EXECUTION_MODE": "shadow",
    "BITPANDA_FUSION_DRY_RUN": "true",
    "BITPANDA_FUSION_LIVE_ORDERS_ENABLED": "false",
    "BITPANDA_FUSION_SELL_ONLY": "true",
    "EMERGENCY_STOP": "true",
})

prices = [70000.0, 70125.0, 69875.0, 70400.0, 69600.0, 70050.0]
max_order_eur = 32.0
agent = AutoTrader("config.yaml")
started = agent.start()
errors: list[str] = []
processed = 0
for price in prices:
    try:
        agent.shadow_tick(pair="BTC-EUR", price=price)
        processed += 1
    except Exception as exc:  # report the agent name-independent failure safely
        errors.append(type(exc).__name__ + ": " + str(exc))
stopped = agent.stop()
status = agent.status()
orders = list(getattr(agent, "_om")._orders.values())
oversized_orders = [
    {
        "strategy": order.strategy,
        "side": order.side.value,
        "quantity": order.quantity,
        "price": order.price,
        "notional_eur": round(order.quantity * (order.price or 0.0), 8),
    }
    for order in orders
    if order.quantity * (order.price or 0.0) > max_order_eur
]

result = {
    "status": "PASS" if processed == len(prices) and not errors and not oversized_orders else "BLOCKED",
    "mode": "shadow",
    "pair": "BTC-EUR",
    "ticks_requested": len(prices),
    "ticks_processed": processed,
    "strategies_started": started,
    "strategies_stopped": stopped,
    "strategy_running_after_stop": status["strategies"],
    "paper_orders_or_intents": len(orders),
    "max_order_eur": max_order_eur,
    "oversized_order_intents": oversized_orders,
    "errors": errors,
    "network_calls": 0,
    "live_orders_sent": False,
    "note": "Synthetic local ticks only; this does not prove Bitpanda Gate 2.",
}
print(json.dumps(result, indent=2, default=str))
raise SystemExit(0 if result["status"] == "PASS" else 1)
