"""FastAPI server – single entry point for the dashboard API.

Start with:
    uvicorn autotrader.api.server:app --host 0.0.0.0 --port 8000
or:
    python main.py --serve
"""

from __future__ import annotations

import contextlib
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from autotrader.api.deps import init_agent
from autotrader.api.routes import pnl, risk, strategies
from autotrader.core.logger import get_logger

log = get_logger("api.server")

_CONFIG_PATH = os.getenv("AUTOTRADER_CONFIG", "config.yaml")


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
    description="Dashboard backend for the AutoTrader automated trading agent.",
    version="0.1.0",
    lifespan=_lifespan,
)

# ── CORS (adjust origins for production) ────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(strategies.router)
app.include_router(pnl.router)
app.include_router(risk.router)


@app.get("/", tags=["health"])
def health() -> dict:
    return {"status": "ok", "service": "AutoTrader API"}


@app.get("/api/trades/recent", tags=["pnl"], include_in_schema=False)
def recent_trades_alias(limit: int = 50):
    """Convenience alias kept for dashboard compatibility."""
    from autotrader.api.routes.pnl import recent_trades
    from fastapi import Query
    return recent_trades(limit=limit)
