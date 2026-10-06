import time

from autotrader.api.server import (
    _dashboard_snapshot_section,
    _execution_v2_cancel_decision,
    _execution_v2_retry_seconds,
    _inventory_reconciliation_kind,
    _apply_strategy_evidence_gate,
    _readiness_log_worthy,
    _router_status_log_worthy,
    _shadow_fee_ranked_candidates,
    _symbol_scoped_balance_total,
)
from autotrader.connectors.bitvavo import BitvavoError
from autotrader.core.profit_optimization import ExecutionV2Advisor


def test_inventory_reconciliation_classifies_only_severe_unsellable_dust():
    assert _inventory_reconciliation_kind(
        exchange_total=0.0,
        journal_quantity=52.2,
        min_order_base=21.7,
        min_order_quote=5.0,
        price=0.23,
    ) == "zero"
    assert _inventory_reconciliation_kind(
        exchange_total=0.03344753,
        journal_quantity=52.20282410,
        min_order_base=21.7,
        min_order_quote=5.0,
        price=0.23,
    ) == "dust"
    # A meaningful residual inventory is not erased merely because it is
    # below the exchange minimum.
    assert _inventory_reconciliation_kind(
        exchange_total=10.0,
        journal_quantity=52.2,
        min_order_base=21.7,
        min_order_quote=5.0,
        price=0.23,
    ) is None
    # Small balance drift is preserved when it remains sellable.
    assert _inventory_reconciliation_kind(
        exchange_total=4.0,
        journal_quantity=100.0,
        min_order_base=1.0,
        min_order_quote=0.0,
        price=1.0,
    ) is None


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


def test_execution_v2_keeps_competitive_buy_during_transient_quality_failure():
    decision = _execution_v2_cancel_decision(
        advisor=_execution_advisor(),
        record={"market": "QNT-EUR", "side": "buy", "price": 220.0},
        plan_row={
            "desired_market": "IMX-EUR",
            "score_improvement": 26.0,
            "current_market_quality_ok": False,
        },
        book={"bid": 220.0, "ask": 220.2},
        age_seconds=195,
        desired_stable_seconds=15,
    )
    assert decision["price_lag_bps"] == 0.0
    assert decision["cancel"] is False
    assert decision["reason"] == "keep_queue_position"


def test_execution_v2_quality_failure_can_reprice_same_market_when_price_degrades():
    decision = _execution_v2_cancel_decision(
        advisor=_execution_advisor(),
        record={"market": "QNT-EUR", "side": "buy", "price": 220.0},
        plan_row={
            "desired_market": "QNT-EUR",
            "score_improvement": 0.0,
            "current_market_quality_ok": False,
        },
        book={"bid": 220.50, "ask": 220.70},
        age_seconds=195,
        desired_stable_seconds=15,
    )
    assert decision["cancel"] is True
    assert decision["reason"] == "buy_quality_failed_price_lag"
    assert decision["price_lag_bps"] >= 10.0


def test_execution_v2_quality_failure_does_not_switch_to_unconfirmed_market():
    decision = _execution_v2_cancel_decision(
        advisor=_execution_advisor(),
        record={"market": "QNT-EUR", "side": "buy", "price": 220.0},
        plan_row={
            "desired_market": "IMX-EUR",
            "score_improvement": 26.0,
            "current_market_quality_ok": False,
        },
        book={"bid": 220.50, "ask": 220.70},
        age_seconds=195,
        desired_stable_seconds=15,
    )
    assert decision["price_lag_bps"] >= 10.0
    assert decision["cancel"] is False
    assert decision["reason"] == "keep_queue_position"


class _EvidenceStrategy:
    def __init__(self, name):
        self.name = name
        self._config = {"_autonomous_entry_allowed": True}


class _EvidenceProfitEngine:
    def __init__(self, rows):
        self._rows = rows

    def as_summary(self):
        return {"by_strategy": self._rows}


class _EvidenceAgent:
    def __init__(self, rows, gate=None):
        self._config = {
            "live_evidence_gate": gate
            or {
                "enabled": True,
                "min_completed_exits": 4,
                "minimum_net_pnl_eur": 0.0,
            }
        }
        self._strategies = {
            "good": _EvidenceStrategy("GoodBot"),
            "bad": _EvidenceStrategy("BadBot"),
            "new": _EvidenceStrategy("NewBot"),
        }
        self.profit_engine = _EvidenceProfitEngine(rows)


def test_live_evidence_gate_blocks_only_proven_weak_entries():
    agent = _EvidenceAgent({
        "GoodBot": {"wins": 4, "losses": 1, "net_pnl": 0.25},
        "BadBot": {"wins": 1, "losses": 4, "net_pnl": -0.35},
        "NewBot": {"wins": 0, "losses": 1, "net_pnl": -0.20},
    })
    result = _apply_strategy_evidence_gate(agent)

    assert [row["strategy"] for row in result["blocked"]] == ["BadBot"]
    assert agent._strategies["bad"]._config["_evidence_entry_blocked"] is True
    assert agent._strategies["bad"]._config["_evidence_entry_reason"] == "live_evidence_gate"
    assert agent._strategies["good"]._config["_evidence_entry_blocked"] is False
    assert agent._strategies["new"]._config["_evidence_entry_blocked"] is False
    # Evidence overlay must not mutate the autonomous router decision.
    assert agent._strategies["bad"]._config["_autonomous_entry_allowed"] is True


