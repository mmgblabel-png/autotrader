#!/usr/bin/env python3
"""Verify the Bitpanda Fusion Read scope with a redacted balance probe.

The script only calls GET /v1/account/balances. It never places, cancels,
or lists orders and never prints the API key or balance amounts.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

DEFAULT_BASE_URL = "https://api.fusion.bitpanda.com"
BALANCES_PATH = "/v1/account/balances"


def redacted_body(raw: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    safe_fields = {
        "type", "title", "status", "detail", "instance", "code",
        "error", "error_code", "error_name", "error_category",
        "cloudflare_error", "retryable", "owner_action_required",
        "zone", "ray_id", "timestamp",
    }
    return {k: v for k, v in payload.items() if k.lower() in safe_fields}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Fusion Read scope without exposing balances")
    parser.add_argument("--base-url", default=os.getenv("BITPANDA_FUSION_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    key = os.getenv("BITPANDA_FUSION_API_KEY", "").strip()
    result: dict[str, object] = {
        "endpoint": BALANCES_PATH,
        "credentials_present": bool(key),
        "scope_test": "Read",
        "orders_attempted": False,
    }
    if not key:
        result.update({"authenticated": False, "scope_verified": False, "category": "credentials_missing"})
        print(json.dumps(result, sort_keys=True))
        return 2

    url = args.base_url.rstrip("/") + BALANCES_PATH
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": os.getenv(
                "BITPANDA_FUSION_USER_AGENT",
                "AutoTrader/1.0 (+https://github.com/mmgblabel-png/autotrader)",
            ),
            "x-api-key": key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            raw = response.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        result.update({
            "authenticated": True,
            "scope_verified": True,
            "http_status": 200,
            "response_type": type(payload).__name__,
            "balance_entries": len(payload) if isinstance(payload, list) else None,
        })
        print(json.dumps(result, sort_keys=True))
        return 0
    except urllib.error.HTTPError as exc:
        body = redacted_body(exc.read().decode("utf-8", "replace"))
        is_cloudflare = isinstance(body, dict) and (
            str(body.get("error_code")) == "1010"
            or str(body.get("error_name", "")).lower() == "browser_signature_banned"
            or str(body.get("cloudflare_error", "")).lower() == "true"
        )
        result.update({
            "authenticated": False,
            "scope_verified": False,
            "http_status": exc.code,
            "category": "upstream_access_denied" if is_cloudflare else ("invalid_credentials" if exc.code in {401, 403} else "fusion_http_error"),
            "response_body": body,
        })
        print(json.dumps(result, sort_keys=True))
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result.update({
            "authenticated": False,
            "scope_verified": False,
            "category": "network_error",
            "error_type": type(exc).__name__,
        })
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
