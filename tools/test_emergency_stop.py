#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from decimal import Decimal

os.environ["EXECUTION_MODE"] = "live"
os.environ["BITVAVO_DRY_RUN"] = "false"
os.environ["EMERGENCY_STOP"] = "true"
os.environ["LIVE_EXECUTION_APPROVED"] = "true"
os.environ["LIVE_EXECUTION_ADAPTER_INSTALLED"] = "true"
os.environ["LIVE_TRADING_CONFIRMATION"] = "I_UNDERSTAND_LIVE_ORDERS"
os.environ["ORDER_JOURNAL_PATH"] = os.path.join(tempfile.mkdtemp(), "orders.sqlite3")

from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError

adapter = BitvavoAdapter(api_key="DUMMY-KEY", api_secret="DUMMY-SECRET")
adapter.ticker_price = lambda market: Decimal("50000")
try:
    adapter.place_limit_order("BTC-EUR", "buy", Decimal("0.0001"), Decimal("50000"), "emergency-stop-test-001")
except BitvavoError as exc:
    reason = str(exc).lower()
    assert any(token in reason for token in ("gates", "emergency", "not installed", "no order was sent"))
    print("KILL_SWITCH=PASS")
    print("ORDER_SENT=FALSE")
    print("REASON=" + str(exc))
else:
    raise SystemExit("FAIL: emergency stop did not block order")
