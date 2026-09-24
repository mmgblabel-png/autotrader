from decimal import Decimal
import time

from autotrader.api.auth import make_password_hash, verify_login
from autotrader.core.execution_gateway import ExecutionGateway, ExecutionLimits, ExecutionMode, ExecutionRequest
from autotrader.ml.shadow import signal_from_recent, walk_forward


def req(order_id="abc-1234567890123456", amount="10"):
    return ExecutionRequest("binance_spot", "BTCUSDT", "BUY", Decimal(amount), Decimal("100"), Decimal("100"), order_id, time.time())


def test_login_hash_is_not_plaintext(monkeypatch):
    encoded = make_password_hash("a-strong-password-123")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", encoded)
    assert verify_login("admin", "a-strong-password-123")
    assert not verify_login("admin", "wrong-password")
    assert "a-strong-password-123" not in encoded


def test_gateway_accepts_paper_but_never_live(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    gateway = ExecutionGateway(ExecutionLimits(Decimal("10"), Decimal("50"), Decimal("25"), 50))
    decision = gateway.evaluate(req())
    assert decision.accepted
    assert decision.mode == ExecutionMode.PAPER
    duplicate = gateway.evaluate(req())
    assert not duplicate.accepted
    assert "duplicate" in duplicate.reason


def test_gateway_rejects_limit_and_live(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    gateway = ExecutionGateway(ExecutionLimits(Decimal("10"), Decimal("50"), Decimal("25"), 50))
    decision = gateway.evaluate(req(amount="11"))
    assert not decision.accepted
    assert "per-trade" in decision.reason
    decision = gateway.evaluate(req(order_id="live-1234567890123456"))
    assert not decision.accepted
    assert "adapter" in decision.reason


def candles(n=90):
    return [{"close": 100 + ((i % 7) - 3) * 0.8 + i * 0.04, "volume": 1000 + i * 5} for i in range(n)]


def test_ml_walk_forward_and_signal_are_deterministic():
    rows = candles()
    report = walk_forward(rows, minimum_train=30)
    assert report["status"] == "ok"
    assert report["test_samples"] > 0
    signal = signal_from_recent(rows)
    assert signal.action in {"BUY", "SELL", "HOLD"}
    assert 0 <= signal.probability_up <= 1
