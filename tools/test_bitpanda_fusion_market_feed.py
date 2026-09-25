#!/usr/bin/env python3
"""Read-only BTC-EUR market-feed probe; never places or cancels orders."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autotrader.core.market_feed import BitpandaFusionMarketFeed  # noqa: E402

result = BitpandaFusionMarketFeed(pair="BTC-EUR").fetch_once()
# Keep output safe for logs: price is status evidence, not an account secret.
print(json.dumps({
    "status": result.get("status"),
    "source": result.get("source"),
    "pair": result.get("pair"),
    "price_present": result.get("price") is not None,
    "stale": result.get("stale"),
    "orders_enabled": result.get("orders_enabled"),
    "error": result.get("error"),
}, sort_keys=True))
raise SystemExit(0 if result.get("status") == "live" else 1)
