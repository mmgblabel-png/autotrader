"""FastAPI server – single entry point for the dashboard API.

Start with:
    uvicorn autotrader.api.server:app --host 0.0.0.0 --port 8000
or:
    python main.py --serve

Environment variables
---------------------
AUTOTRADER_CONFIG          Path to the YAML configuration (default: config.yaml).
AUTOTRADER_TICK_INTERVAL   Seconds between strategy ticks (default: 1.0, minimum: 0.1).
CORS_ORIGINS               Comma-separated allowed dashboard origins.
                           Defaults to http://localhost:3000.
AUTOTRADER_CONTROL_TOKEN   Required shared secret for strategy start/stop calls.
                           Keep this secret only in the deployment environment.
MAINNET_EXECUTION_ENABLED   Future offline-policy flag; defaults false.
MAINNET_EMERGENCY_STOP      Future offline-policy stop; defaults true.
MAINNET_MAX_TRADE_USDC      Future offline-policy per-trade cap; defaults 0.
MAINNET_MAX_DAILY_USDC      Future offline-policy daily exposure cap; defaults 0.
MAINNET_MAX_DAILY_LOSS_USDC Future offline-policy daily realized-loss cap; defaults 0.
MAINNET_MAX_SLIPPAGE_BPS    Future offline-policy slippage cap; defaults 0.
MAINNET_MAX_GAS_ETH         Future offline-policy fee cap; defaults 0.

The Mainnet settings configure only the non-executing proposal validator. They
never add a wallet, approval, signing, or broadcast capability.

This application intentionally operates in paper mode. The included strategy,
exchange, and blockchain layers are simulations/stubs and must not be presented
as live MetaMask or exchange trading.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import os
import time
from typing import Final

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from autotrader.agent import AutoTrader
from autotrader.api.auth import extract_bearer, issue_jwt, valid_credential, verify_login
from autotrader.api.deps import get_agent, init_agent
from autotrader.blockchain.mainnet_policy import MainnetExecutionPolicy
from autotrader.core.logger import get_logger
from autotrader.core.notifications import notify_paper_report
from autotrader.core.paper_reporting import build_paper_report, export_paper_report
from autotrader.core.execution_gateway import ExecutionGateway
from autotrader.core.bitvavo_security import validate_bitvavo_security
from autotrader.connectors.bitvavo import BitvavoAdapter
from autotrader.api.dashboard_html import dashboard_html
from autotrader.ml.shadow import walk_forward

log = get_logger("api.server")

_CONFIG_PATH: Final[str] = os.getenv("AUTOTRADER_CONFIG", "config.yaml")
_DEFAULT_TICK_INTERVAL: Final[float] = 1.0
_MIN_TICK_INTERVAL: Final[float] = 0.1


def _cors_origins() -> list[str]:
    """Return non-empty, whitespace-normalised CORS origins."""
    raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    return origins or ["http://localhost:3000"]


def _tick_interval() -> float:
    """Read a safe API tick interval without letting invalid env input crash startup."""
    raw_value = os.getenv("AUTOTRADER_TICK_INTERVAL", str(_DEFAULT_TICK_INTERVAL))
    try:
        value = float(raw_value)
    except ValueError:
        log.warning(
            "Invalid AUTOTRADER_TICK_INTERVAL=%r; using %.1f seconds.",
            raw_value,
            _DEFAULT_TICK_INTERVAL,
        )
        return _DEFAULT_TICK_INTERVAL

    if value < _MIN_TICK_INTERVAL:
        log.warning(
            "AUTOTRADER_TICK_INTERVAL=%s is below the %.1f-second minimum; clamping it.",
            value,
            _MIN_TICK_INTERVAL,
        )
        return _MIN_TICK_INTERVAL
    return value


def _paper_report(agent: AutoTrader) -> dict:
    """Return the dashboard-ready paper report and track process-local equity peak."""
    summary = agent.profit_engine.as_summary()
    current = float(os.getenv("PAPER_STARTING_BALANCE_USD", "1000")) + float(summary.get("total_pnl", 0.0))
    peak = max(float(getattr(app.state, "peak_equity_usd", current)), current)
    app.state.peak_equity_usd = peak
    return build_paper_report(summary, peak_equity_usd=peak)


def _require_control_token(
    x_autotrader_token: str | None = Header(default=None),
) -> None:
    """Protect strategy control from unauthenticated public requests."""
    expected = os.getenv("AUTOTRADER_CONTROL_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Strategy controls are disabled until AUTOTRADER_CONTROL_TOKEN is set.",
        )
    if not x_autotrader_token or not hmac.compare_digest(x_autotrader_token, expected):
        raise HTTPException(status_code=401, detail="Invalid strategy-control token.")


async def _tick_loop(app: FastAPI, agent: AutoTrader) -> None:
    """Drive all active strategies for the lifetime of the API process.

    The previous Railway entry point only exposed control endpoints. A strategy
    could be marked running, but nothing ever called ``tick_all``. This task
    keeps the API responsive while advancing the in-process paper strategies.
    """
    while True:
        try:
            agent.tick_all()
            app.state.tick_count += 1
            app.state.last_tick_at = time.time()
            app.state.last_tick_error = None
        except Exception as exc:  # pragma: no cover - defensive production guard
            app.state.last_tick_error = str(exc)
            log.exception("Strategy tick failed; the loop will continue.")
        await asyncio.sleep(app.state.tick_interval_seconds)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialise the agent, run its tick task, then stop it cleanly."""
    agent = init_agent(_CONFIG_PATH)
    app.state.tick_interval_seconds = _tick_interval()
    app.state.tick_count = 0
    app.state.last_tick_at = None
    app.state.last_tick_error = None
    app.state.peak_equity_usd = float(os.getenv("PAPER_STARTING_BALANCE_USD", "1000"))
    app.state.tick_task = asyncio.create_task(
        _tick_loop(app, agent), name="autotrader-paper-tick-loop"
    )
    log.info(
        "AutoTrader paper-mode agent initialised from '%s' (tick interval %.3fs).",
        _CONFIG_PATH,
        app.state.tick_interval_seconds,
    )

    try:
        yield
    finally:
        log.info("Shutting down AutoTrader paper-mode agent…")
        app.state.tick_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.tick_task
        agent.stop()
        log.info("AutoTrader agent stopped.")


