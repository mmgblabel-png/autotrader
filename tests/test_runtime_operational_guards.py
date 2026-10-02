from autotrader.api.server import _execution_v2_retry_seconds, _readiness_log_worthy, _router_status_log_worthy
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
