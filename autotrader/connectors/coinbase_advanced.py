"""Read-only Coinbase Advanced market-data connector.

Uses Coinbase's public Advanced Trade REST endpoints only. No API key is
required and this module contains no order-placement capability.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import os
import secrets
import time
import urllib.error

import jwt
from cryptography.hazmat.primitives import serialization


class CoinbaseMarketDataError(RuntimeError):
    pass


class CoinbaseAuthenticationError(RuntimeError):
    """Raised when authenticated Coinbase access cannot be established."""

    def __init__(self, message: str, *, status: int | None = None, category: str = "authentication_failed") -> None:
        super().__init__(message)
        self.status = status
        self.category = category


@dataclass(frozen=True)
class CoinbaseTopOfBook:
    product_id: str
    bid_price: Decimal
    bid_size: Decimal
    ask_price: Decimal
    ask_size: Decimal

    @property
    def mid_price(self) -> Decimal:
        return (self.bid_price + self.ask_price) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal:
        if self.mid_price <= 0:
            return Decimal("0")
        return (self.ask_price - self.bid_price) / self.mid_price * Decimal("10000")


class CoinbaseAdvancedMarketData:
    """Minimal fail-closed client for Coinbase Advanced public market data."""

    BASE_URL = "https://api.coinbase.com"
    BOOK_PATH = "/api/v3/brokerage/market/product_book"
    ACCOUNTS_PATH = "/api/v3/brokerage/accounts"

    def __init__(self, *, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self.BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "autotrader-coinbase-marketdata/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CoinbaseMarketDataError("Coinbase public market-data request failed") from exc

    @staticmethod
    def _credential_format() -> dict[str, object]:
        key_name = os.getenv("COINBASE_API_KEY", "").strip()
        key_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n").strip()
        key_name_ok = key_name.startswith("organizations/") and "/apiKeys/" in key_name
        key_secret_ok = (
            "BEGIN EC PRIVATE KEY" in key_secret
            or "BEGIN PRIVATE KEY" in key_secret
        )
        return {
            "credentials_present": bool(key_name and key_secret),
            "key_name_format_ok": key_name_ok,
            "ecdsa_private_key_format_ok": key_secret_ok,
            "format_compatible": bool(key_name_ok and key_secret_ok),
        }

    def _build_rest_jwt(self, method: str, path: str) -> str:
        fmt = self._credential_format()
        if not fmt["credentials_present"]:
            raise CoinbaseAuthenticationError(
                "Coinbase credentials are missing",
                category="credentials_missing",
            )
        if not fmt["format_compatible"]:
            raise CoinbaseAuthenticationError(
                "Coinbase credentials are not in the expected CDP ECDSA format",
                category="credential_format_invalid",
            )

        key_name = os.getenv("COINBASE_API_KEY", "").strip()
        key_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n")
        try:
            private_key = serialization.load_pem_private_key(
                key_secret.encode("utf-8"),
                password=None,
            )
        except Exception as exc:
            raise CoinbaseAuthenticationError(
                "Coinbase private key could not be parsed",
                category="private_key_parse_failed",
            ) from exc

        now = int(time.time())
        uri = f"{method.upper()} api.coinbase.com{path}"
        payload = {
            "sub": key_name,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": uri,
        }
        return jwt.encode(
            payload,
            private_key,
            algorithm="ES256",
            headers={
                "kid": key_name,
                "nonce": secrets.token_hex(16),
            },
        )

    def _auth_get(self, path: str) -> Any:
        token = self._build_rest_jwt("GET", path)
        request = urllib.request.Request(
            self.BASE_URL + path,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "autotrader-coinbase-auth/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                category = "unauthorized_or_ip_restricted"
            elif exc.code == 429:
                category = "rate_limited"
            else:
                category = "http_error"
            raise CoinbaseAuthenticationError(
                "Coinbase authenticated request failed",
                status=exc.code,
                category=category,
            ) from exc
        except Exception as exc:
            raise CoinbaseAuthenticationError(
                "Coinbase authenticated request failed",
                category="network_error",
            ) from exc

    def authenticated_accounts_probe(self) -> dict[str, object]:
        fmt = self._credential_format()
        result: dict[str, object] = {
            "venue": "coinbase_advanced",
            "read_only": True,
            **fmt,
            "authenticated": False,
            "status": None,
            "account_count": None,
            "error_category": None,
        }
        if not fmt["credentials_present"] or not fmt["format_compatible"]:
            result["error_category"] = (
                "credentials_missing"
                if not fmt["credentials_present"]
                else "credential_format_invalid"
            )
            return result
        try:
            payload = self._auth_get(self.ACCOUNTS_PATH)
            accounts = payload.get("accounts") if isinstance(payload, dict) else None
            result["authenticated"] = isinstance(accounts, list)
            result["status"] = 200 if result["authenticated"] else None
            result["account_count"] = len(accounts) if isinstance(accounts, list) else None
            if not result["authenticated"]:
                result["error_category"] = "unexpected_response"
            return result
        except CoinbaseAuthenticationError as exc:
            result["status"] = exc.status
            result["error_category"] = exc.category
            return result

    @staticmethod
    def normalize_product_id(symbol: str) -> str:
        return symbol.strip().upper().replace("/", "-")

    def top_of_book(self, symbol: str) -> CoinbaseTopOfBook:
        product_id = self.normalize_product_id(symbol)
        payload = self._get(
            self.BOOK_PATH,
            {"product_id": product_id, "limit": "1"},
        )
        pricebook = payload.get("pricebook") if isinstance(payload, dict) else None
        bids = pricebook.get("bids") if isinstance(pricebook, dict) else None
        asks = pricebook.get("asks") if isinstance(pricebook, dict) else None
        if not bids or not asks:
            raise CoinbaseMarketDataError("Coinbase product book has no bid/ask")

        bid = bids[0]
        ask = asks[0]
        try:
            bid_price = Decimal(str(bid["price"]))
            bid_size = Decimal(str(bid["size"]))
            ask_price = Decimal(str(ask["price"]))
            ask_size = Decimal(str(ask["size"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise CoinbaseMarketDataError("Unexpected Coinbase product-book response") from exc

        if bid_price <= 0 or ask_price <= 0 or bid_size <= 0 or ask_size <= 0:
            raise CoinbaseMarketDataError("Invalid Coinbase top-of-book values")
        if ask_price < bid_price:
            raise CoinbaseMarketDataError("Crossed Coinbase product book")

        return CoinbaseTopOfBook(
            product_id=product_id,
            bid_price=bid_price,
            bid_size=bid_size,
            ask_price=ask_price,
            ask_size=ask_size,
        )
