#!/usr/bin/env python3
"""Offline regression probe for Bitpanda/Cloudflare Error 1010 handling."""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from autotrader.connectors.bitpanda_fusion import (  # noqa: E402
    _is_cloudflare_access_denied,
    _redacted_error_body,
)

payload = {
    "type": "https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/",
    "title": "Error 1010: Access denied",
    "status": 403,
    "detail": "The site owner has blocked access based on your browser's signature.",
    "error_code": "1010",
    "error_name": "browser_signature_banned",
    "error_category": "access_denied",
    "cloudflare_error": True,
    "retryable": False,
    "owner_action_required": True,
    "api_key": "THIS_MUST_NOT_APPEAR",
    "secret": "THIS_MUST_NOT_APPEAR",
}

assert _is_cloudflare_access_denied(payload) is True
redacted = _redacted_error_body(payload)
assert redacted is not None
assert redacted["error_code"] == "1010"
assert redacted["error_name"] == "browser_signature_banned"
assert "api_key" not in redacted
assert "secret" not in redacted

print(json.dumps({
    "simulated_http_status": 403,
    "classification": "upstream_access_denied",
    "cloudflare_error_1010_detected": True,
    "sensitive_fields_redacted": "api_key" not in redacted and "secret" not in redacted,
    "retryable": redacted.get("retryable"),
}, sort_keys=True))
