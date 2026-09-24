#!/usr/bin/env python3
"""Audit live Bitvavo execution gates without placing an order.

Exit 0 only when every gate is PASS. BLOCKED/FAIL is deliberate fail-closed
behavior; this tool never changes environment variables or submits orders.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def result(gate: int, name: str, status: str, evidence: str, action: str = "") -> dict[str, Any]:
    return {"gate": gate, "name": name, "status": status, "evidence": evidence, "required_action": action}


def source_text(*paths: str) -> str:
    return "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)


def all_python_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "autotrader").rglob("*.py"))


def audit() -> list[dict[str, Any]]:
    adapter = source_text("autotrader/connectors/bitvavo.py")
    gateway = source_text("autotrader/core/execution_gateway.py")
    risk = source_text("autotrader/core/risk_manager.py")
    reports: list[dict[str, Any]] = []

    # 1. Credentials and permissions: secrets are never printed or copied.
    key_confirmed = bool(os.getenv("BITVAVO_API_KEY") and os.getenv("BITVAVO_API_SECRET"))
    rights_confirmed = os.getenv("BITVAVO_WITHDRAWALS_DISABLED", "false").lower() == "true" and os.getenv("BITVAVO_IP_WHITELIST_CONFIRMED", "false").lower() == "true"
    reports.append(result(
        1, "Credentials and permissions", "PASS" if key_confirmed and rights_confirmed else "BLOCKED",
        "The adapter has authenticated account/balance probes and explicit withdrawal/IP-whitelist confirmations; Bitvavo does not expose portable key-metadata, so trade permission still requires operator verification in Bitvavo.",
        "Verify the key has View + Trade digital assets, no withdrawals, and IP restriction; keep values only in Railway secrets.",
    ))

    # 2. Venue connectivity / controlled environment.
    has_public_ticker = "def ticker_price" in adapter and "https://api.bitvavo.com/v2" in adapter
    reports.append(result(
        2, "Connectivity and controlled test", "BLOCKED" if has_public_ticker else "FAIL",
        "Public ticker code exists, but Bitvavo has no configured testnet/sandbox path in this repository; no private order test was attempted.",
        "Add a venue-supported non-production test or keep shadow mode; do not use a real order as a first connectivity test.",
    ))

    # 3. Hard limits and slippage.
    limits_ok = all(token in gateway for token in ("MAX_TRADE_EUR", "MAX_DAILY_EXPOSURE_EUR", "MAX_DAILY_LOSS_EUR", "MAX_SLIPPAGE_BPS"))
    reports.append(result(
        3, "Hard trade, daily-loss and slippage limits", "PASS" if limits_ok else "FAIL",
        "ExecutionGateway validates per-order EUR notional, daily exposure, daily loss and slippage before any adapter call.",
    ))

    # 4. Idempotency and duplicate protection.
    idempotency_ok = "_seen_order_ids" in gateway and "duplicate client_order_id" in gateway
    reports.append(result(
        4, "Idempotency and duplicate-order protection", "PASS" if idempotency_ok else "FAIL",
        "ExecutionGateway rejects missing or duplicate client_order_id values.",
    ))

    # 5. Reconciliation / fills.
    reconciliation = all(token in adapter for token in ("open_orders", "get_order", "reconcile_order", "reconcile_inflight", "record_fill")) and "class OrderJournal" in all_python_text()
    reports.append(result(
        5, "Order reconciliation and partial fills", "PASS" if reconciliation else "FAIL",
        "Bitvavo adapter now provides get_order, ordersOpen, reconcile_order, reconcile_inflight and durable fill recording.",
        "",
    ))

    # 6. Restart recovery / durable state.
    durable = "class OrderJournal" in all_python_text() and "CREATE TABLE IF NOT EXISTS orders" in all_python_text() and "inflight" in adapter
    reports.append(result(
        6, "Restart recovery and durable execution state", "PASS" if durable else "FAIL",
        "SQLite WAL journal persists intent, submitted/status events and fills; inflight orders can be reconciled after restart.",
        "",
    ))

    # 7. Kill switch, auth, monitoring and explicit live gate.
    kill_ok = "EMERGENCY_STOP" in adapter and "LIVE_TRADING_CONFIRMATION" in adapter and "kill-switch" in risk
    reports.append(result(
        7, "Kill switch, authentication and operator monitoring", "BLOCKED" if kill_ok else "FAIL",
        "Emergency-stop, confirmation phrase, dashboard auth and risk kill-switch code exist; live capability remains blocked by gates 1 and 2 and the required operational review.",
        "Keep EMERGENCY_STOP=true until all preceding gates pass and perform an independent operational review.",
    ))
    return reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = {"mode": os.getenv("EXECUTION_MODE", "paper"), "live_orders_sent": False, "gates": audit()}
    passed = sum(item["status"] == "PASS" for item in report["gates"])
    report["passed"] = passed
    report["total"] = len(report["gates"])
    report["live_activation_allowed"] = passed == len(report["gates"])
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for item in report["gates"]:
            print(f"GATE {item['gate']}: {item['status']:<7} {item['name']} — {item['evidence']}")
        print(f"RESULT: {passed}/{len(report['gates'])} PASS; live_activation_allowed={report['live_activation_allowed']}")
    return 0 if report["live_activation_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
