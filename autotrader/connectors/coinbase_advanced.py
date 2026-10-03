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
import base64
import secrets
import time
import urllib.error

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


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
    PRODUCTS_PATH = "/api/v3/brokerage/market/products"
    ACCOUNTS_PATH = "/api/v3/brokerage/accounts"
    INTX_POSITIONS_PATH = "/api/v3/brokerage/intx/positions/{portfolio_uuid}"
    INTX_BALANCES_PATH = "/api/v3/brokerage/intx/balances/{portfolio_uuid}"

    def __init__(self, *, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self.BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Accept": "application/json",
            "User-Agent": "autotrader-coinbase-marketdata/1.0",
        }
        # Coinbase public endpoints allow authentication and the official SDK
        # recommends it for higher rate limits. Fall back to unauthenticated
        # public access if credentials are absent or malformed.
        try:
            if bool(self._credential_format().get("format_compatible")):
                headers["Authorization"] = f"Bearer {self._build_rest_jwt('GET', path)}"
        except Exception:
            pass
        request = urllib.request.Request(
            url,
            method="GET",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CoinbaseMarketDataError(
                f"Coinbase public market-data request failed: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _credential_format() -> dict[str, object]:
        key_name = os.getenv("COINBASE_API_KEY", "").strip()
        key_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n").strip()
        key_name_ok = bool(
            key_name
            and (
                (key_name.startswith("organizations/") and "/apiKeys/" in key_name)
                or (len(key_name) == 36 and key_name.count("-") == 4)
            )
        )
        ec_key = "BEGIN " in key_secret and "PRIVATE KEY" in key_secret
        ed25519_key = False
        if key_secret and not ec_key:
            try:
                ed25519_key = len(base64.b64decode(key_secret, validate=True)) == 64
            except Exception:
                ed25519_key = False
        return {
            "credentials_present": bool(key_name and key_secret),
            "key_name_format_ok": key_name_ok,
            "ecdsa_private_key_format_ok": ec_key,
            "ed25519_private_key_format_ok": ed25519_key,
            "format_compatible": bool(key_name_ok and (ec_key or ed25519_key)),
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
                "Coinbase credentials are not in a supported CDP format",
                category="credential_format_invalid",
            )

        key_name = os.getenv("COINBASE_API_KEY", "").strip()
        key_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n").strip()
        now = int(time.time())
        uri = f"{method.upper()} api.coinbase.com{path}"
        payload = {
            "sub": key_name,
            "iss": "cdp",
            "nbf": now,
            "iat": now,
            "exp": now + 120,
            "uris": [uri],
        }
        headers = {
            "kid": key_name,
            "nonce": secrets.token_hex(16),
            "typ": "JWT",
        }

        try:
            if fmt["ed25519_private_key_format_ok"]:
                decoded = base64.b64decode(key_secret, validate=True)
                private_key = Ed25519PrivateKey.from_private_bytes(decoded[:32])
                return jwt.encode(
                    payload,
                    private_key,
                    algorithm="EdDSA",
                    headers=headers,
                )

            private_key = serialization.load_pem_private_key(
                key_secret.encode("utf-8"),
                password=None,
            )
            return jwt.encode(
                payload,
                private_key,
                algorithm="ES256",
                headers=headers,
            )
        except Exception as exc:
            raise CoinbaseAuthenticationError(
                "Coinbase private key could not be parsed or signed",
                category="private_key_parse_failed",
            ) from exc

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

    def account_balances(self) -> dict[str, object]:
        """Return a privacy-safe balance summary from Coinbase Advanced.

        Account UUIDs, names, API credentials and other identifiers are never
        returned. Balances are aggregated by currency across active accounts.
        """
        payload = self._auth_get(self.ACCOUNTS_PATH)
        accounts = payload.get("accounts") if isinstance(payload, dict) else None
        if not isinstance(accounts, list):
            raise CoinbaseAuthenticationError(
                "Coinbase accounts response was not understood",
                category="unexpected_response",
            )

        aggregated: dict[str, dict[str, Decimal]] = {}
        active_accounts = 0
        for account in accounts:
            if not isinstance(account, dict):
                continue
            currency = str(account.get("currency") or "").upper().strip()
            if not currency:
                continue
            if account.get("active", True):
                active_accounts += 1

            available_obj = account.get("available_balance") or {}
            hold_obj = account.get("hold") or {}
            try:
                available = Decimal(str(available_obj.get("value") or "0"))
                hold = Decimal(str(hold_obj.get("value") or "0"))
            except (ValueError, TypeError):
                continue

            bucket = aggregated.setdefault(
                currency,
                {"available": Decimal("0"), "hold": Decimal("0")},
            )
            bucket["available"] += max(available, Decimal("0"))
            bucket["hold"] += max(hold, Decimal("0"))

        assets = []
        for currency, amounts in aggregated.items():
            total = amounts["available"] + amounts["hold"]
            if total == 0:
                continue
            assets.append(
                {
                    "currency": currency,
                    "available": format(amounts["available"], "f"),
                    "hold": format(amounts["hold"], "f"),
                    "total": format(total, "f"),
                }
            )
        preferred_order = {"EUR": 0, "USD": 1, "USDC": 2, "BTC": 3, "ETH": 4, "SOL": 5, "XRP": 6}
        assets.sort(
            key=lambda row: (
                preferred_order.get(row["currency"], 100),
                row["currency"],
            )
        )
        return {
            "venue": "coinbase_advanced",
            "authenticated": True,
            "read_only": True,
            "account_count": len(accounts),
            "active_account_count": active_accounts,
            "asset_count": len(assets),
            "assets": assets,
        }

    @staticmethod
    def _safe_portfolio_uuid(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise CoinbaseAuthenticationError(
                "Coinbase derivatives portfolio is not configured",
                category="derivatives_portfolio_missing",
            )
        # UUID-like values only; never allow arbitrary path fragments.
        import uuid
        try:
            return str(uuid.UUID(raw))
        except ValueError as exc:
            raise CoinbaseAuthenticationError(
                "Coinbase derivatives portfolio identifier is invalid",
                category="derivatives_portfolio_invalid",
            ) from exc

    def perpetual_positions_read_only(self, portfolio_uuid: str) -> dict[str, object]:
        """Return privacy-safe derivatives position risk fields; never places orders."""
        pid = self._safe_portfolio_uuid(portfolio_uuid)
        path = self.INTX_POSITIONS_PATH.format(portfolio_uuid=pid)
        payload = self._auth_get(path)
        rows = payload.get("positions") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise CoinbaseAuthenticationError(
                "Coinbase derivatives positions response was not understood",
                category="unexpected_derivatives_response",
            )
        positions = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            positions.append({
                "product_id": str(row.get("product_id") or ""),
                "symbol": str(row.get("symbol") or ""),
                "position_side": str(row.get("position_side") or ""),
                "margin_type": str(row.get("margin_type") or ""),
                "net_size": str(row.get("net_size") or "0"),
                "leverage": str(row.get("leverage") or "0"),
                "mark_price": str((row.get("mark_price") or {}).get("value") or "0"),
                "liquidation_price": str((row.get("liquidation_price") or {}).get("value") or "0"),
                "position_notional": str((row.get("position_notional") or {}).get("value") or "0"),
                "unrealized_pnl": str((row.get("unrealized_pnl") or {}).get("value") or "0"),
                "im_contribution": str(row.get("im_contribution") or "0"),
            })
        return {
            "venue": "coinbase_derivatives",
            "read_only": True,
            "position_count": len(positions),
            "positions": positions,
        }

    def perpetual_balances_read_only(self, portfolio_uuid: str) -> dict[str, object]:
        """Return aggregate collateral values without exposing portfolio identifiers."""
        pid = self._safe_portfolio_uuid(portfolio_uuid)
        path = self.INTX_BALANCES_PATH.format(portfolio_uuid=pid)
        payload = self._auth_get(path)
        rows = payload.get("portfolio_balances") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise CoinbaseAuthenticationError(
                "Coinbase derivatives balances response was not understood",
                category="unexpected_derivatives_response",
            )
        assets = []
        margin_limit_reached = False
        for portfolio in rows:
            if not isinstance(portfolio, dict):
                continue
            margin_limit_reached = margin_limit_reached or bool(
                portfolio.get("is_margin_limit_reached", False)
            )
            for row in portfolio.get("balances") or []:
                if not isinstance(row, dict):
                    continue
                asset = row.get("asset") or {}
                assets.append({
                    "asset": str(asset.get("asset_id") or asset.get("asset_name") or ""),
                    "quantity": str(row.get("quantity") or "0"),
                    "hold": str(row.get("hold") or "0"),
                    "collateral_value": str(row.get("collateral_value") or "0"),
                    "collateral_weight": str(row.get("collateral_weight") or ""),
                    "max_withdraw_amount": str(row.get("max_withdraw_amount") or "0"),
                })
        return {
            "venue": "coinbase_derivatives",
            "read_only": True,
            "asset_count": len(assets),
            "is_margin_limit_reached": margin_limit_reached,
            "assets": assets,
        }

    def derivatives_risk_probe(self, portfolio_uuid: str | None = None) -> dict[str, object]:
        """Probe derivatives access read-only; missing eligibility/portfolio fails closed."""
        raw = str(
            portfolio_uuid
            or os.getenv("COINBASE_INTX_PORTFOLIO_UUID", "")
        ).strip()
        if not raw:
            return {
                "venue": "coinbase_derivatives",
                "read_only": True,
                "configured": False,
                "authenticated": False,
                "eligible": None,
                "error_category": "derivatives_portfolio_missing",
            }
        try:
            positions = self.perpetual_positions_read_only(raw)
            balances = self.perpetual_balances_read_only(raw)
            return {
                "venue": "coinbase_derivatives",
                "read_only": True,
                "configured": True,
                "authenticated": True,
                "eligible": True,
                "positions": positions,
                "balances": balances,
                "error_category": None,
            }
        except CoinbaseAuthenticationError as exc:
            return {
                "venue": "coinbase_derivatives",
                "read_only": True,
                "configured": True,
                "authenticated": False,
                "eligible": None,
                "error_category": exc.category,
                "status": exc.status,
            }

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

    def list_spot_products(
        self,
        *,
        page_size: int = 250,
        max_pages: int = 20,
    ) -> list[dict[str, object]]:
        """Return the full public Coinbase Advanced SPOT product catalogue.

        Pagination is followed defensively. The returned shape is normalized so
        callers do not need to depend on every upstream product field.
        """
        page_size = max(1, min(1000, int(page_size)))
        max_pages = max(1, min(100, int(max_pages)))
        cursor: str | None = None
        products: list[dict[str, object]] = []
        seen: set[str] = set()

        for _ in range(max_pages):
            params = {
                "limit": str(page_size),
                "product_type": "SPOT",
            }
            if cursor:
                params["cursor"] = cursor
            payload = self._get(self.PRODUCTS_PATH, params)
            rows = payload.get("products") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise CoinbaseMarketDataError("Unexpected Coinbase products response")

            for row in rows:
                if not isinstance(row, dict):
                    continue
                product_id = self.normalize_product_id(str(row.get("product_id") or ""))
                if not product_id or product_id in seen or "-" not in product_id:
                    continue
                base, quote = product_id.rsplit("-", 1)
                trading_disabled = bool(row.get("trading_disabled", False))
                cancel_only = bool(row.get("cancel_only", False))
                is_disabled = bool(row.get("is_disabled", False))
                view_only = bool(row.get("view_only", False))
                product_type = str(row.get("product_type") or "SPOT").upper()
                if product_type not in {"SPOT", "UNKNOWN_PRODUCT_TYPE", ""}:
                    continue
                seen.add(product_id)
                products.append({
                    "product_id": product_id,
                    "base": str(row.get("base_currency_id") or base).upper(),
                    "quote": str(row.get("quote_currency_id") or quote).upper(),
                    "product_type": product_type or "SPOT",
                    "trading_disabled": trading_disabled,
                    "cancel_only": cancel_only,
                    "is_disabled": is_disabled,
                    "view_only": view_only,
                    "tradable": not (trading_disabled or cancel_only or is_disabled or view_only),
                    "price": row.get("price"),
                    "volume_24h": row.get("volume_24h"),
                    "price_change_24h_pct": row.get("price_percentage_change_24h"),
                    "base_increment": row.get("base_increment"),
                    "quote_increment": row.get("quote_increment"),
                })

            next_cursor = ""
            if isinstance(payload, dict):
                next_cursor = str(
                    payload.get("cursor")
                    or (payload.get("pagination") or {}).get("next_cursor")
                    or ""
                ).strip()
                has_next = payload.get("has_next")
            else:
                has_next = False
            if not next_cursor or next_cursor == cursor or has_next is False:
                break
            cursor = next_cursor

        products.sort(key=lambda row: str(row["product_id"]))
        return products

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
