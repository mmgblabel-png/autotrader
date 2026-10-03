"""Wallet authentication and read-only AIHF entitlement services.

Security boundaries:
- never accepts seed phrases or private keys;
- never signs or broadcasts a transaction;
- never mutates AutoTrader state;
- reads only the canonical AIHFAccessVault on the configured chain;
- fails closed when chain/vault/finality checks cannot be completed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jwt
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import is_address, keccak, to_checksum_address


_TIER_NAMES = {0: "NONE", 1: "READER", 2: "PRO", 3: "QUANT"}
_TIER_RANK = {"NONE": 0, "READER": 1, "PRO": 2, "QUANT": 3}


class EcosystemConfigurationError(RuntimeError):
    """Required AIHF service configuration is absent or unsafe."""


class EcosystemAuthenticationError(ValueError):
    """Wallet challenge or session validation failed."""


class EcosystemRpcError(RuntimeError):
    """Canonical chain state could not be read safely."""


def _utc_iso(timestamp: int | float | None = None) -> str:
    value = time.time() if timestamp is None else float(timestamp)
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized_address(value: str) -> str:
    raw = str(value or "").strip()
    if not is_address(raw):
        raise EcosystemAuthenticationError("Invalid EVM wallet address")
    return to_checksum_address(raw)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _session_secret() -> str:
    value = os.getenv("AIHF_SESSION_SECRET", "").strip()
    if len(value) < 32:
        raise EcosystemConfigurationError(
            "AIHF_SESSION_SECRET must be configured with at least 32 characters"
        )
    return value


def _expected_chain_id() -> int:
    return _bounded_int("AIHF_EXPECTED_CHAIN_ID", 80002, 1, 2**31 - 1)


@dataclass(frozen=True)
class WalletChallenge:
    address: str
    nonce: str
    message: str
    issued_at: int
    expires_at: int


class WalletNonceStore:
    """Process-local, one-time nonce store for the closed beta.

    A multi-replica production deployment must replace this with a shared
    atomic store (for example Redis) before public launch.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, WalletChallenge] = {}

    def create(self, address: str) -> WalletChallenge:
        wallet = _normalized_address(address)
        now = int(time.time())
        ttl = _bounded_int("AIHF_NONCE_TTL_SECONDS", 300, 60, 900)
        nonce = secrets.token_urlsafe(18)
        domain = os.getenv("AIHF_AUTH_DOMAIN", "localhost").strip() or "localhost"
        uri = os.getenv("AIHF_AUTH_URI", "http://localhost:3000").strip() or "http://localhost:3000"
        chain_id = _expected_chain_id()
        expires = now + ttl
        message = (
            f"{domain} wants you to sign in to AI HedgeFund with your Ethereum account:\n"
            f"{wallet}\n\n"
            "This signature authenticates access only. It does not authorize a token transfer, "
            "trade, approval, or AutoTrader action.\n\n"
            f"URI: {uri}\n"
            "Version: 1\n"
            f"Chain ID: {chain_id}\n"
            f"Nonce: {nonce}\n"
            f"Issued At: {_utc_iso(now)}\n"
            f"Expiration Time: {_utc_iso(expires)}"
        )
        challenge = WalletChallenge(wallet, nonce, message, now, expires)
        with self._lock:
            self._prune_locked(now)
            self._items[nonce] = challenge
        return challenge

    def get(self, nonce: str) -> WalletChallenge:
        now = int(time.time())
        with self._lock:
            self._prune_locked(now)
            challenge = self._items.get(str(nonce))
            if challenge is None:
                raise EcosystemAuthenticationError("Challenge is missing, expired, or already used")
            return challenge

    def consume(self, nonce: str) -> None:
        with self._lock:
            challenge = self._items.pop(str(nonce), None)
            if challenge is None:
                raise EcosystemAuthenticationError("Challenge is missing, expired, or already used")

    def _prune_locked(self, now: int) -> None:
        expired = [key for key, item in self._items.items() if item.expires_at <= now]
        for key in expired:
            self._items.pop(key, None)


_nonce_store = WalletNonceStore()


def create_wallet_challenge(address: str) -> dict[str, Any]:
    challenge = _nonce_store.create(address)
    return {
        "address": challenge.address,
        "nonce": challenge.nonce,
        "message": challenge.message,
        "issued_at": _utc_iso(challenge.issued_at),
        "expires_at": _utc_iso(challenge.expires_at),
        "chain_id": _expected_chain_id(),
    }


def _issue_session(address: str) -> str:
    now = int(time.time())
    ttl = _bounded_int("AIHF_SESSION_TTL_SECONDS", 900, 300, 3600)
    payload = {
        "iss": "aihf-access",
        "aud": "aihf-ecosystem",
        "sub": _normalized_address(address),
        "chain_id": _expected_chain_id(),
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_urlsafe(12),
        "scope": "aihf:access",
    }
    return jwt.encode(payload, _session_secret(), algorithm="HS256")