def test_live_evidence_gate_blocks_small_net_loss_after_minimum_sample():
    agent = _EvidenceAgent({
        "GoodBot": {"wins": 2, "losses": 2, "net_pnl": -0.01},
        "BadBot": {"wins": 0, "losses": 0, "net_pnl": 0.0},
        "NewBot": {"wins": 0, "losses": 0, "net_pnl": 0.0},
    })
    result = _apply_strategy_evidence_gate(agent)

    assert [row["strategy"] for row in result["blocked"]] == ["GoodBot"]
    assert result["minimum_net_pnl_eur"] == 0.0


def test_live_evidence_gate_recovers_without_sticky_block():
    agent = _EvidenceAgent({
        "GoodBot": {"wins": 1, "losses": 4, "net_pnl": -0.35},
        "BadBot": {"wins": 0, "losses": 0, "net_pnl": 0.0},
        "NewBot": {"wins": 0, "losses": 0, "net_pnl": 0.0},
    })
    first = _apply_strategy_evidence_gate(agent)
    assert first["blocked"][0]["strategy"] == "GoodBot"
    assert agent._strategies["good"]._config["_evidence_entry_blocked"] is True

    agent.profit_engine = _EvidenceProfitEngine({
        "GoodBot": {"wins": 5, "losses": 1, "net_pnl": 0.25},
        "BadBot": {"wins": 0, "losses": 0, "net_pnl": 0.0},
        "NewBot": {"wins": 0, "losses": 0, "net_pnl": 0.0},
    })
    second = _apply_strategy_evidence_gate(agent)
    assert second["blocked"] == []
    assert agent._strategies["good"]._config["_evidence_entry_blocked"] is False
    assert agent._strategies["good"]._config["_evidence_entry_reason"] == ""
    assert agent._strategies["good"]._config["_autonomous_entry_allowed"] is True


def test_good_evidence_does_not_override_router_block():
    agent = _EvidenceAgent({
        "GoodBot": {"wins": 5, "losses": 0, "net_pnl": 1.0},
        "BadBot": {"wins": 0, "losses": 0, "net_pnl": 0.0},
        "NewBot": {"wins": 0, "losses": 0, "net_pnl": 0.0},
    })
    good = agent._strategies["good"]
    good._config["_autonomous_entry_allowed"] = False
    good._config["_autonomous_entry_reason"] = "quality_below_threshold"

    result = _apply_strategy_evidence_gate(agent)
    assert result["blocked"] == []
    assert good._config["_evidence_entry_blocked"] is False
    assert good._config["_autonomous_entry_allowed"] is False
    assert good._config["_autonomous_entry_reason"] == "quality_below_threshold"


def test_live_evidence_gate_can_be_disabled():
    agent = _EvidenceAgent(
        {"BadBot": {"wins": 0, "losses": 10, "net_pnl": -9.0}},
        gate={"enabled": False},
    )
    result = _apply_strategy_evidence_gate(agent)
    assert result["enabled"] is False
    assert result["blocked"] == []
    assert agent._strategies["bad"]._config["_evidence_entry_blocked"] is False
    assert agent._strategies["bad"]._config["_autonomous_entry_allowed"] is True


def test_shadow_candidate_ranking_prefers_economic_score_without_mutating_live_score():
    rows = [
        {"market": "AAA-EUR", "eligible": True, "score": 80.0, "economic_shadow_score": 78.0},
        {"market": "AAA-USDC", "eligible": True, "score": 80.0, "economic_shadow_score": 84.0},
        {"market": "BAD-USDC", "eligible": False, "score": 99.0, "economic_shadow_score": 99.0},
    ]
    selected = _shadow_fee_ranked_candidates(rows, 2)
    assert [row["market"] for row in selected] == ["AAA-USDC", "AAA-EUR"]
    assert rows[0]["score"] == 80.0
    assert rows[1]["score"] == 80.0


def test_symbol_scoped_balance_total_accepts_explicit_zero_row():
    assert _symbol_scoped_balance_total(
        [{"symbol": "RSR", "available": "0", "inOrder": "0"}],
        "RSR",
    ) == 0.0


def test_symbol_scoped_balance_total_treats_empty_explicit_response_as_zero():
    assert _symbol_scoped_balance_total([], "RSR") == 0.0


def test_symbol_scoped_balance_total_preserves_positive_locked_balance():
    assert _symbol_scoped_balance_total(
        [{"symbol": "RSR", "available": "0", "inOrder": "5845.4476"}],
        "RSR",
    ) == 5845.4476


