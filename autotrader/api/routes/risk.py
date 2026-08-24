"""Risk routes."""

from __future__ import annotations

from fastapi import APIRouter

from autotrader.api.deps import get_agent

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/status", summary="Per-strategy risk status (daily loss, kill-switch)")
def risk_status() -> dict:
    return get_agent().risk_manager.status()
