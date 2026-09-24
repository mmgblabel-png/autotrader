#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter


class NetworkCalled(RuntimeError):
    pass


def forbidden_network(*args, **kwargs):
    raise NetworkCalled("shadow validation must not call the network")


os.environ["BITPANDA_FUSION_DRY_RUN"] = "true"
os.environ["EXECUTION_MODE"] = "paper"
os.environ["BITPANDA_FUSION_LIVE_ORDERS_ENABLED"] = "false"

adapter = BitpandaFusionAdapter(api_key="shadow-placeholder", opener=forbidden_network)
result = adapter.place_limit_order(
    "BTC-EUR",
    "buy",
    amount=Decimal("10"),
    limit_price=Decimal("50000"),
    time_in_force="GTC",
)

assert result["status"] == "SHADOW"
assert result["live_orders_sent"] is False
assert result["would_place"] == {
    "pair": "BTC-EUR",
    "side": "Buy",
    "type": "Limit",
    "amount": "10",
    "limitPrice": "50000",
    "timeInForce": "GTC",
}
print(json.dumps(result, sort_keys=True))
