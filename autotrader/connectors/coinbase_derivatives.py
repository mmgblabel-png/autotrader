"""Read-only Coinbase Global Derivatives (Starbase/Deribit) connector.

This connector deliberately exposes only public market data plus read-only
account/risk probes. It contains no order-placement methods.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData


class CoinbaseDerivativesError(RuntimeError):
    def __init__(self, message: str, *, category: str = "derivatives_request_failed") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class CoinbaseDerivativesTicker:
    instrument_name: str
    mark_price: float
    index_price: float
    best_bid_price: float
    best_ask_price: float
    open_interest: float
    volume_usd: float
    price_change_pct: float
    current_funding: float

    @property
    def spread_bps(self) -> float:
        mid = (self.best_bid_price + self.best_ask_price) / 2.0
        if mid <= 0.0:
            return 0.0
        return max(0.0, (self.best_ask_price - self.best_bid_price) / mid * 10000.0)


class CoinbaseDerivativesGateway:
    """Minimal JSON-RPC client for Coinbase Global Derivatives.

    Host and protocol follow Coinbase's post-2026-10-01 Starbase migration.
    Private methods are read-only probes only.
    """

    BASE_URL = "https://drb.coinbase.com/api/v2"
    HOST = "drb.coinbase.com"

    def __init__(self, *, timeout: float = 5.0) -> None:
        self.timeout = max(1.0, float(timeout))

    @staticmethod
    def _json_result(payload: object) -> Any:
        if not isinstance(payload, dict):
            raise CoinbaseDerivativesError("Unexpected derivatives response", category="unexpected_response")
        if payload.get("error"):
            err = payload.get("error")
            if isinstance(err, dict):
                code = str(err.get("code") or "")
                message = str(err.get("message") or "")
                text = f"{code} {message}".lower()
                if "permission" in text or "not allowed" in text or "forbidden" in text:
                    category = "trade_permission_missing"
                elif "auth" in text or "token" in text or "credential" in text:
                    category = "authentication_failed"
                else:
                    category = "api_error"
            else:
                category = "api_error"
            raise CoinbaseDerivativesError("Coinbase derivatives API returned an error", category=category)
        if "result" not in payload:
            raise CoinbaseDerivativesError("Coinbase derivatives result missing", category="unexpected_response")
        return payload["result"]

    def _request(
        self,
        path: str,
        *,
        method_name: str,
        params: dict[str, Any] | None = None,
        http_method: str = "GET",
        bearer: str | None = None,
        jsonrpc_base: bool = False,
    ) -> Any:
        params = dict(params or {})
        http_method = http_method.upper()
        headers = {
            "Accept": "application/json",
            "User-Agent": "autotrader-coinbase-derivatives/1.0",
        }
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        body = None
        url = self.BASE_URL if jsonrpc_base else self.BASE_URL + path
        if http_method == "GET":
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)
        else:
            headers["Content-Type"] = "application/json"
            body = json.dumps(
                {
                    "id": int(time.time() * 1000) % 2_000_000_000,
                    "jsonrpc": "2.0",
                    "method": method_name,
                    "params": params,
                },
                separators=(",", ":"),
            ).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=http_method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise CoinbaseDerivativesError(
                "Coinbase derivatives HTTP request failed",
                category=f"http_{int(exc.code)}",
            ) from exc
        except urllib.error.URLError as exc:
            raise CoinbaseDerivativesError(
                "Coinbase derivatives transport request failed",
                category="transport_error",
            ) from exc
        except Exception as exc:
            raise CoinbaseDerivativesError(
                f"Coinbase derivatives request failed: {type(exc).__name__}",
                category="network_or_http_error",
            ) from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CoinbaseDerivativesError("Coinbase derivatives response was not JSON", category="unexpected_response") from exc
        return self._json_result(payload)

    def _public_call(
        self,
        path: str,
        *,
        method_name: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Support both documented HTTP paths and canonical JSON-RPC base POST."""
        first_error: CoinbaseDerivativesError | None = None
        try:
            return self._request(
                path,
                method_name=method_name,
                params=params,
                http_method="GET",
            )
        except CoinbaseDerivativesError as exc:
            first_error = exc
        try:
            return self._request(
                path,
                method_name=method_name,
                params=params,
                http_method="POST",
                jsonrpc_base=True,
            )
        except CoinbaseDerivativesError as exc:
            # Return the fallback category: it reflects the canonical JSON-RPC
            # route and is usually the more useful production diagnosis.
            raise CoinbaseDerivativesError(
                "Coinbase derivatives public method failed on REST and JSON-RPC transports",
                category=exc.category or (first_error.category if first_error else "public_call_failed"),
            ) from exc

    @staticmethod
    def _build_cdp_jwt(method: str, path: str) -> str:
        fmt = CoinbaseAdvancedMarketData._credential_format()
        if not fmt.get("credentials_present"):
            raise CoinbaseDerivativesError("Coinbase credentials are missing", category="credentials_missing")
        if not fmt.get("format_compatible"):
            raise CoinbaseDerivativesError("Coinbase credentials are not compatible", category="credential_format_invalid")

        key_name = os.getenv("COINBASE_API_KEY", "").strip()
        key_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n").strip()
        now = int(time.time())
        payload = {
            "sub": key_name,
            "iss": "cdp",
            "nbf": now,
            "iat": now,
            "exp": now + 120,
            "uri": f"{method.upper()} {CoinbaseDerivativesGateway.HOST}{path}",
        }
        headers = {
            "kid": key_name,
            "nonce": secrets.token_hex(16),
            "typ": "JWT",
        }
        try:
            if fmt.get("ed25519_private_key_format_ok"):
                decoded = base64.b64decode(key_secret, validate=True)
                private_key = Ed25519PrivateKey.from_private_bytes(decoded[:32])
                return jwt.encode(payload, private_key, algorithm="EdDSA", headers=headers)
            private_key = serialization.load_pem_private_key(key_secret.encode("utf-8"), password=None)
            return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
        except Exception as exc:
            raise CoinbaseDerivativesError("Coinbase CDP JWT signing failed", category="private_key_parse_failed") from exc

    def authenticate(self) -> dict[str, Any]:
        path = "/public/auth"
        token = self._build_cdp_jwt("POST", "/api/v2/public/auth")
        result = self._request(
            path,
            method_name="public/auth",
            params={"grant_type": "coinbase_cdp", "token": token},
            http_method="POST",
        )
        if not isinstance(result, dict) or not str(result.get("access_token") or ""):
            raise CoinbaseDerivativesError("Derivatives access token missing", category="authentication_failed")
        return dict(result)

    def auth_probe(self) -> dict[str, Any]:
        probe: dict[str, Any] = {
            "authenticated": False,
            "risk_profile_readable": False,
            "positions_readable": False,
            "error_category": None,
            "order_sent": False,
        }
        try:
            auth = self.authenticate()
            access = str(auth.get("access_token") or "")
            probe["authenticated"] = True
            risk = self._request(
                "/private/get_risk_profile",
                method_name="private/get_risk_profile",
                bearer=access,
            )
            probe["risk_profile_readable"] = isinstance(risk, dict)
            positions = self._request(
                "/private/get_positions",
                method_name="private/get_positions",
                params={"currency": "any", "kind": "future", "include_isolated": True},
                bearer=access,
            )
            probe["positions_readable"] = isinstance(positions, list)
            probe["position_count"] = len(positions) if isinstance(positions, list) else None
            if isinstance(risk, dict):
                # Privacy-safe subset only.
                for key in (
                    "portfolio_margining_enabled",
                    "cross_collateral_enabled",
                    "max_leverage",
                    "margin_model",
                    "is_direct_access_allowed",
                ):
                    if key in risk:
                        probe[key] = risk[key]
        except CoinbaseDerivativesError as exc:
            probe["error_category"] = exc.category
        except Exception as exc:
            probe["error_category"] = type(exc).__name__
        return probe

    def list_futures(self, *, currency: str = "any") -> list[dict[str, Any]]:
        result = self._public_call(
            "/public/get_instruments",
            method_name="public/get_instruments",
            params={"currency": currency, "kind": "future", "expired": False},
        )
        if not isinstance(result, list):
            raise CoinbaseDerivativesError("Unexpected instruments response", category="unexpected_response")
        return [dict(row) for row in result if isinstance(row, dict)]

    def ticker(self, instrument_name: str) -> CoinbaseDerivativesTicker:
        result = self._public_call(
            "/public/ticker",
            method_name="public/ticker",
            params={"instrument_name": str(instrument_name)},
        )
        if not isinstance(result, dict):
            raise CoinbaseDerivativesError("Unexpected ticker response", category="unexpected_response")
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}

        def num(key: str, default: float = 0.0) -> float:
            try:
                return float(result.get(key) if result.get(key) is not None else default)
            except (TypeError, ValueError):
                return default

        def stat_num(key: str, default: float = 0.0) -> float:
            try:
                return float(stats.get(key) if stats.get(key) is not None else default)
            except (TypeError, ValueError):
                return default

        return CoinbaseDerivativesTicker(
            instrument_name=str(result.get("instrument_name") or instrument_name),
            mark_price=num("mark_price"),
            index_price=num("index_price"),
            best_bid_price=num("best_bid_price"),
            best_ask_price=num("best_ask_price"),
            open_interest=num("open_interest"),
            volume_usd=stat_num("volume_usd"),
            price_change_pct=stat_num("price_change"),
            current_funding=num("current_funding"),
        )
