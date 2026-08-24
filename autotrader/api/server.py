"""FastAPI server – single entry point for the dashboard API.

Start with:
    uvicorn autotrader.api.server:app --host 0.0.0.0 --port 8000
or:
    python main.py --serve

Environment variables
---------------------
AUTOTRADER_CONFIG   path to config YAML (default: config.yaml)
CORS_ORIGINS        comma-separated allowed origins
                    (default: http://localhost:3000 – set to your dashboard URL in production)
"""

from __future__ import annotations

import contextlib
import os

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from autotrader.api.deps import get_agent, init_agent
from autotrader.core.logger import get_logger

log = get_logger("api.server")

_CONFIG_PATH = os.getenv("AUTOTRADER_CONFIG", "config.yaml")

# CORS: default to localhost dev server; set CORS_ORIGINS in production.
# Do NOT use "*" with allow_credentials=True – browsers will reject it.
_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

# ── Rate limiter (must be attached to app.state.limiter) ─────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialise the agent on startup; stop it cleanly on shutdown."""
    agent = init_agent(_CONFIG_PATH)
    log.info("AutoTrader agent initialised from '%s'.", _CONFIG_PATH)
    yield
    log.info("Shutting down AutoTrader agent…")
    agent.stop()
    log.info("AutoTrader agent stopped.")


app = FastAPI(
    title="AutoTrader API",
    version="1.0.0",
    lifespan=_lifespan,
)

# Attach limiter to app state so SlowAPIMiddleware can find it
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── PnL & trades ─────────────────────────────────────────────────────────────

@app.get("/api/pnl/summary", tags=["pnl"])
def pnl_summary():
    """Total PnL + PnL per strategy + trade count."""
    return get_agent().profit_engine.as_summary()


@app.get("/api/trades/recent", tags=["pnl"])
def recent_trades(limit: int = 50):
    """Most recent trades, default 50."""
    return {"trades": get_agent().profit_engine.last_trades(limit)}


@app.get("/api/pnl/events", tags=["pnl"])
def pnl_events(limit: int = 100):
    """Risk events and large PnL movements."""
    return {"events": get_agent().profit_engine.events(limit)}


# ── Risk status ───────────────────────────────────────────────────────────────

@app.get("/api/risk/status", tags=["risk"])
def risk_status():
    """Risk status: daily PnL, max daily loss, kill-switch, open positions."""
    return get_agent().risk_manager.status()


# ── Strategy list & control ───────────────────────────────────────────────────

@app.get("/api/strategies", tags=["strategies"])
def strategies():
    """List all strategies with their running status."""
    strats = get_agent().list_strategies()
    return {
        "strategies": [
            {"name": k, "running": v["running"]}
            for k, v in strats.items()
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
    return {
        "running": {
            display_name: state["running"]
            for key, display_name in names.items()
            for state in [get_agent().list_strategies().get(key, {"running": False})]
        }
    }


@app.post("/api/strategies/start", tags=["strategies"])
def start_strategy(name: str = Body(..., embed=True)):
    """Start a strategy by name. Body: { "name": "market_maker" }"""
    _validate(name)
    return get_agent().start(name)


@app.post("/api/strategies/stop", tags=["strategies"])
def stop_strategy(name: str = Body(..., embed=True)):
    """Stop a strategy by name. Body: { "name": "market_maker" }"""
    _validate(name)
    return get_agent().stop(name)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["health"])
@app.get("/", tags=["health"])
def health():
    return {"status": "ok", "service": "AutoTrader API"}


# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID = {"market_maker", "arbitrage", "grid", "sniper"}


def _validate(name: str) -> None:
    from fastapi import HTTPException
    if name not in _VALID:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown strategy '{name}'. Valid: {sorted(_VALID)}",
        )


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("autotrader.api.server:app", host="0.0.0.0", port=8000, reload=True)