def verify_wallet_challenge(
    *,
    address: str,
    nonce: str,
    message: str,
    signature: str,
) -> dict[str, Any]:
    wallet = _normalized_address(address)
    challenge = _nonce_store.get(nonce)
    if not hmac.compare_digest(wallet.lower(), challenge.address.lower()):
        raise EcosystemAuthenticationError("Challenge wallet mismatch")
    if not hmac.compare_digest(str(message), challenge.message):
        raise EcosystemAuthenticationError("Challenge message mismatch")
    try:
        recovered = Account.recover_message(
            encode_defunct(text=challenge.message),
            signature=str(signature),
        )
    except Exception as exc:
        raise EcosystemAuthenticationError("Invalid wallet signature") from exc
    if not hmac.compare_digest(recovered.lower(), wallet.lower()):
        raise EcosystemAuthenticationError("Wallet signature does not match address")

    # Consume only after a valid signature so unauthenticated requests cannot
    # invalidate another user's pending challenge.
    _nonce_store.consume(nonce)
    token = _issue_session(wallet)
    return {
        "access_token": token,
        "token_type": "bearer",
        "wallet": wallet,
        "expires_in": _bounded_int("AIHF_SESSION_TTL_SECONDS", 900, 300, 3600),
        "chain_id": _expected_chain_id(),
    }


def decode_ecosystem_session(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            str(token),
            _session_secret(),
            algorithms=["HS256"],
            audience="aihf-ecosystem",
            issuer="aihf-access",
            options={"require": ["exp", "iat", "sub", "chain_id", "scope"]},
        )
    except Exception as exc:
        raise EcosystemAuthenticationError("Invalid or expired AIHF session") from exc
    if payload.get("scope") != "aihf:access":
        raise EcosystemAuthenticationError("Invalid AIHF session scope")
    if int(payload.get("chain_id", -1)) != _expected_chain_id():
        raise EcosystemAuthenticationError("AIHF session chain mismatch")
    payload["sub"] = _normalized_address(str(payload.get("sub", "")))
    return payload


def valid_ecosystem_session(token: str | None) -> bool:
    if not token:
        return False
    try:
        decode_ecosystem_session(token)
        return True
    except (EcosystemAuthenticationError, EcosystemConfigurationError):
        return False


class JsonRpcClient:
    def __init__(self, url: str, timeout_seconds: float = 5.0) -> None:
        if not str(url).strip():
            raise EcosystemConfigurationError("AIHF Polygon RPC URL is not configured")
        self.url = str(url).strip()
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 15.0))
        self._request_id = 0
        self._lock = threading.Lock()

    def call(self, method: str, params: list[Any]) -> Any:
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
        body = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EcosystemRpcError("Polygon RPC request failed") from exc
        if payload.get("error"):
            raise EcosystemRpcError(f"Polygon RPC error for {method}")
        if "result" not in payload:
            raise EcosystemRpcError(f"Polygon RPC returned no result for {method}")
        return payload["result"]


def _rpc_url() -> str:
    return (
        os.getenv("AIHF_POLYGON_RPC_URL", "").strip()
        or os.getenv("POLYGON_AMOY_RPC_URL", "").strip()
    )


def _vault_address() -> str:
    raw = os.getenv("AIHF_ACCESS_VAULT_ADDRESS", "").strip()
    if not raw or not is_address(raw):
        raise EcosystemConfigurationError("AIHF_ACCESS_VAULT_ADDRESS is not configured")
    return to_checksum_address(raw)


def _encode_address_call(signature: str, wallet: str) -> str:
    selector = keccak(text=signature)[:4].hex()
    argument = int(_normalized_address(wallet), 16).to_bytes(32, "big").hex()
    return f"0x{selector}{argument}"


def _uint_result(value: Any, label: str) -> int:
    try:
        if not isinstance(value, str) or not value.startswith("0x"):
            raise ValueError
        return int(value, 16)
    except (TypeError, ValueError) as exc:
        raise EcosystemRpcError(f"Invalid {label} RPC result") from exc


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(relative_path: str) -> dict[str, Any]:
    path = _repo_root() / relative_path
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EcosystemConfigurationError(f"Cannot load {relative_path}") from exc


def load_access_catalog() -> dict[str, Any]:
    return _load_json("ecosystem-token/config/access-catalog.json")


def load_sandbox_hq_config() -> dict[str, Any]:
    return _load_json("ecosystem-token/config/sandbox-hq-access.json")


