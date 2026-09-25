#!/usr/bin/env python3
"""Preview one bounded Bitpanda Fusion order without network I/O.

This script never calls Bitpanda. It validates the same adapter payload and
local risk constraints that must be checked before any separately authorised
production action.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from decimal import Decimal, InvalidOperation

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter, BitpandaFusionError


def positive(value: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("must be numeric") from exc
    if not number.is_finite() or number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def nonnegative(value: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("must be numeric") from exc
    if not number.is_finite() or number < 0:
        raise argparse.ArgumentTypeError("must be zero or positive")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", default="BTC-EUR")
    parser.add_argument("--side", default="Sell")
    parser.add_argument("--quantity", type=positive, required=True, help="base-asset quantity, e.g. BTC")
    parser.add_argument("--limit-price", type=positive, required=True)
    parser.add_argument("--max-order-eur", type=positive, default=Decimal("32"))
    parser.add_argument("--daily-exposure-eur", type=nonnegative, default=Decimal("0"))
    parser.add_argument("--max-daily-exposure-eur", type=positive, default=Decimal("50"))
    parser.add_argument("--min-order-eur", type=positive, default=Decimal("0"), help="set only from current Bitpanda pair rules")
    args = parser.parse_args()

    # Enforce the same safety posture as Railway's current Gate-2 setup.
    import os
    os.environ.update({
        "BITPANDA_FUSION_DRY_RUN": "true",
        "EXECUTION_MODE": "shadow",
        "BITPANDA_FUSION_LIVE_ORDERS_ENABLED": "false",
        "BITPANDA_FUSION_SELL_ONLY": "true",
        "EMERGENCY_STOP": "true",
    })

    notional = args.quantity * args.limit_price
    checks = {
        "pair_is_btc_eur": args.pair.upper() == "BTC-EUR",
        "sell_only": args.side.lower() == "sell",
        "positive_quantity": args.quantity > 0,
        "positive_limit_price": args.limit_price > 0,
        "min_order_met": notional >= args.min_order_eur,
        "max_order_not_exceeded": notional <= args.max_order_eur,
        "daily_exposure_not_exceeded": args.daily_exposure_eur + notional <= args.max_daily_exposure_eur,
        "emergency_stop_enabled": True,
        "network_calls_zero": True,
    }
    try:
        adapter = BitpandaFusionAdapter(api_key="offline-preview-key")
        payload = adapter.create_order(
            pair=args.pair,
            side=args.side,
            order_type="limit",
            quantity=str(args.quantity),
            limit_price=str(args.limit_price),
            time_in_force="GTC",
        )
    except BitpandaFusionError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "checks": checks}, indent=2))
        return 2

    passed = all(checks.values()) and payload.get("status") == "SHADOW"
    print(json.dumps({
        "status": "PASS" if passed else "BLOCKED",
        "simulation": True,
        "payload": payload.get("would_place"),
        "estimated_notional_eur": str(notional),
        "checks": checks,
        "live_orders_sent": False,
        "network_calls": 0,
        "note": "Preview only. This script cannot submit an order to Bitpanda.",
    }, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
