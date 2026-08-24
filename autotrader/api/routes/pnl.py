"""PnL routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from autotrader.api.deps import get_agent

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


@router.get("/summary", summary="Total PnL + per-strategy breakdown")
def pnl_summary() -> dict:
    return get_agent()._pe.as_summary()


@router.get("/trades/recent", summary="Most recent trades across all strategies")
def recent_trades(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    trades = get_agent()._pe.recent_trades(limit=limit)
    return {"trades": trades}


@router.get("/events", summary="Risk and large-PnL event log")
def events(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    evts = get_agent()._pe.events(limit=limit)
    return {"events": evts}
