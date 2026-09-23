"""Authentication helpers for the public paper dashboard API.

Supports either a fixed API key or an HS256 JWT. Authentication is fail-closed:
protected routes return 503 when no credential is configured, rather than
silently exposing paper account data.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _configured_api_key() -> str | None:
    value = os.getenv("PUBLIC_API_KEY", "").strip()
    return value or None


def _configured_jwt_secret() -> str | None:
    value = os.getenv("PUBLIC_JWT_SECRET", "").strip()
    return value or None


def issue_jwt(subject: str = "dashboard", ttl_seconds: int = 3600) -> str:
    """Issue a minimal HS256 JWT for operators with the configured secret."""
    secret = _configured_jwt_secret()
    if not secret:
        raise RuntimeError("PUBLIC_JWT_SECRET is not configured")
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": subject, "iat": now, "exp": now + ttl_seconds}
    encoded_header = _b64(json.dumps(header, separators=(",", ":")).encode())
    encoded_payload = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = _b64(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    return f"{encoded_header}.{encoded_payload}.{signature}"


def _valid_jwt(token: str) -> bool:
    secret = _configured_jwt_secret()
    if not secret:
        return False
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        header = json.loads(_unb64(encoded_header))
        payload: dict[str, Any] = json.loads(_unb64(encoded_payload))
        if header.get("alg") != "HS256" or header.get("typ") != "JWT":
            return False
        expected = _b64(
            hmac.new(
                secret.encode(),
                f"{encoded_header}.{encoded_payload}".encode(),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(encoded_signature, expected):
            return False
        return int(payload.get("exp", 0)) > int(time.time())
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
        return False


def valid_credential(value: str | None) -> bool:
    """Validate an API key or JWT; no configured credential means fail closed."""
    if not value:
        return False
    api_key = _configured_api_key()
    if api_key and hmac.compare_digest(value, api_key):
        return True
    return _valid_jwt(value)


def extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()