def test_symbol_scoped_balance_total_fails_closed_on_mismatched_response():
    assert _symbol_scoped_balance_total(
        [{"symbol": "BTC", "available": "1", "inOrder": "0"}],
        "RSR",
    ) is None


def test_live_evidence_gate_allows_only_bounded_high_quality_recovery():
    agent = _EvidenceAgent(
        {
            "GoodBot": {"wins": 0, "losses": 0, "net_pnl": 0.0, "winrate_pct": 0.0},
            "BadBot": {"wins": 3, "losses": 1, "net_pnl": -0.20, "winrate_pct": 75.0},
            "NewBot": {"wins": 0, "losses": 0, "net_pnl": 0.0, "winrate_pct": 0.0},
        },
        gate={
            "enabled": True,
            "min_completed_exits": 4,
            "minimum_net_pnl_eur": 0.0,
            "recovery_enabled": True,
            "recovery_strategies": ["BadBot"],
            "recovery_order_eur": 5.5,
            "recovery_cooldown_seconds": 1800,
            "recovery_min_score": 92.0,
            "recovery_min_confidence": 0.75,
            "recovery_min_signal_strength": 80.0,
            "recovery_min_winrate_pct": 50.0,
            "recovery_max_net_deficit_eur": 0.50,
        },
    )
    bad = agent._strategies["bad"]
    bad._config.update(
        {
            "_autonomous_entry_allowed": True,
            "_autonomous_market_score": 94.0,
            "_autonomous_confidence": 0.82,
            "_autonomous_signal_strength": 86.0,
        }
    )

    result = _apply_strategy_evidence_gate(agent)
    row = next(row for row in result["blocked"] if row["strategy"] == "BadBot")

    assert row["blocked"] is True
    assert row["recovery_allowed"] is True
    assert row["recovery_order_eur"] == 5.5
    assert bad._config["_evidence_entry_blocked"] is True
    assert bad._config["_evidence_recovery_allowed"] is True


def test_live_evidence_recovery_never_overrides_router_or_quality():
    agent = _EvidenceAgent(
        {
            "BadBot": {"wins": 3, "losses": 1, "net_pnl": -0.20, "winrate_pct": 75.0},
        },
        gate={
            "enabled": True,
            "min_completed_exits": 4,
            "minimum_net_pnl_eur": 0.0,
            "recovery_enabled": True,
            "recovery_strategies": ["BadBot"],
            "recovery_order_eur": 5.5,
            "recovery_cooldown_seconds": 1800,
            "recovery_min_score": 92.0,
            "recovery_min_confidence": 0.75,
            "recovery_min_signal_strength": 80.0,
            "recovery_min_winrate_pct": 50.0,
            "recovery_max_net_deficit_eur": 0.50,
        },
    )
    bad = agent._strategies["bad"]
    bad._config.update(
        {
            "_autonomous_entry_allowed": False,
            "_autonomous_market_score": 99.0,
            "_autonomous_confidence": 0.99,
            "_autonomous_signal_strength": 99.0,
        }
    )
    _apply_strategy_evidence_gate(agent)
    assert bad._config["_evidence_recovery_allowed"] is False

    bad._config.update(
        {
            "_autonomous_entry_allowed": True,
            "_autonomous_market_score": 90.0,
            "_autonomous_confidence": 0.99,
            "_autonomous_signal_strength": 99.0,
        }
    )
    _apply_strategy_evidence_gate(agent)
    assert bad._config["_evidence_recovery_allowed"] is False


def test_live_evidence_recovery_cooldown_prevents_repeat_canary():
    agent = _EvidenceAgent(
        {
            "BadBot": {"wins": 3, "losses": 1, "net_pnl": -0.20, "winrate_pct": 75.0},
        },
        gate={
            "enabled": True,
            "min_completed_exits": 4,
            "minimum_net_pnl_eur": 0.0,
            "recovery_enabled": True,
            "recovery_strategies": ["BadBot"],
            "recovery_order_eur": 5.5,
            "recovery_cooldown_seconds": 1800,
            "recovery_min_score": 92.0,
            "recovery_min_confidence": 0.75,
            "recovery_min_signal_strength": 80.0,
            "recovery_min_winrate_pct": 50.0,
            "recovery_max_net_deficit_eur": 0.50,
        },
    )
    bad = agent._strategies["bad"]
    bad._config.update(
        {
            "_autonomous_entry_allowed": True,
            "_autonomous_market_score": 95.0,
            "_autonomous_confidence": 0.85,
            "_autonomous_signal_strength": 90.0,
            "_evidence_recovery_last_attempt_at": time.time(),
        }
    )

    result = _apply_strategy_evidence_gate(agent)
    row = next(row for row in result["blocked"] if row["strategy"] == "BadBot")
    assert row["recovery_allowed"] is False
    assert row["recovery_cooldown_remaining_seconds"] > 1700
