"""Strategy routes – list, start, stop."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from autotrader.api.deps import get_agent

router = APIRouter(prefix="/api/strategies", tags=["strategies"])
_limiter = Limiter(key_func=get_remote_address)

_VALID_STRATEGIES = {"market_maker", "arbitrage", "grid", "sniper"}


class StrategyRequest(BaseModel):
    name: str


# ── List ────────────────────────────────────────────────────────────────────

@router.get("", summary="List all strategies and their running status")
def list_strategies() -> dict:
    agent = get_agent()
    status = agent.status()
    return {
        "strategies": [
            {"name": k, "running": v}
            for k, v in status["strategies"].items()
        ]
    }


# ── Start ────────────────────────────────────────────────────────────────────

@router.post("/start", summary="Start a strategy by name")
@_limiter.limit("10/minute")
def start_strategy(request: Request, body: StrategyRequest) -> dict:
    _validate_strategy(body.name)
    agent = get_agent()
    agent.start(body.name)
    return {"ok": True, "name": body.name, "action": "started"}


# ── Stop ─────────────────────────────────────────────────────────────────────

@router.post("/stop", summary="Stop a strategy by name")
@_limiter.limit("10/minute")
def stop_strategy(request: Request, body: StrategyRequest) -> dict:
    _validate_strategy(body.name)
    agent = get_agent()
    agent.stop(body.name)
    return {"ok": True, "name": body.name, "action": "stopped"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_strategy(name: str) -> None:
    if name not in _VALID_STRATEGIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown strategy '{name}'. Valid: {sorted(_VALID_STRATEGIES)}",
        )
