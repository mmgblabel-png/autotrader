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

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from autotrader.agent import AutoTrader
from autotrader.api.deps import get_agent, init_agent
from autotrader.core.logger import get_logger

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

# ── Rate limiting ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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
        "pnl_by_strategy": summary["pnl_per_strategy"],
        "pnl_per_strategy": rows,
        "mode": "paper",
    }


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
