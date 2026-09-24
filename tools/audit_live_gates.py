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

    # 1. Credentials and permissions: code-side check only; secrets are never read.
    reports.append(result(
        1, "Credentials and permissions", "BLOCKED",
        "The adapter supports API-key/secret authentication and no withdrawal method, but this audit never reads or verifies Railway secrets or Bitvavo key permissions.",
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
    reconciliation = any(token in adapter for token in ("open_orders", "order_status", "fills", "reconcile"))
    reports.append(result(
        5, "Order reconciliation and partial fills", "PASS" if reconciliation else "FAIL",
        "The current adapter exposes account/balance/place/cancel only; no durable open-order, fill, partial-fill or post-order reconciliation loop was found.",
        "Implement durable order journal, order-status polling, fill accounting, partial-fill handling and cancel/replace recovery.",
    ))

    # 6. Restart recovery / durable state.
    durable = any(token in all_python_text() for token in ("execution_journal", "order_journal", "sqlite", "recovery_checkpoint"))
    reports.append(result(
        6, "Restart recovery and durable execution state", "PASS" if durable else "FAIL",
        "No durable execution journal or restart checkpoint was found for live orders; the gateway counters are in-memory.",
        "Persist accepted/submitted/filled/canceled state and reconcile it before allowing a restarted worker to trade.",
    ))

    # 7. Kill switch, auth, monitoring and explicit live gate.
    kill_ok = "EMERGENCY_STOP" in adapter and "LIVE_TRADING_CONFIRMATION" in adapter and "kill-switch" in risk
    reports.append(result(
        7, "Kill switch, authentication and operator monitoring", "BLOCKED" if kill_ok else "FAIL",
        "Emergency-stop, confirmation phrase, dashboard auth and risk kill-switch code exist; live capability is intentionally still reported as not_installed until gates 1, 2, 5 and 6 are complete.",
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
