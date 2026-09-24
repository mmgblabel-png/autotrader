"""Fail-closed Bitvavo API-key and IP-whitelist validation.

Bitvavo does not expose a portable endpoint that returns the key's permission
set. Permission and whitelist checks therefore combine authenticated API
probes with explicit operator confirmations; no secret is ever printed.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError


def current_public_ip(timeout: float = 5.0) -> str:
    request = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "autotrader-security-check/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode().strip()


def validate_bitvavo_security(adapter: BitvavoAdapter, *, expected_ip: str | None = None) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "credentials_present": bool(adapter.api_key and adapter.api_secret),
        "authenticated_probe": False,
        "trade_permission": "unknown",
        "withdrawals_disabled": os.getenv("BITVAVO_WITHDRAWALS_DISABLED", "false").lower() == "true",
        "ip_whitelist_confirmed": os.getenv("BITVAVO_IP_WHITELIST_CONFIRMED", "false").lower() == "true",
        "current_public_ip": None,
        "expected_public_ip": expected_ip or os.getenv("BITVAVO_EXPECTED_PUBLIC_IP") or None,
        "errors": [],
    }
    if not checks["credentials_present"]:
        checks["errors"].append("credentials_missing")
    else:
        try:
            adapter.account()
            adapter.balance("EUR")
            checks["authenticated_probe"] = True
            checks["trade_permission"] = "not_verifiable_without_order_or_key-metadata_endpoint"
        except BitvavoError as exc:
            checks["errors"].append(exc.category)
            if exc.status in {401, 403}:
                checks["trade_permission"] = "rejected_or_not_authorized"
    if checks["expected_public_ip"]:
        try:
            checks["current_public_ip"] = current_public_ip()
            if checks["current_public_ip"] != checks["expected_public_ip"]:
                checks["errors"].append("public_ip_mismatch")
        except Exception:
            checks["errors"].append("public_ip_lookup_failed")
    checks["passed"] = bool(
        checks["credentials_present"]
        and checks["authenticated_probe"]
        and checks["withdrawals_disabled"]
        and checks["ip_whitelist_confirmed"]
        and (not checks["expected_public_ip"] or checks["current_public_ip"] == checks["expected_public_ip"])
        and not checks["errors"]
    )
    return checks


def main() -> int:
    report = validate_bitvavo_security(BitvavoAdapter())
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