app = FastAPI(
    title="AutoTrader API",
    version="1.1.0",
    lifespan=_lifespan,
)

app.state.execution_gateway = ExecutionGateway()


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    """Serve the visual protected dashboard shell; data remains API-authenticated."""
    return HTMLResponse(dashboard_html())


def _protected_path(path: str) -> bool:
    """Protect dashboard data while keeping Railway's healthcheck public."""
    return (path.startswith("/api/") and path not in {"/api/health", "/api/auth/login"}) or path.startswith("/strategies/")


def _request_credential(request: Request) -> str | None:
    return request.headers.get("x-api-key") or extract_bearer(request.headers.get("authorization"))


@app.middleware("http")
async def public_auth_middleware(request: Request, call_next):
    """Require API-key or JWT credentials on public dashboard routes."""
    if _protected_path(request.url.path) and not valid_credential(_request_credential(request)):
        if not os.getenv("PUBLIC_API_KEY", "").strip() and not os.getenv("PUBLIC_JWT_SECRET", "").strip():
            return JSONResponse({"detail": "Dashboard authentication is not configured."}, status_code=503)
        return JSONResponse({"detail": "Missing or invalid dashboard credential."}, status_code=401)
    return await call_next(request)

# ── Rate limiting ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.post("/api/auth/login", tags=["auth"])
@limiter.limit("5/minute")
async def login(request: Request, credentials: dict = Body(...)):
    """Issue a short-lived JWT for the configured single dashboard user."""
    username = str(credentials.get("username", ""))
    password = str(credentials.get("password", ""))
    if not verify_login(username, password):
        raise HTTPException(status_code=401, detail="Invalid login credentials")
    try:
        token = issue_jwt(subject=username, ttl_seconds=3600)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="JWT login is not configured") from exc
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}

# ── CORS ──────────────────────────────────────────────────────────────────────
# Never use "*" with allow_credentials=True; browsers reject that combination.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── PnL & trades ──────────────────────────────────────────────────────────────

