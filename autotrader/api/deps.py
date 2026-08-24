"""Shared application state – single AutoTrader instance for all routes."""

from __future__ import annotations

from autotrader.agent import AutoTrader

_agent: AutoTrader | None = None


def get_agent() -> AutoTrader:
    if _agent is None:
        raise RuntimeError("Agent not initialised. Call init_agent() first.")
    return _agent


def init_agent(config_path: str = "config.yaml") -> AutoTrader:
    global _agent
    _agent = AutoTrader(config_path=config_path)
    return _agent
