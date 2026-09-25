#!/usr/bin/env python3
"""Audit live-execution gates without placing an order.

The audit is fail-closed: it never changes environment variables and never
submits, cancels, or broadcasts an exchange order. Gate 1 supports Bitpanda
Fusion and requires both a successful read-only authentication probe and
explicit operator confirmations for the key scope and IP restriction.
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


def truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def audit() -> list[dict[str, Any]]:
    venue = os.getenv("EXCHANGE_VENUE", "bitvavo").strip().lower()
    gateway = source_text("autotrader/core/execution_gateway.py")
    risk = source_text("autotrader/core/risk_manager.py")
    adapter_path = "autotrader/connectors/bitpanda_fusion.py" if venue in {"bitpanda", "bitpanda_fusion"} else "autotrader/connectors/bitvavo.py"
    adapter = source_text(adapter_path)
    reports: list[dict[str, Any]] = []

    # Gate 1: credentials, successful read-only authentication, and scope/IP evidence.
    if venue in {"bitpanda", "bitpanda_fusion"}:
        key_present = bool(os.getenv("BITPANDA_FUSION_API_KEY", "").strip())
        auth_confirmed = truthy("BITPANDA_FUSION_AUTH_CONFIRMED")
        trade_confirmed = truthy("BITPANDA_FUSION_TRADE_PERMISSION_CONFIRMED")
        transfer_disabled = truthy("BITPANDA_FUSION_TRANSFER_DISABLED")
        ip_confirmed = truthy("BITPANDA_FUSION_IP_WHITELIST_CONFIRMED")
        gate1_pass = key_present and auth_confirmed and trade_confirmed and transfer_disabled and ip_confirmed
        reports.append(result(
            1,
            "Bitpanda Fusion credentials, permissions and IP restriction",
            "PASS" if gate1_pass else "BLOCKED",
            "Bitpanda Fusion read-only authentication, Read+Trade scope, Transfer disabled, and allowlisted IP confirmation are required; secrets are never printed.",
            "Set the four BITPANDA_FUSION_* confirmation flags only after checking the active Bitpanda key and successful Railway read-only probe." if not gate1_pass else "",
        ))
    else:
        key_confirmed = bool(os.getenv("BITVAVO_API_KEY") and os.getenv("BITVAVO_API_SECRET"))
        rights_confirmed = truthy("BITVAVO_WITHDRAWALS_DISABLED") and truthy("BITVAVO_IP_WHITELIST_CONFIRMED")
        reports.append(result(
            1,
            "Bitvavo credentials and permissions",
            "PASS" if key_confirmed and rights_confirmed else "BLOCKED",
            "Bitvavo account/balance authentication and explicit withdrawal/IP-whitelist confirmations are required; secrets are never printed.",
            "Verify the Bitvavo key has View + Trade, withdrawals disabled, and IP restriction." if not (key_confirmed and rights_confirmed) else "",
        ))

    # Gate 2 deliberately cannot be satisfied by a shadow simulation.
    if venue in {"bitpanda", "bitpanda_fusion"}:
        sandbox_confirmed = truthy("BITPANDA_FUSION_SANDBOX_CONFIRMED")
        reports.append(result(
            2,
            "Bitpanda Fusion connectivity and controlled test",
            "PASS" if sandbox_confirmed else "BLOCKED",
            "Read-only authentication and shadow order construction are not a venue-supported non-production order test.",
            "Use and document an official Bitpanda Fusion sandbox/test environment; do not replace this gate with a real order on the funded account." if not sandbox_confirmed else "",
        ))
    else:
        has_public_ticker = "def ticker_price" in adapter and "https://api.bitvavo.com/v2" in adapter
        reports.append(result(
            2,
            "Venue connectivity and controlled test",
            "BLOCKED" if has_public_ticker else "FAIL",
            "Public ticker and private shadow paths exist, but no funded live order is used as a first connectivity test.",
            "Add a venue-supported non-production test or keep shadow mode." if has_public_ticker else "Implement and test a public ticker path.",
        ))

    limits_ok = all(token in gateway for token in ("MAX_TRADE_EUR", "MAX_DAILY_EXPOSURE_EUR", "MAX_DAILY_LOSS_EUR", "MAX_SLIPPAGE_BPS"))
    reports.append(result(3, "Hard trade, daily-loss and slippage limits", "PASS" if limits_ok else "FAIL", "ExecutionGateway validates per-order EUR notional, daily exposure, daily loss and slippage before any adapter call."))

    idempotency_ok = "_seen_order_ids" in gateway and "duplicate client_order_id" in gateway
    reports.append(result(4, "Idempotency and duplicate-order protection", "PASS" if idempotency_ok else "FAIL", "ExecutionGateway rejects missing or duplicate client_order_id values."))

    reconciliation = all(token in adapter for token in ("open_orders", "get_order", "reconcile_order", "reconcile_inflight", "record_fill")) and "class OrderJournal" in all_python_text()
    reports.append(result(5, "Order reconciliation and partial fills", "PASS" if reconciliation else "FAIL", "The selected adapter provides order reconciliation and durable fill recording."))

    durable = "class OrderJournal" in all_python_text() and "CREATE TABLE IF NOT EXISTS orders" in all_python_text() and "inflight" in adapter
    reports.append(result(6, "Restart recovery and durable execution state", "PASS" if durable else "FAIL", "SQLite WAL journal persists intent, status events and fills; inflight orders can be reconciled after restart."))

    kill_ok = "EMERGENCY_STOP" in adapter or "EMERGENCY_STOP" in all_python_text()
    all_prior_pass = all(item["status"] == "PASS" for item in reports)
    operational_review = truthy("LIVE_OPERATIONAL_REVIEW_CONFIRMED")
    gate7_pass = kill_ok and all_prior_pass and operational_review
    reports.append(result(
        7,
        "Kill switch, authentication and operator monitoring",
        "PASS" if gate7_pass else "BLOCKED",
        "Emergency-stop, dashboard authentication, monitoring and an independent operational review are required after Gates 1–6 pass.",
        "Keep EMERGENCY_STOP=true; complete the independent operational review only after all preceding gates pass." if not gate7_pass else "",
    ))
    return reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = {"venue": os.getenv("EXCHANGE_VENUE", "bitvavo"), "mode": os.getenv("EXECUTION_MODE", "paper"), "live_orders_sent": False, "gates": audit()}
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
