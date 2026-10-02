from autotrader.api.server import (
    _dashboard_snapshot_section,
    _execution_v2_cancel_decision,
    _execution_v2_retry_seconds,
    _readiness_log_worthy,
    _router_status_log_worthy,
)
from autotrader.connectors.bitvavo import BitvavoError
from autotrader.core.profit_optimization import ExecutionV2Advisor


def test_execution_v2_uses_long_backoff_for_signature_errors():
    advisor = ExecutionV2Advisor({
        "cancel_retry_seconds": 60,
        "auth_cancel_retry_seconds": 900,
    })
    exc = BitvavoError(
        "signature rejected",
        category="invalid_signature",
        status=403,
        error_code=309,
    )
    assert _execution_v2_retry_seconds(advisor, exc) == 900


def test_execution_v2_keeps_normal_backoff_for_transient_errors():
    advisor = ExecutionV2Advisor({
        "cancel_retry_seconds": 60,
        "auth_cancel_retry_seconds": 900,
    })
    exc = BitvavoError("network", category="network_error")
    assert _execution_v2_retry_seconds(advisor, exc) == 60


def test_router_log_debounce_ignores_one_market_flapping():
    assert _router_status_log_worthy(
        None,
        (441, 440),
        last_log_at=0,
        now_mono=100,
    ) is True
    assert _router_status_log_worthy(
        (441, 440),
        (441, 439),
        last_log_at=100,
        now_mono=110,
    ) is False
    assert _router_status_log_worthy(
        (441, 440),
        (441, 434),
        last_log_at=100,
        now_mono=110,
    ) is True
    assert _router_status_log_worthy(
        (441, 440),
        (441, 439),
        last_log_at=100,
        now_mono=401,
    ) is True


def test_readiness_log_debounce_logs_changes_and_slow_heartbeats():
    state = (True, False, (), 3, 0, True)
    assert _readiness_log_worthy(
        None,
        state,
        last_log_at=0,
        now_mono=100,
    ) is True
    assert _readiness_log_worthy(
        state,
        state,
        last_log_at=100,
        now_mono=200,
    ) is False
    assert _readiness_log_worthy(
        state,
        (True, True, (), 3, 0, True),
        last_log_at=100,
        now_mono=101,
    ) is True
    assert _readiness_log_worthy(
        state,
        state,
        last_log_at=100,
        now_mono=401,
    ) is True


def test_dashboard_snapshot_sections_fail_independently():
    ok = _dashboard_snapshot_section("ok", lambda: {"value": 7})
    assert ok == {"ok": True, "data": {"value": 7}}

    failed = _dashboard_snapshot_section("bad", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert failed["ok"] is False
    assert failed["error"] == "RuntimeError"


def _execution_advisor():
    return ExecutionV2Advisor({
        "stale_after_seconds": 180,
        "buy_stale_after_seconds": 180,
        "buy_max_order_age_seconds": 900,
        "buy_refresh_tolerance_bps": 10,
        "opportunity_switch_score_delta": 5,
        "opportunity_switch_confirm_seconds": 120,
        "sell_stale_after_seconds": 600,
        "sell_max_order_age_seconds": 1800,
        "sell_refresh_tolerance_bps": 12,
        "order_refresh_tolerance_bps": 10,
        "max_order_age_seconds": 900,
    })


def test_execution_v2_does_not_cancel_on_small_router_flap():
    decision = _execution_v2_cancel_decision(
        advisor=_execution_advisor(),
        record={"market": "DOGE-EUR", "side": "buy", "price": 0.085},
        plan_row={
            "desired_market": "WLD-EUR",
            "score_improvement": 2.0,
            "current_market_quality_ok": True,
        },
        book={"bid": 0.0852, "ask": 0.0853},
        age_seconds=300,
        desired_stable_seconds=300,
    )
    assert decision["cancel"] is False
    assert decision["reason"] == "keep_queue_position"


def test_execution_v2_requires_confirmed_materially_better_market():
    advisor = _execution_advisor()
    record = {"market": "DOGE-EUR", "side": "buy", "price": 0.085}
    plan = {
        "desired_market": "WLD-EUR",
        "score_improvement": 7.0,
        "current_market_quality_ok": True,
    }
    early = _execution_v2_cancel_decision(
        advisor=advisor,
        record=record,
        plan_row=plan,
        book={"bid": 0.0851, "ask": 0.0852},
        age_seconds=300,
        desired_stable_seconds=60,
    )
    assert early["cancel"] is False

    confirmed = _execution_v2_cancel_decision(
        advisor=advisor,
        record=record,
        plan_row=plan,
        book={"bid": 0.0851, "ask": 0.0852},
        age_seconds=300,
        desired_stable_seconds=130,
    )
    assert confirmed["cancel"] is True
    assert confirmed["reason"] == "buy_better_market_confirmed"


def test_execution_v2_reprices_stale_buy_only_after_material_price_lag():
    advisor = _execution_advisor()
    record = {"market": "DOGE-EUR", "side": "buy", "price": 0.085}
    plan = {
        "desired_market": "DOGE-EUR",
        "score_improvement": 0.0,
        "current_market_quality_ok": True,
    }
    competitive = _execution_v2_cancel_decision(
        advisor=advisor,
        record=record,
        plan_row=plan,
        book={"bid": 0.08505, "ask": 0.08510},
        age_seconds=600,
        desired_stable_seconds=600,
    )
    assert competitive["cancel"] is False

    lagging = _execution_v2_cancel_decision(
        advisor=advisor,
        record=record,
        plan_row=plan,
        book={"bid": 0.08520, "ask": 0.08525},
        age_seconds=600,
        desired_stable_seconds=600,
    )
    assert lagging["cancel"] is True
    assert lagging["reason"] == "buy_stale_price_lag"
    assert lagging["price_lag_bps"] >= 10


def test_execution_v2_keeps_competitive_profitable_sell_hanging():
    advisor = _execution_advisor()
    record = {"market": "UNI-EUR", "side": "sell", "price": 8.10}
    plan = {"desired_market": "UNI-EUR", "current_market_quality_ok": True}

    competitive = _execution_v2_cancel_decision(
        advisor=advisor,
        record=record,
        plan_row=plan,
        book={"bid": 8.09, "ask": 8.11},
        age_seconds=1200,
        desired_stable_seconds=1200,
        min_exit_price=8.00,
    )
    assert competitive["cancel"] is False
    assert competitive["reason"] == "keep_queue_position"

    lagging = _execution_v2_cancel_decision(
        advisor=advisor,
        record=record,
        plan_row=plan,
        book={"bid": 8.00, "ask": 8.04},
        age_seconds=1200,
        desired_stable_seconds=1200,
        min_exit_price=8.00,
    )
    assert lagging["cancel"] is True
    assert lagging["reason"] == "sell_stale_price_lag"

    unsafe_requote = _execution_v2_cancel_decision(
        advisor=advisor,
        record=record,
        plan_row=plan,
        book={"bid": 7.95, "ask": 7.99},
        age_seconds=2000,
        desired_stable_seconds=2000,
        min_exit_price=8.00,
    )
    assert unsafe_requote["cancel"] is False
    assert unsafe_requote["reason"] == "sell_profit_guard_holds"
