"""Coinbase-only local RiskTrader server.

This module intentionally does not import or initialize Bitvavo, Railway,
multi-exchange routing, or the general AutoTrader runtime. It is designed for
Docker Desktop on a single workstation and is expected to be bound to
127.0.0.1 only.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from autotrader.api.auth import extract_bearer, issue_jwt, valid_credential, verify_login
from autotrader.api.coinbase_dashboard_html import coinbase_dashboard_html
from autotrader.connectors.coinbase_advanced import (
    CoinbaseAdvancedMarketData,
    CoinbaseAuthenticationError,
)
from autotrader.core.coinbase_autonomous_executor import CoinbaseAutonomousExecutor
from autotrader.core.coinbase_opportunity_engine import CoinbaseOpportunityEngine
from autotrader.core.coinbase_realtime_orderflow import CoinbaseRealtimeOrderflowEngine
from autotrader.core.coinbase_zscore_shadow import CoinbaseZScoreShadowEngine
from autotrader.core.live_arm_state import LiveArmIntentStore
from autotrader.core.logger import get_logger

log = get_logger("coinbase.local")

_CONFIG_PATH = os.getenv("AUTOTRADER_CONFIG", "/app/config.coinbase.local.yaml")
_ARM_PATH = os.getenv("COINBASE_ARM_STATE_PATH", "/data/coinbase_live_arm_state.json")

app = FastAPI(
    title="Coinbase Local RiskTrader",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver"],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8787", "http://localhost:8787"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Autotrader-Token"],
)


def _load_config() -> dict[str, Any]:
    path = Path(_CONFIG_PATH)
    payload = yaml.safe_load(path.read_text("utf-8")) if path.exists() else {}
    return payload if isinstance(payload, dict) else {}


def _request_credential(request: Request) -> str | None:
    return request.headers.get("x-api-key") or extract_bearer(request.headers.get("authorization"))


def _protected_path(path: str) -> bool:
    return path.startswith("/api/") and path not in {"/api/health", "/api/auth/login"}


@app.middleware("http")
async def local_auth_middleware(request: Request, call_next):
    if _protected_path(request.url.path) and not valid_credential(_request_credential(request)):
        if not os.getenv("PUBLIC_API_KEY", "").strip() and not os.getenv("PUBLIC_JWT_SECRET", "").strip():
            return JSONResponse({"detail": "Local dashboard authentication is not configured."}, status_code=503)
        return JSONResponse({"detail": "Missing or invalid local dashboard credential."}, status_code=401)
    return await call_next(request)


def _require_control_token(value: str | None) -> None:
    expected = os.getenv("AUTOTRADER_CONTROL_TOKEN", "").strip()
    supplied = str(value or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="AUTOTRADER_CONTROL_TOKEN is not configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid control token")


def _shadow_status() -> dict[str, Any]:
    cached = getattr(app.state, "shadow_status", None)
    if isinstance(cached, dict):
        return dict(cached)
    return dict(app.state.shadow_engine.status())


def _opportunity_status() -> dict[str, Any]:
    cached = getattr(app.state, "opportunity_status", None)
    if isinstance(cached, dict):
        return dict(cached)
    return dict(app.state.opportunity_engine.status())


def _executor_readiness(*, armed: bool | None = None) -> dict[str, Any]:
    opportunity = _opportunity_status()
    value = app.state.live_armed if armed is None else bool(armed)
    return dict(app.state.executor.readiness(armed=value, shadow_status=opportunity))


def _readiness_payload() -> dict[str, Any]:
    ready = _executor_readiness()
    failed = list(ready.get("failed_gates") or [])
    ready_to_arm = all(
        bool(value)
        for key, value in (ready.get("gates") or {}).items()
        if key != "runtime_armed"
    ) and not bool(ready.get("submission_outcome_unknown"))
    return {
        "venue": "coinbase_advanced",
        "local_only": True,
        "coinbase_only": True,
        "ready_to_arm": bool(ready_to_arm),
        "execution_ready_now": bool(ready.get("ready_for_new_entry")),
        "failed_gates": failed,
        "execution_failed_gates": failed,
        "readiness": ready,
        "arm_persistence": app.state.arm_store.status(),
        "trade_permission_preview": dict(getattr(app.state, "preview_status", {"passed": False})),
    }


async def _shadow_loop() -> None:
    while True:
        try:
            status = await asyncio.to_thread(app.state.shadow_engine.tick)
            app.state.shadow_status = dict(status)
            app.state.shadow_error = None
        except Exception as exc:
            app.state.shadow_error = type(exc).__name__
            log.warning("Coinbase local shadow tick failed safely: %s", type(exc).__name__)
        await asyncio.sleep(app.state.shadow_interval)


async def _executor_loop() -> None:
    while True:
        try:
            status = await asyncio.to_thread(
                app.state.executor.tick,
                armed=bool(app.state.live_armed),
                shadow_status=_opportunity_status(),
            )
            app.state.executor_status = dict(status)
            app.state.executor_error = None
        except Exception as exc:
            app.state.executor_error = type(exc).__name__
            log.warning("Coinbase local executor tick failed safely: %s", type(exc).__name__)
        await asyncio.sleep(app.state.executor_interval)


async def _opportunity_loop() -> None:
    while True:
        try:
            status = await asyncio.to_thread(app.state.opportunity_engine.tick)
            app.state.opportunity_status = dict(status)
            app.state.opportunity_error = None
        except Exception as exc:
            app.state.opportunity_error = type(exc).__name__
            log.warning("Coinbase multi-market opportunity scan failed: %s", type(exc).__name__)
        await asyncio.sleep(app.state.opportunity_interval)


def _refresh_universe() -> dict[str, Any]:
    rows = app.state.market.list_spot_products()
    return {
        "all": len(rows),
        "tradable": sum(1 for row in rows if bool(row.get("tradable"))),
        "crypto_crypto": sum(
            1 for row in rows
            if str(row.get("quote") or "").upper() not in {"EUR", "USD", "USDC", "GBP"}
        ),
        "eur_quote": sum(1 for row in rows if str(row.get("quote") or "").upper() == "EUR"),
        "usdc_quote": sum(1 for row in rows if str(row.get("quote") or "").upper() == "USDC"),
    }


async def _universe_loop() -> None:
    while True:
        try:
            app.state.universe = await asyncio.to_thread(_refresh_universe)
            app.state.universe_error = None
        except Exception as exc:
            app.state.universe_error = type(exc).__name__
            log.warning("Coinbase local universe refresh failed: %s", type(exc).__name__)
        await asyncio.sleep(300.0)


def _refresh_preview_status() -> dict[str, Any]:
    portfolio_id = str(app.state.executor.config.portfolio_id or "").strip()
    balances = app.state.market.account_balances(portfolio_id=portfolio_id or None)
    by_asset = {
        str(row.get("currency") or "").upper(): float(row.get("available") or 0.0)
        for row in balances.get("assets", [])
        if isinstance(row, dict)
    }
    product_id = None
    quote_size = None
    if by_asset.get("EUR", 0.0) >= 1.0:
        product_id, quote_size = "BTC-EUR", "1.00"
    elif by_asset.get("USDC", 0.0) >= 1.0:
        product_id, quote_size = "BTC-USDC", "1.00"
    if not product_id:
        return {"passed": False, "reason": "no_quote_balance"}
    preview = app.state.market.preview_spot_market_order(
        product_id=product_id,
        side="BUY",
        quote_size=quote_size,
        portfolio_id=portfolio_id or None,
    )
    return {
        "passed": True,
        "product_id": product_id,
        "commission_total": preview.get("commission_total"),
        "estimated_price": preview.get("est_average_filled_price"),
    }


async def _preview_loop() -> None:
    while True:
        try:
            app.state.preview_status = await asyncio.to_thread(_refresh_preview_status)
            app.state.preview_error = None
        except Exception as exc:
            app.state.preview_status = {"passed": False, "reason": type(exc).__name__}
            app.state.preview_error = type(exc).__name__
        await asyncio.sleep(60.0)


async def _arm_recovery_loop() -> None:
    """Re-arm after temporary readiness blocks when operator intent remains live."""
    while True:
        try:
            if not bool(app.state.live_armed) and app.state.arm_store.should_resume():
                test_ready = await asyncio.to_thread(_executor_readiness, armed=True)
                failed = list(test_ready.get("failed_gates") or [])
                if not failed:
                    app.state.live_armed = True
                    log.info("Coinbase local live arm recovered after temporary readiness block")
        except Exception as exc:
            log.warning("Coinbase local arm recovery failed safely: %s", type(exc).__name__)
        await asyncio.sleep(30.0)


@app.on_event("startup")
async def startup() -> None:
    cfg = _load_config()
    shadow_cfg = dict(cfg.get("coinbase_zscore_shadow") or {})
    opportunity_cfg = dict(cfg.get("coinbase_opportunity_engine") or {})
    realtime_cfg = dict(cfg.get("coinbase_realtime_orderflow") or {})
    auto_cfg = dict(cfg.get("coinbase_autonomous_execution") or {})

    app.state.market = CoinbaseAdvancedMarketData(timeout=5.0)
    app.state.shadow_engine = CoinbaseZScoreShadowEngine(shadow_cfg)
    app.state.executor = CoinbaseAutonomousExecutor(auto_cfg)
    app.state.realtime_orderflow = CoinbaseRealtimeOrderflowEngine(realtime_cfg)
    app.state.realtime_error = None
    try:
        await asyncio.to_thread(app.state.realtime_orderflow.start)
    except Exception as exc:
        app.state.realtime_error = type(exc).__name__
        log.warning(
            "Coinbase realtime orderflow unavailable; continuing with REST fallback: %s",
            type(exc).__name__,
        )
    app.state.opportunity_engine = CoinbaseOpportunityEngine(
        opportunity_cfg,
        market_data=app.state.market,
        portfolio_id=str(app.state.executor.config.portfolio_id or ""),
        realtime_orderflow=app.state.realtime_orderflow,
    )
    app.state.shadow_interval = max(2.0, float(shadow_cfg.get("interval_seconds", 5.0)))
    app.state.opportunity_interval = max(10.0, float(opportunity_cfg.get("interval_seconds", 20.0)))
    app.state.executor_interval = max(2.0, float(auto_cfg.get("interval_seconds", 5.0)))
    app.state.shadow_status = app.state.shadow_engine.status()
    app.state.opportunity_status = app.state.opportunity_engine.status()
    app.state.executor_status = app.state.executor.status()
    app.state.shadow_error = None
    app.state.opportunity_error = None
    app.state.executor_error = None
    app.state.universe = {}
    app.state.universe_error = None
    app.state.preview_status = {"passed": False, "reason": "startup"}
    app.state.preview_error = None

    app.state.arm_store = LiveArmIntentStore(_ARM_PATH, allow_cross_release_resume=True)
    app.state.live_armed = False

    # Reconcile cash/risk persistence before evaluating persisted live intent.
    # This is state-only: no order can be placed by reconcile_runtime_state().
    try:
        await asyncio.to_thread(app.state.executor.reconcile_runtime_state)
        app.state.executor_status = app.state.executor.status()
    except Exception as exc:
        log.warning("Coinbase local startup state reconcile failed safely: %s", type(exc).__name__)

    # Fail closed unless the exact isolated portfolio is configured and authenticated.
    portfolio_id = str(app.state.executor.config.portfolio_id or "").strip()
    if not portfolio_id and app.state.executor.config.require_isolated_portfolio:
        log.warning("Coinbase local runtime starts disarmed: COINBASE_AGENT_PORTFOLIO_ID is missing")
    else:
        try:
            probe = await asyncio.to_thread(
                app.state.market.authenticated_accounts_probe,
                portfolio_id or None,
            )
            log.info(
                "Coinbase local auth: authenticated=%s portfolio_scoped=%s",
                probe.get("authenticated"),
                probe.get("portfolio_scoped"),
            )
        except Exception as exc:
            log.warning("Coinbase local auth probe failed: %s", type(exc).__name__)

    auto_arm_requested = os.getenv("COINBASE_AUTO_ARM_ON_START", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if auto_arm_requested:
        # Persist desired live intent even when a temporary gate (for example
        # the daily risk budget) prevents arming right now. The recovery loop
        # can then re-arm automatically once the gate clears. Manual Stop live
        # writes False and therefore cancels this intent.
        app.state.arm_store.write(True, source="startup_auto_arm")

    if app.state.arm_store.should_resume():
        try:
            test_ready = await asyncio.to_thread(_executor_readiness, armed=True)
            failed = list(test_ready.get("failed_gates") or [])
            if not failed:
                app.state.live_armed = True
                log.info("Coinbase local live arm enabled/restored from operator intent")
            else:
                log.warning(
                    "Coinbase local arm pending; temporary failed_gates=%s",
                    failed,
                )
        except Exception as exc:
            log.warning("Coinbase local arm restore/auto-arm failed safely: %s", type(exc).__name__)

    app.state.tasks = [
        asyncio.create_task(_shadow_loop(), name="coinbase-local-shadow"),
        asyncio.create_task(_opportunity_loop(), name="coinbase-local-opportunity"),
        asyncio.create_task(_executor_loop(), name="coinbase-local-executor"),
        asyncio.create_task(_universe_loop(), name="coinbase-local-universe"),
        asyncio.create_task(_preview_loop(), name="coinbase-local-preview"),
        asyncio.create_task(_arm_recovery_loop(), name="coinbase-local-arm-recovery"),
    ]


@app.on_event("shutdown")
async def shutdown() -> None:
    realtime = getattr(app.state, "realtime_orderflow", None)
    if realtime is not None:
        await asyncio.to_thread(realtime.close)
    for task in getattr(app.state, "tasks", []):
        task.cancel()
    for task in getattr(app.state, "tasks", []):
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "runtime": "coinbase_local",
        "coinbase_only": True,
        "live_armed": bool(getattr(app.state, "live_armed", False)),
        "shadow_error": getattr(app.state, "shadow_error", None),
        "executor_error": getattr(app.state, "executor_error", None),
        "opportunity_error": getattr(app.state, "opportunity_error", None),
        "realtime_error": getattr(app.state, "realtime_error", None),
        "daily_loss_stop": bool((getattr(app.state, "executor_status", {}) or {}).get("daily_loss_stop")),
        "drawdown_stop": bool((getattr(app.state, "executor_status", {}) or {}).get("drawdown_stop")),
        "current_drawdown_pct": (getattr(app.state, "executor_status", {}) or {}).get("current_drawdown_pct"),
        "realtime_orderflow": (
            app.state.realtime_orderflow.status()
            if getattr(app.state, "realtime_orderflow", None) is not None
            else {"enabled": False, "started": False}
        ),
    }


@app.post("/api/auth/login")
async def login(credentials: dict[str, Any] = Body(...)) -> dict[str, Any]:
    username = str(credentials.get("username") or "")
    password = str(credentials.get("password") or "")
    if not verify_login(username, password):
        raise HTTPException(status_code=401, detail="Invalid login credentials")
    try:
        token = issue_jwt(subject=username, ttl_seconds=3600)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="JWT login is not configured") from exc
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/coinbase-dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    return HTMLResponse(coinbase_dashboard_html())


@app.get("/api/coinbase/zscore-shadow")
def zscore_shadow() -> dict[str, Any]:
    return _shadow_status()


@app.get("/api/coinbase/autonomous")
def autonomous() -> dict[str, Any]:
    status = dict(getattr(app.state, "executor_status", {}) or {})
    status["coinbase_armed"] = bool(app.state.live_armed)
    status["runtime_error"] = getattr(app.state, "executor_error", None)
    # Keep dashboard portfolio figures tied to a fresh Coinbase readiness read.
    # Cached executor_status can briefly contain startup-zero balances.
    try:
        status["readiness"] = _executor_readiness(armed=bool(app.state.live_armed))
    except Exception:
        pass
    return status


@app.get("/api/coinbase/live/readiness")
def live_readiness() -> dict[str, Any]:
    return _readiness_payload()


@app.get("/api/coinbase/dashboard/snapshot")
def dashboard_snapshot() -> dict[str, Any]:
    portfolio_id = str(app.state.executor.config.portfolio_id or "").strip()
    readiness = live_readiness()
    try:
        balances = app.state.market.account_balances(portfolio_id=portfolio_id or None)
    except CoinbaseAuthenticationError as exc:
        balances = {
            "venue": "coinbase_advanced",
            "authenticated": False,
            "portfolio_scoped": bool(portfolio_id),
            "assets": [],
            "error_category": exc.category,
        }

    try:
        auth_probe = app.state.market.authenticated_accounts_probe(
            portfolio_id=portfolio_id or None
        )
    except Exception as exc:
        auth_probe = {
            "authenticated": False,
            "status": None,
            "error_category": type(exc).__name__,
            "portfolio_scoped": bool(portfolio_id),
            "portfolio_id": portfolio_id or None,
        }

    # Fail-safe dashboard fallback: if the direct balance list is temporarily
    # empty but readiness already has the isolated sleeve balances, expose those
    # instead of misleading the operator with EUR 0 / "Geen balances".
    if not list(balances.get("assets") or []):
        readiness_body = (
            readiness.get("readiness")
            if isinstance(readiness, dict) and isinstance(readiness.get("readiness"), dict)
            else readiness
        )
        rb = readiness_body.get("balances") if isinstance(readiness_body, dict) else {}
        if isinstance(rb, dict):
            fallback_assets = []
            for currency in ("EUR", "USDC", "BTC"):
                try:
                    value = float(rb.get(currency, 0.0) or 0.0)
                except (TypeError, ValueError):
                    value = 0.0
                if value > 0:
                    fallback_assets.append({
                        "currency": currency,
                        "available": str(value),
                        "hold": "0",
                        "total": str(value),
                    })
            if fallback_assets:
                balances = dict(balances)
                balances["assets"] = fallback_assets
                balances["asset_count"] = len(fallback_assets)
                balances["portfolio_scoped"] = bool(portfolio_id)
                balances["fallback_source"] = "readiness"

    return {
        "venue": "coinbase_advanced",
        "runtime": "coinbase_local",
        "local_only": True,
        "portfolio_isolated": bool(
            portfolio_id and app.state.executor.config.require_isolated_portfolio
        ),
        "balances": balances,
        "auth_probe": auth_probe,
        "autonomous": autonomous(),
        "readiness": readiness,
        "shadow": zscore_shadow(),
        "opportunity": _opportunity_status(),
        "realtime_orderflow": (
            app.state.realtime_orderflow.status()
            if getattr(app.state, "realtime_orderflow", None) is not None
            else {}
        ),
        "universe": dict(getattr(app.state, "universe", {}) or {}),
        "universe_error": getattr(app.state, "universe_error", None),
        "generated_at": time.time(),
    }


@app.post("/api/coinbase/live/activate")
def activate(
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    # This endpoint is already protected by local_auth_middleware and the
    # service is bound to 127.0.0.1 only. Do not require a second browser-side
    # secret; the authenticated dashboard session is the control boundary.
    if str(payload.get("confirmation") or "") != "I_UNDERSTAND_COINBASE_LIVE_ORDERS":
        raise HTTPException(status_code=400, detail="Explicit Coinbase live confirmation required")
    ready = _executor_readiness(armed=True)
    failed = list(ready.get("failed_gates") or [])
    if failed:
        raise HTTPException(status_code=409, detail={"message": "Coinbase live gates failed", "failed_gates": failed})
    app.state.arm_store.write(True)
    app.state.live_armed = True
    return {"armed": True, "readiness": _readiness_payload()}


@app.post("/api/coinbase/live/deactivate")
def deactivate() -> dict[str, Any]:
    # Same authenticated local-dashboard boundary as activation.
    app.state.live_armed = False
    app.state.arm_store.write(False)
    return {"armed": False, "readiness": _readiness_payload()}
