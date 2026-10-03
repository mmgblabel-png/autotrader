"""Public AIHF wallet-auth and read-only entitlement API.

These routes authenticate independently from the private AutoTrader dashboard.
No route in this module can start/stop strategies, place orders, move treasury
funds, mint AIHF, or broadcast a blockchain transaction.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from autotrader.api.auth import extract_bearer
from autotrader.ecosystem.access import (
    EcosystemAuthenticationError,
    EcosystemConfigurationError,
    EcosystemRpcError,
    EntitlementService,
    create_wallet_challenge,
    decode_ecosystem_session,
    load_access_catalog,
    load_sandbox_hq_config,
    sandbox_pass_claim,
    sandbox_pass_eligibility,
    verify_wallet_challenge,
)

router = APIRouter(prefix="/api/ecosystem", tags=["aihf-ecosystem"])
_limiter = Limiter(key_func=get_remote_address)


class WalletNonceRequest(BaseModel):
    address: str = Field(min_length=42, max_length=64)


class WalletVerifyRequest(BaseModel):
    address: str = Field(min_length=42, max_length=64)
    nonce: str = Field(min_length=12, max_length=128)
    message: str = Field(min_length=32, max_length=4096)
    signature: str = Field(min_length=64, max_length=512)


def _session(authorization: str | None) -> dict[str, Any]:
    token = extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="AIHF wallet session required")
    try:
        return decode_ecosystem_session(token)
    except EcosystemConfigurationError as exc:
        raise HTTPException(status_code=503, detail="AIHF session service is not configured") from exc
    except EcosystemAuthenticationError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired AIHF wallet session") from exc


async def _snapshot(wallet: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(EntitlementService().snapshot, wallet)
    except EcosystemConfigurationError as exc:
        raise HTTPException(status_code=503, detail="AIHF entitlement service is not configured") from exc
    except EcosystemRpcError as exc:
        raise HTTPException(status_code=503, detail="AIHF entitlement verification is temporarily unavailable") from exc
    except EcosystemAuthenticationError as exc:
        raise HTTPException(status_code=422, detail="Invalid wallet address") from exc


@router.get("/status")
def ecosystem_status() -> dict[str, Any]:
    """Public capability status without exposing secrets or contract balances."""
    import os

    try:
        config = load_sandbox_hq_config()
        land = config.get("experience", {}).get("land", {})
    except EcosystemConfigurationError:
        land = {}
    return {
        "service": "aihf-ecosystem",
        "phase": "polygon-amoy",
        "testnet_first": True,
        "live_trading_capital_connected": False,
        "wallet_auth_configured": len(os.getenv("AIHF_SESSION_SECRET", "").strip()) >= 32,
        "rpc_configured": bool(
            os.getenv("AIHF_POLYGON_RPC_URL", "").strip()
            or os.getenv("POLYGON_AMOY_RPC_URL", "").strip()
        ),
        "vault_configured": bool(os.getenv("AIHF_ACCESS_VAULT_ADDRESS", "").strip()),
        "sandbox_pass_issuance_enabled": os.getenv(
            "AIHF_SANDBOX_PASS_ISSUANCE_ENABLED", "false"
        ).strip().lower() in {"1", "true", "yes", "on"},
        "land": {
            "coordinates": land.get("coordinates"),
            "token_id": land.get("token_id"),
            "inventory_status": land.get("sandbox_inventory_status"),
        },
    }


@router.get("/catalog")
def ecosystem_catalog() -> dict[str, Any]:
    """Public, machine-readable access features and Sandbox mapping."""
    try:
        return {
            "access": load_access_catalog(),
            "sandbox_hq": load_sandbox_hq_config(),
        }
    except EcosystemConfigurationError as exc:
        raise HTTPException(status_code=503, detail="AIHF catalog is unavailable") from exc


@router.post("/auth/nonce")
@_limiter.limit("20/minute")
def wallet_nonce(request: Request, body: WalletNonceRequest) -> dict[str, Any]:
    try:
        return create_wallet_challenge(body.address)
    except EcosystemAuthenticationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/auth/verify")
@_limiter.limit("20/minute")
def wallet_verify(request: Request, body: WalletVerifyRequest) -> dict[str, Any]:
    try:
        return verify_wallet_challenge(
            address=body.address,
            nonce=body.nonce,
            message=body.message,
            signature=body.signature,
        )
    except EcosystemConfigurationError as exc:
        raise HTTPException(status_code=503, detail="AIHF wallet sessions are not configured") from exc
    except EcosystemAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/access")
async def ecosystem_access(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    session = _session(authorization)
    return await _snapshot(str(session["sub"]))


@router.get("/sandbox/pass-eligibility")
async def sandbox_eligibility(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    session = _session(authorization)
    snapshot = await _snapshot(str(session["sub"]))
    return {
        "entitlement": snapshot,
        "sandbox": sandbox_pass_eligibility(snapshot),
    }


@router.post("/sandbox/pass-claim")
@_limiter.limit("10/minute")
async def sandbox_claim(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    session = _session(authorization)
    snapshot = await _snapshot(str(session["sub"]))
    return {
        "entitlement": snapshot,
        "sandbox": sandbox_pass_claim(snapshot),
    }


@router.get("/sandbox/pass-status")
async def sandbox_status(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    session = _session(authorization)
    snapshot = await _snapshot(str(session["sub"]))
    # V1 status is deliberately derived from current entitlement. No claim is
    # represented as minted until a real Sandbox-native issuer is integrated.
    return {
        "entitlement": snapshot,
        "sandbox": sandbox_pass_claim(snapshot),
    }