@app.get("/api/pnl/summary", tags=["pnl"])
def pnl_summary():
    """Return the paper PnL summary in the hosted dashboard's expected shape."""
    agent = get_agent()
    summary = agent.profit_engine.as_summary()
    states = agent.list_strategies()
    by_strategy = summary["by_strategy"]

    # The first dashboard build expected an array here, while the original API
    # returned a mapping. Keep the mapping under an explicit name and expose an
    # array for the dashboard so it can render every configured paper strategy.
    rows = []
    for name, state in states.items():
        display_name = _STRATEGY_DISPLAY_NAMES[name]
        stats = by_strategy.get(display_name, {})
        rows.append(
            {
                "name": name,
                "status": "running" if state["running"] else "stopped",
                "cost": 0.0,
                "pnl24h": stats.get("net_pnl", 0.0),
                "pnl7d": stats.get("net_pnl", 0.0),
                "pnlAllTime": stats.get("net_pnl", 0.0),
                "tradesToday": stats.get("num_trades", 0),
                "config": {},
                "pnlSeries": [],
            }
        )

    return {
        **summary,
        "paper_report": _paper_report(agent),
        "pnl_by_strategy": summary["pnl_per_strategy"],
        "pnl_per_strategy": rows,
        "mode": "paper",
    }


@app.get("/api/paper/report", tags=["pnl"])
def paper_report():
    """Return paper PnL in USD/EUR/BTC, PnL percentage and drawdown."""
    return _paper_report(get_agent())


@app.post("/api/paper/export", tags=["pnl"])
def paper_export():
    """Export paper PnL JSON/CSV; no live orders or credentials are involved."""
    report = _paper_report(get_agent())
    json_path, csv_path = export_paper_report(report)
    notifications = notify_paper_report(report)
    return {"mode": "paper", "json": json_path, "csv": csv_path, "notifications": notifications}


@app.websocket("/ws/paper")
async def paper_websocket(websocket: WebSocket):
    """Push the paper report every two seconds for a private dashboard client."""
    credential = websocket.headers.get("x-api-key") or extract_bearer(
        websocket.headers.get("authorization")
    ) or websocket.query_params.get("api_key") or websocket.query_params.get("access_token")
    if not valid_credential(credential):
        await websocket.close(code=1008, reason="Missing or invalid dashboard credential")
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_paper_report(get_agent()))
            await asyncio.sleep(2)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return


@app.get("/api/trades/recent", tags=["pnl"])
def recent_trades(limit: int = Query(default=50, ge=1, le=200)):
    """Return between 1 and 200 most recent simulated trades."""
    return {"trades": get_agent().profit_engine.last_trades(limit)}


@app.get("/api/pnl/events", tags=["pnl"])
def pnl_events(limit: int = Query(default=100, ge=1, le=200)):
    """Return between 1 and 200 risk events and large PnL movements."""
    return {"events": get_agent().profit_engine.events(limit)}


@app.get("/api/events", tags=["pnl"])
def events(limit: int = Query(default=100, ge=1, le=200)):
    """Compatibility route returning the event list required by the dashboard."""
    return get_agent().profit_engine.events(limit)


@app.get("/api/pnl/history", tags=["pnl"])
def pnl_history():
    """Compatibility route for the dashboard's chart history request.

    The current paper engine tracks aggregate PnL but not time-series snapshots,
    so this explicitly returns an empty history instead of fabricating market data.
    """
    return {"history": []}


@app.get("/api/wallet/credits", tags=["wallet"])
def wallet_credits():
    """Return zero application credits; never infer a wallet balance from an address."""
    return {"credits": 0, "mode": "paper"}


# ── Risk status ───────────────────────────────────────────────────────────────

@app.get("/api/risk/status", tags=["risk"])
def risk_status():
    """Risk status: daily PnL, limits, kill-switches, and open positions."""
    status = get_agent().risk_manager.status()
    status["slippage_alerts"] = []
    status["mode"] = "paper"
    return status


