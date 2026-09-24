from __future__ import annotations

import argparse
import json
import os

from autotrader.connectors.bitvavo import BitvavoAdapter
from autotrader.connectors.bitvavo import BitvavoError


def main() -> int:
    parser = argparse.ArgumentParser(description="Bitvavo emergency cancel/liquidation handler")
    parser.add_argument("--market", action="append", dest="markets", help="Allowlisted market, repeatable")
    args = parser.parse_args()
    if os.getenv("EMERGENCY_STOP", "true").lower() != "true":
        raise SystemExit("Refusing to run: EMERGENCY_STOP must be true")
    adapter = BitvavoAdapter()
    try:
        try:
            report = adapter.kill_switch_close_all(markets=args.markets)
        except BitvavoError as exc:
            print(json.dumps({"kill_switch": True, "status": "blocked_fail_closed", "live_orders_sent": False, "error": exc.category}, indent=2))
            return 2
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        adapter.journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
