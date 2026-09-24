#!/usr/bin/env python3
"""Standalone Bitvavo private-account authentication probe.

Reads credentials only from BITVAVO_API_KEY and BITVAVO_API_SECRET.
Never prints credentials or the full signature.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request


def main() -> int:
    api_key = os.getenv("BITVAVO_API_KEY", "").strip()
    api_secret = os.getenv("BITVAVO_API_SECRET", "").strip()
    if not api_key or not api_secret:
        print(json.dumps({"passed": False, "error": "missing_credentials"}))
        return 2

    method = "GET"
    endpoint = "/account"
    body = ""  # Bitvavo requires an empty string for GET signing.
    timestamp = str(int(time.time() * 1000))
    payload = f"{timestamp}{method}/v2{endpoint}{body}"
    signature = hmac.new(
        api_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    request = urllib.request.Request(
        "https://api.bitvavo.com/v2/account",
        data=None,
        method=method,
        headers={
            "Bitvavo-Access-Key": api_key,
            "Bitvavo-Access-Timestamp": timestamp,
            "Bitvavo-Access-Signature": signature,
            "Bitvavo-Access-Window": "10000",
            "Content-Type": "application/json",
        },
    )

    result = {
        "request": {
            "method": method,
            "path": "/v2/account",
            "body_length": len(body.encode("utf-8")),
            "payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "signature_format": "64 lowercase hexadecimal characters",
        },
        "credentials": {
            "key_prefix": api_key[:4],
            "key_suffix": api_key[-4:],
            "key_length": len(api_key),
            "secret_length": len(api_secret),
            "secret_whitespace": sum(ch.isspace() for ch in api_secret),
        },
    }

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            result.update({"http_status": response.status, "authenticated": True, "response_keys": sorted(parsed) if isinstance(parsed, dict) else []})
            print(json.dumps(result, indent=2))
            return 0
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        result.update({
            "http_status": exc.code,
            "authenticated": False,
            "bitvavo_error_code": parsed.get("errorCode"),
            "bitvavo_error": parsed.get("error"),
        })
        print(json.dumps(result, indent=2))
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        result.update({"authenticated": False, "network_error": type(exc).__name__})
        print(json.dumps(result, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
