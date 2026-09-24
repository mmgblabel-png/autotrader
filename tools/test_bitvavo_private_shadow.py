#!/usr/bin/env python3
"""No-money Bitvavo private-path smoke test; never calls the order endpoint."""
from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal

os.environ["BITVAVO_DRY_RUN"] = "true"
os.environ["EXECUTION_MODE"] = "shadow"
os.environ["EMERGENCY_STOP"] = "true"

from autotrader.connectors.bitvavo import BitvavoAdapter
from autotrader.core.order_journal import OrderJournal


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        journal = OrderJournal(os.path.join(directory, "orders.sqlite3"))
        adapter = BitvavoAdapter(api_key="DUMMY-KEY", api_secret="DUMMY-SECRET", journal=journal)
        adapter.ticker_price = lambda market: Decimal("50000")
        response = adapter.place_limit_order("BTC-EUR", "buy", Decimal("0.0001"), Decimal("50000"), "shadow-private-test-001")
        report = {
            "status": response.get("status"),
            "live_orders_sent": False,
            "private_order_endpoint_called": False,
            "journal_status": journal.get("shadow-private-test-001")["status"],
            "journal_counts": journal.counts(),
            "notional_eur": "5.0000",
        }
        print(json.dumps(report, indent=2))
        assert response["status"] == "SHADOW"
        assert report["journal_status"] == "shadow"
        assert report["live_orders_sent"] is False
        journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
