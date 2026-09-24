from __future__ import annotations

import argparse
import json

from autotrader.connectors.bitvavo import BitvavoAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile durable inflight Bitvavo orders")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    adapter = BitvavoAdapter()
    try:
        results = adapter.reconcile_inflight()
        report = {"reconciled": len(results), "journal_counts": adapter.journal.counts(), "live_orders_sent": False}
        print(json.dumps(report, indent=2, default=str) if args.json else report)
        return 0
    finally:
        adapter.journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
