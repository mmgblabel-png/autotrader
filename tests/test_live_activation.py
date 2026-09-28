import os

from autotrader.core.execution_gateway import ExecutionGateway, ExecutionRequest
from decimal import Decimal


def test_live_gateway_requires_runtime_arm(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("LIVE_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("LIVE_EXECUTION_ADAPTER_INSTALLED", "true")
    monkeypatch.setenv("EMERGENCY_STOP", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDERS")
    monkeypatch.setenv("BITVAVO_LIVE_TRADING", "true")
    req=ExecutionRequest("bitvavo","BTC-EUR","BUY",Decimal("5"),Decimal("100"),Decimal("100"),"550e8400-e29b-41d4-a716-446655440000",__import__("time").time())
    gateway=ExecutionGateway()
    assert not gateway.evaluate(req, armed=False).accepted
    assert gateway.evaluate(req, armed=True).accepted
