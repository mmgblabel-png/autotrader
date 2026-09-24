#!/usr/bin/env python3
"""Redacted Bitpanda Fusion key probe.

The script never prints the API key or balances. Without
BITPANDA_FUSION_API_KEY it performs only a safe configuration check.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter, BitpandaFusionError


def main() -> int:
    adapter = BitpandaFusionAdapter()
    if not adapter.credentials_present:
        print(json.dumps({**adapter.redacted_status(), "authenticated": False, "reason": "credentials_missing"}))
        return 2
    try:
        print(json.dumps(adapter.authenticate(), sort_keys=True))
        return 0
    except BitpandaFusionError as exc:
        print(json.dumps({
            "venue": adapter.name,
            "credentials_present": True,
            "authenticated": False,
            "category": exc.category,
            "status": exc.status,
            "response_code": exc.response_code,
        }, sort_keys=True))
        return 1
    except Exception as exc:  # defensive redaction boundary
        print(json.dumps({
            "venue": adapter.name,
            "credentials_present": True,
            "authenticated": False,
            "category": "unexpected_error",
            "error_type": type(exc).__name__,
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
