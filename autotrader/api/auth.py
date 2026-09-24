"""Fail-closed single-user authentication for the private dashboard API."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
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


def _configured_username() -> str:
    return os.getenv("DASHBOARD_USERNAME", "admin").strip()


def _password_hash(password: str, encoded: str) -> bool:
    """Verify PBKDF2-SHA256 encoded as ``pbkdf2_sha256$iterations$salt$digest``."""
    try:
        algorithm, iterations_raw, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        if not 100_000 <= iterations <= 2_000_000:
            return False
        derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
        return hmac.compare_digest(_b64(derived), digest)
    except (ValueError, TypeError, UnicodeError):
        return False


def make_password_hash(password: str, iterations: int = 310_000) -> str:
    """Create a Railway-ready password hash; store only the result in a secret."""
    if len(password) < 12:
        raise ValueError("Dashboard password must contain at least 12 characters")
    salt = _b64(secrets.token_bytes(16))
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${_b64(digest)}"


def verify_login(username: str, password: str) -> bool:
    configured = os.getenv("DASHBOARD_PASSWORD_HASH", "").strip()
    return bool(configured and hmac.compare_digest(username, _configured_username()) and _password_hash(password, configured))


def issue_jwt(subject: str = "dashboard", ttl_seconds: int = 3600) -> str:
    secret = _configured_jwt_secret()
    if not secret:
        raise RuntimeError("PUBLIC_JWT_SECRET is not configured")
    ttl_seconds = max(300, min(ttl_seconds, 86_400))
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
        expected = _b64(hmac.new(secret.encode(), f"{encoded_header}.{encoded_payload}".encode(), hashlib.sha256).digest())
        return hmac.compare_digest(encoded_signature, expected) and int(payload.get("exp", 0)) > int(time.time())
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
        return False


def valid_credential(value: str | None) -> bool:
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
    return value.strip() if scheme.lower() == "bearer" and value else None
