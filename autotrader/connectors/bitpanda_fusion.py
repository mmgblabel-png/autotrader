"""Bitpanda Fusion REST adapter.

This adapter intentionally starts with authenticated read-only support. Fusion
uses an ``x-api-key`` header; it does not use the Bitvavo HMAC scheme. Live
order methods remain fail-closed until the exact order contract and a suitable
non-production validation path are confirmed from the vendor documentation.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)


class BitpandaFusionError(RuntimeError):
    """Non-sensitive Fusion adapter error."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "bitpanda_fusion_error",
        status: int | None = None,
        response_code: str | int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status = status
        self.response_code = response_code


class BitpandaFusionAdapter:
    """Safe Fusion client with authenticated read-only capability.

    Environment variables:
      BITPANDA_FUSION_API_KEY: Fusion API key; never logged.
      BITPANDA_FUSION_BASE_URL: override only for an approved test endpoint.
      BITPANDA_FUSION_DRY_RUN: defaults to true.
      EXECUTION_MODE: live orders are blocked unless explicitly set to live,
        but the adapter still blocks order methods by design until enabled in a
        later, separately audited change.
    """

    name = "bitpanda_fusion"
    BASE_URL = "https://api.fusion.bitpanda.com"
    BALANCES_PATH = "/v1/account/balances"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
        opener: Any = urllib.request.urlopen,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("BITPANDA_FUSION_API_KEY", "")).strip()
        self.base_url = (base_url or os.getenv("BITPANDA_FUSION_BASE_URL", self.BASE_URL)).rstrip("/")
        self.timeout = timeout
        self._opener = opener
        self.dry_run = os.getenv("BITPANDA_FUSION_DRY_RUN", "true").lower() in {"1", "true", "yes"}

    @property
    def credentials_present(self) -> bool:
        return bool(self.api_key)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Any:
        if not self.api_key:
            raise BitpandaFusionError(
                "BITPANDA_FUSION_API_KEY is not configured",
                category="credentials_missing",
            )
        method = method.upper()
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        body_text = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers = {
            "Accept": "application/json",
            "x-api-key": self.api_key,
        }
        if body_text:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=body_text.encode("utf-8") if body_text else None,
            method=method,
            headers=headers,
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            response_code: str | int | None = None
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                if isinstance(payload, dict):
                    response_code = payload.get("code") or payload.get("error") or payload.get("message")
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                pass
            category = "invalid_credentials" if exc.code in {401, 403} else "fusion_http_error"
            raise BitpandaFusionError(
                "Bitpanda Fusion request was rejected",
                category=category,
                status=exc.code,
                response_code=response_code,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BitpandaFusionError(
                "Bitpanda Fusion request could not reach the service",
                category="network_error",
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BitpandaFusionError(
                "Bitpanda Fusion returned an invalid response",
                category="invalid_response",
            ) from exc

    def authenticate(self) -> dict[str, Any]:
        """Validate the key using Fusion's documented balances endpoint.

        Returns only safe metadata; the balance payload is intentionally not
        included in the returned diagnostic object.
        """
        payload = self._request("GET", self.BALANCES_PATH)
        if not isinstance(payload, (dict, list)):
            raise BitpandaFusionError("Unexpected Fusion balances response", category="invalid_response")
        return {
            "venue": self.name,
            "credentials_present": True,
            "authenticated": True,
            "endpoint": self.BALANCES_PATH,
            "response_type": type(payload).__name__,
            "balance_entries": len(payload) if isinstance(payload, list) else None,
        }

    def balances(self) -> Any:
        """Return the authenticated balances payload for internal callers."""
        return self._request("GET", self.BALANCES_PATH)

    def supported_pairs(self) -> Any:
        """Fetch supported pairs using a configurable documented path.

        Fusion's public docs should be checked at deployment time before this
        method is enabled in production; the path can be supplied explicitly.
        """
        path = os.getenv("BITPANDA_FUSION_SUPPORTED_PAIRS_PATH", "")
        if not path:
            raise BitpandaFusionError(
                "Fusion supported-pairs endpoint is not configured",
                category="endpoint_not_configured",
            )
        return self._request("GET", path)

    def place_limit_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Return a shadow proposal only; live Fusion orders are blocked."""
        proposal = {"venue": self.name, "order_type": "limit", "args": args, "kwargs": kwargs}
        if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
            return {"status": "SHADOW", "would_place": proposal}
        raise BitpandaFusionError(
            "Fusion live order placement is blocked until the order contract and safety audit are complete",
            category="live_orders_blocked",
        )

    def place_market_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Return a shadow proposal only; live Fusion orders are blocked."""
        proposal = {"venue": self.name, "order_type": "market", "args": args, "kwargs": kwargs}
        if self.dry_run or os.getenv("EXECUTION_MODE", "paper") != "live":
            return {"status": "SHADOW", "would_place": proposal}
        raise BitpandaFusionError(
            "Fusion live order placement is blocked until the order contract and safety audit are complete",
            category="live_orders_blocked",
        )

    def get_mid_price(self, symbol: str) -> Decimal:
        """Market-price endpoint is intentionally not guessed from docs."""
        raise BitpandaFusionError(
            f"Fusion market-price endpoint is not configured for {symbol.upper()}",
            category="endpoint_not_configured",
        )

    def redacted_status(self) -> dict[str, Any]:
        """Return credential-presence status without contacting Fusion."""
        return {"venue": self.name, "credentials_present": self.credentials_present}


__all__ = ["BitpandaFusionAdapter", "BitpandaFusionError"]
