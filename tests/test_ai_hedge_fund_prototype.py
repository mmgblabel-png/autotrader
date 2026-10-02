"""AI Hedge Fund Prototype governance and research-department tests."""

from autotrader.fund.agents import AGENT_SPECS, ResearchDepartment
from autotrader.fund.engine import HedgeFundEngine
from autotrader.fund.models import AgentSignal
from autotrader.fund.reporting import FundReporter


def _config(tmp_path):
    return {
        "enabled": True,
        "fund_id": "prototype-test",
        "base_currency": "EUR",
        "initial_nav_eur": 50.0,
        "target_nav_eur": 50000.0,
        "protected_capital_floor_eur": 25000.0,
        "ledger_path": str(tmp_path / "fund.sqlite3"),
        "max_portfolio_drawdown_pct": 8.0,
        "max_daily_loss_pct": 2.0,
        "max_single_trade_pct": 20.0,
        "max_gross_exposure_pct": 85.0,
        "max_strategy_exposure_pct": 40.0,
        "max_asset_exposure_pct": 35.0,
        "min_cash_reserve_pct": 15.0,
    }


def test_research_department_contains_all_nine_institutional_agents():
    department = ResearchDepartment()
    status = department.status(now=1000.0)

    assert len(AGENT_SPECS) == 9
    assert status["agent_count"] == 9
    keys = {row["key"] for row in status["agents"]}
    assert keys == {
        "market_research",
        "trend_detection",
        "onchain_analysis",
        "whale_tracking",
        "sentiment",
        "risk",
        "portfolio_allocation",
        "execution",
        "performance_review",
    }
    assert all(row["responsibilities"] for row in status["agents"])
    assert all(row["inputs"] for row in status["agents"])
    assert all(row["outputs"] for row in status["agents"])
    assert all(row["decision_process"] for row in status["agents"])
    assert all(row["kpis"] for row in status["agents"])


def test_signal_evidence_updates_department_health():
    department = ResearchDepartment()
    department.ingest(
        AgentSignal(
            agent="trend_detection",
            strategy="Trend",
            symbol="BTC-EUR",
            direction=1.0,
            confidence=0.8,
            score=82.0,
            horizon_seconds=3600,
            timestamp=1000.0,
        )
    )
    status = department.status(now=1100.0)
    trend = next(row for row in status["agents"] if row["key"] == "trend_detection")

    assert trend["state"] == "ACTIVE"
    assert trend["signal_count"] == 1
    assert trend["mean_confidence"] == 0.8
    assert status["healthy_signal_agent_count"] == 1


def test_ledger_performance_accounting_uses_recorded_fills(tmp_path):
    fund = HedgeFundEngine(_config(tmp_path))
    fund.record_fill(
        strategy="A",
        symbol="BTC-EUR",
        side="BUY",
        notional_eur=8.0,
        realized_net_pnl_delta_eur=-0.05,
        fill_id="1",
    )
    fund.record_fill(
        strategy="A",
        symbol="BTC-EUR",
        side="SELL",
        notional_eur=8.5,
        realized_net_pnl_delta_eur=0.55,
        fill_id="2",
    )
    stats = fund.ledger.performance_stats()

    assert stats["fill_count"] == 2
    assert stats["realized_net_pnl_eur"] == 0.5
    assert stats["turnover_eur"] == 16.5
    assert stats["profitable_fill_count"] == 1
    assert stats["loss_fill_count"] == 1
    assert stats["profit_factor"] == 11.0


def test_track_record_clock_starts_at_first_fill_not_fund_boot(tmp_path):
    fund = HedgeFundEngine(_config(tmp_path))
    before = fund.ledger.track_record_stats()
    assert before["days"] == 0.0
    assert before["first_timestamp"] is None

    fund.record_fill(
        strategy="A",
        symbol="BTC-EUR",
        side="BUY",
        notional_eur=5.0,
        realized_net_pnl_delta_eur=0.0,
        fill_id="first",
    )
    after = fund.ledger.track_record_stats()
    assert after["first_timestamp"] is not None
    assert after["fill_count"] == 1


def test_fund_status_exposes_accounting_governance_and_agent_roster(tmp_path):
    fund = HedgeFundEngine(_config(tmp_path))
    fund.refresh_nav(50.0, source="bitvavo", verified=True)
    status = fund.status()

    assert status["research"]["agent_count"] == 9
    assert status["performance"]["fill_count"] == 0
    assert status["governance"]["compliance"]["state"] == "INTERNAL_PERSONAL_FUND"
    assert status["governance"]["investor_reporting"]["diligence_ready"] is False
    assert status["governance"]["investor_reporting"]["third_party_capital_acceptance_enabled"] is False


def test_governance_report_never_enables_external_capital_automatically():
    report = FundReporter().build(
        fund_id="x",
        risk={"nav_eur": 50000, "peak_nav_eur": 50000, "drawdown_pct": 0, "nav_verified": True},
        growth={"verified_track_record": True, "investor_ready": True},
        ledger={"valid": True},
        performance={"fill_count": 100},
        research={"agent_count": 9, "signal_coverage_pct": 100, "healthy_signal_agent_count": 5},
    )

    assert report["investor_reporting"]["diligence_ready"] is True
    assert report["investor_reporting"]["third_party_capital_acceptance_enabled"] is False
    assert report["compliance"]["policy"]["withdrawals_automated"] is False
    assert report["compliance"]["policy"]["private_key_export_allowed"] is False
