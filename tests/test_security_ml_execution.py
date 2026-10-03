from decimal import Decimal
import time

from autotrader.api.auth import make_password_hash, verify_login
from autotrader.core.execution_gateway import ExecutionGateway, ExecutionLimits, ExecutionMode, ExecutionRequest
from autotrader.ml.shadow import signal_from_recent, walk_forward, lookahead_analysis, recursive_analysis


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
    assert "armed" in decision.reason

    decision = gateway.evaluate(req(order_id="gates-1234567890123456"), armed=True)
    assert not decision.accepted
    assert "gates" in decision.reason


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


def test_gateway_allows_favorable_passive_limit_prices(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    limits = ExecutionLimits(Decimal("10"), Decimal("50"), Decimal("25"), 50)

    sell_gateway = ExecutionGateway(limits)
    sell = ExecutionRequest(
        "bitvavo", "BTC-EUR", "SELL", Decimal("7.5"),
        Decimal("74289.60"), Decimal("73476.00"),
        "sell-favorable-123456789", time.time(),
    )
    assert sell_gateway.evaluate(sell).accepted

    buy_gateway = ExecutionGateway(limits)
    buy = ExecutionRequest(
        "bitvavo", "BTC-EUR", "BUY", Decimal("7.5"),
        Decimal("73000.00"), Decimal("73476.00"),
        "buy-favorable-1234567890", time.time(),
    )
    assert buy_gateway.evaluate(buy).accepted


def test_gateway_rejects_only_adverse_slippage(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    limits = ExecutionLimits(Decimal("10"), Decimal("50"), Decimal("25"), 50)

    buy_gateway = ExecutionGateway(limits)
    bad_buy = ExecutionRequest(
        "bitvavo", "BTC-EUR", "BUY", Decimal("7.5"),
        Decimal("74250.00"), Decimal("73476.00"),
        "buy-adverse-123456789012", time.time(),
    )
    assert not buy_gateway.evaluate(bad_buy).accepted

    sell_gateway = ExecutionGateway(limits)
    bad_sell = ExecutionRequest(
        "bitvavo", "BTC-EUR", "SELL", Decimal("7.5"),
        Decimal("72700.00"), Decimal("73476.00"),
        "sell-adverse-12345678901", time.time(),
    )
    assert not sell_gateway.evaluate(bad_sell).accepted


def test_gateway_reports_central_remaining_exposure(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    gateway = ExecutionGateway(ExecutionLimits(Decimal("10"), Decimal("50"), Decimal("25"), 50))
    gateway.restore_daily_state(exposure_eur=Decimal("38"))
    remaining = gateway.remaining_daily_exposure_eur(
        pending_reservation_eur=Decimal("7"),
        safety_buffer_eur=Decimal("0.25"),
    )
    assert remaining == Decimal("4.75")
    assert gateway.status()["remaining_daily_exposure_eur"] == "12"


def test_shadow_lookahead_and_recursive_validation_are_non_trading():
    rows = candles(100)
    lookahead = lookahead_analysis(rows, minimum_prefix=24)
    recursive = recursive_analysis(rows, windows=(20, 30, 50, 80))
    assert lookahead["mismatches"] == 0
    assert lookahead["has_lookahead_warning"] is False
    assert recursive["status"] == "ok"
    assert len(recursive["windows"]) >= 3
    assert 0 <= recursive["action_agreement_pct"] <= 100


def test_gateway_daily_loss_uses_net_fee_aware_pnl(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    gateway = ExecutionGateway(ExecutionLimits(
        Decimal("10"), Decimal("50"), Decimal("0.25"), 50
    ))
    gateway.record_pnl_delta(Decimal("-0.10"))
    gateway.record_pnl_delta(Decimal("0.08"))
    assert gateway.status()["daily_realized_pnl_eur"] == "-0.02"
    assert gateway.status()["daily_loss_eur"] == "0.02"

    gateway.record_pnl_delta(Decimal("-0.24"))
    assert gateway.status()["daily_realized_pnl_eur"] == "-0.26"
    assert gateway.status()["daily_loss_eur"] == "0.26"


def test_gateway_scales_eur_caps_from_verified_nav_percentage_mandate(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    gateway = ExecutionGateway(
        ExecutionLimits(Decimal("10"), Decimal("50"), Decimal("25"), 50)
    )

    assert gateway.set_verified_nav_limits(
        nav_eur=80,
        max_trade_pct=16,
        max_exposure_pct=65,
        max_daily_loss_pct=3,
    ) is True
    assert gateway.limits.max_trade_eur == Decimal("12.8")
    assert gateway.limits.max_daily_exposure_eur == Decimal("52")
    assert gateway.limits.max_daily_loss_eur == Decimal("2.4")
    assert gateway.limits.max_slippage_bps == 50

    assert gateway.set_verified_nav_limits(
        nav_eur=250,
        max_trade_pct=14,
        max_exposure_pct=68,
        max_daily_loss_pct=3,
    ) is True
    assert gateway.limits.max_trade_eur == Decimal("35")
    assert gateway.limits.max_daily_exposure_eur == Decimal("170")
    assert gateway.limits.max_daily_loss_eur == Decimal("7.5")


def test_gateway_rejects_invalid_dynamic_capital_snapshot(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    original = ExecutionLimits(Decimal("10"), Decimal("50"), Decimal("25"), 50)
    gateway = ExecutionGateway(original)

    assert gateway.set_verified_nav_limits(
        nav_eur=0,
        max_trade_pct=16,
        max_exposure_pct=65,
        max_daily_loss_pct=3,
    ) is False
    assert gateway.limits == original