class EntitlementService:
    def __init__(self, rpc: Any | None = None) -> None:
        self.rpc = rpc or JsonRpcClient(_rpc_url())

    def _safe_block(self) -> tuple[str, int]:
        # Prefer safe; finalized is accepted as a stricter fallback.  Never
        # silently fall back to latest for entitlement issuance.
        for tag in ("safe", "finalized"):
            try:
                block = self.rpc.call("eth_getBlockByNumber", [tag, False])
                if isinstance(block, dict) and block.get("number"):
                    number_hex = str(block["number"])
                    return number_hex, int(number_hex, 16)
            except EcosystemRpcError:
                continue
        raise EcosystemRpcError("RPC does not provide a safe/finalized block")

    def snapshot(self, wallet: str) -> dict[str, Any]:
        address = _normalized_address(wallet)
        chain_id = _uint_result(self.rpc.call("eth_chainId", []), "chain id")
        expected = _expected_chain_id()
        if chain_id != expected:
            raise EcosystemRpcError(
                f"Wrong chain: expected {expected}, received {chain_id}"
            )

        vault = _vault_address()
        block_tag, block_number = self._safe_block()
        tier_raw = _uint_result(
            self.rpc.call(
                "eth_call",
                [{"to": vault, "data": _encode_address_call("tierOf(address)", address)}, block_tag],
            ),
            "tier",
        )
        active_raw = _uint_result(
            self.rpc.call(
                "eth_call",
                [
                    {
                        "to": vault,
                        "data": _encode_address_call("activeLockedBalance(address)", address),
                    },
                    block_tag,
                ],
            ),
            "active locked balance",
        )
        if tier_raw not in _TIER_NAMES:
            raise EcosystemRpcError("Vault returned an unknown entitlement tier")

        return {
            "wallet": address,
            "tier": _TIER_NAMES[tier_raw],
            "tier_rank": tier_raw,
            "active_locked_aihf_wei": str(active_raw),
            "active_locked_aihf": f"{active_raw / 10**18:.18f}".rstrip("0").rstrip(".") or "0",
            "network": "polygon-amoy" if expected == 80002 else f"chain-{expected}",
            "chain_id": chain_id,
            "vault": vault,
            "block_number": block_number,
            "observed_at": _utc_iso(),
            "source": "AIHFAccessVault",
            "read_only": True,
        }


def sandbox_pass_eligibility(snapshot: dict[str, Any]) -> dict[str, Any]:
    config = load_sandbox_hq_config()
    tier = str(snapshot.get("tier", "NONE")).upper()
    tier_rank = _TIER_RANK.get(tier, 0)
    if tier_rank <= 0:
        return {
            "eligible": False,
            "tier": "NONE",
            "pass_name": None,
            "sandbox_asset_url": None,
            "reason": "insufficient_live_aihf_entitlement",
        }

    entry = config["tiers"].get(tier)
    if not isinstance(entry, dict):
        raise EcosystemConfigurationError("Sandbox tier mapping is incomplete")
    asset_url = (
        config.get("sandbox_pass_policy", {})
        .get("asset_urls", {})
        .get(tier)
    )
    return {
        "eligible": True,
        "tier": tier,
        "pass_name": entry.get("sandbox_pass"),
        "sandbox_asset_url": asset_url,
        "native_sensor": config.get("sandbox_pass_policy", {}).get("native_sensor"),
        "live_entitlement_required": True,
        "reason": "live_aihf_entitlement_verified",
    }


def sandbox_pass_claim(snapshot: dict[str, Any]) -> dict[str, Any]:
    eligibility = sandbox_pass_eligibility(snapshot)
    if not eligibility["eligible"]:
        return {**eligibility, "claimable": False, "status": "not_eligible"}

    epoch_days = _bounded_int("AIHF_SANDBOX_PASS_EPOCH_DAYS", 30, 1, 30)
    epoch_seconds = epoch_days * 86400
    epoch = int(time.time()) // epoch_seconds
    wallet = str(snapshot["wallet"])
    tier = str(snapshot["tier"])
    claim_id = hashlib.sha256(f"{wallet}:{tier}:{epoch}".encode()).hexdigest()[:24]
    asset_url = eligibility.get("sandbox_asset_url")
    issuance_enabled = os.getenv(
        "AIHF_SANDBOX_PASS_ISSUANCE_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}

    # This endpoint intentionally does not mint.  The Sandbox-native asset
    # workflow is manual/closed-beta until a supported issuer path exists.
    status = "ready_for_manual_beta" if issuance_enabled and asset_url else "dry_run"
    return {
        **eligibility,
        "claimable": bool(asset_url) and issuance_enabled,
        "status": status,
        "claim_id": claim_id,
        "epoch": epoch,
        "epoch_days": epoch_days,
        "expires_no_later_than": _utc_iso((epoch + 1) * epoch_seconds),
        "minted": False,
        "transaction_hash": None,
        "note": (
            "Dry-run only: no Sandbox NFT is minted or transferred by this API."
            if status == "dry_run"
            else "Manual closed-beta issuance is allowed only for the configured Sandbox asset."
        ),
    }