@app.get("/api/execution/status", tags=["execution"])
def execution_status():
    """Expose non-secret execution mode and limits for the dashboard."""
    return app.state.execution_gateway.status()


@app.post("/api/ml/walk-forward", tags=["ml"])
def ml_walk_forward(rows: list[dict] = Body(...)):
    """Evaluate the standard-library shadow model; never places an order."""
    return walk_forward(rows)


# ── Strategy list & control ───────────────────────────────────────────────────

@app.get("/api/strategies", tags=["strategies"])
def strategies():
    """List all strategies with their running status."""
    strats = get_agent().list_strategies()
    return {
        "strategies": [
            {"name": key, "running": value["running"]}
            for key, value in strats.items()
        ]
    }


@app.get("/strategies/status", tags=["strategies"])
@app.get("/api/strategies/status", tags=["strategies"])
def strategies_status():
    """Compatibility status shape for simple dashboards and deployment checks."""
    names = {
        "market_maker": "MarketMaker",
        "arbitrage": "ArbitrageHunter",
        "grid": "GridRunner",
        "sniper": "SniperBot",
    }
    active = get_agent().list_strategies()
    return {
        "running": {
            display_name: active.get(key, {"running": False})["running"]
            for key, display_name in names.items()
        }
    }


@app.post("/api/strategies/start", tags=["strategies"])
def start_strategy(
    name: str = Body(..., embed=True),
    _: None = Depends(_require_control_token),
):
    """Start a paper strategy. Body: ``{\"name\": \"market_maker\"}``."""
    _validate(name)
    return get_agent().start(name)


@app.post("/api/strategies/stop", tags=["strategies"])
def stop_strategy(
    name: str = Body(..., embed=True),
    _: None = Depends(_require_control_token),
):
    """Stop a paper strategy. Body: ``{\"name\": \"market_maker\"}``."""
    _validate(name)
    return get_agent().stop(name)


# ── Base Mainnet readiness (non-executing) ────────────────────────────────────

@app.get("/api/mainnet/safety", tags=["mainnet"])
def mainnet_safety():
    """Expose the active, non-secret policy state without enabling execution.

    The policy is loaded server-side from the Railway environment on each
    request. It exposes only configuration state and always states that signing,
    approvals, and broadcasting are not implemented in this application.
    """
    policy = MainnetExecutionPolicy.from_environment()
    return {
        **policy.status(),
        "mode": "paper",
        "wallet_capability": "not_implemented",
        "approval_capability": "not_implemented",
        "broadcast_capability": "not_implemented",
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["health"])
@app.get("/", tags=["health"])
def health():
    """Liveness and paper-runtime status for Railway and dashboard checks."""
    task = getattr(app.state, "tick_task", None)
    return {
        "status": "ok",
        "service": "AutoTrader API",
        "mode": "paper",
        "runtime": {
            "ticker_running": bool(task and not task.done()),
            "tick_interval_seconds": getattr(app.state, "tick_interval_seconds", None),
            "tick_count": getattr(app.state, "tick_count", 0),
            "last_tick_at": getattr(app.state, "last_tick_at", None),
            "last_tick_error": getattr(app.state, "last_tick_error", None),
        },
    }


@app.get("/api/security/bitvavo", tags=["security"])
def bitvavo_security_status() -> dict[str, object]:
    """Run the fail-closed Bitvavo security gate inside the Railway container.

    This endpoint is behind the normal dashboard authentication middleware and
    returns only the redacted gate report; API credentials are never returned
    or logged. It exists because Railway's interactive console may suppress
    child-process stdout.
    """
    report = validate_bitvavo_security(BitvavoAdapter())
    return report


# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID: Final[set[str]] = {"market_maker", "arbitrage", "grid", "sniper"}
_STRATEGY_DISPLAY_NAMES: Final[dict[str, str]] = {
    "market_maker": "MarketMaker",
    "arbitrage": "ArbitrageHunter",
    "grid": "GridRunner",
    "sniper": "SniperBot",
}


def _validate(name: str) -> None:
    if name not in _VALID:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown strategy '{name}'. Valid: {sorted(_VALID)}",
        )


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("autotrader.api.server:app", host="0.0.0.0", port=8000, reload=True)
