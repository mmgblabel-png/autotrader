"""Fund reporting and governance tests."""

from autotrader.fund.reporting import FundReportingService


def test_fund_report_uses_verified_track_record_and_keeps_external_capital_locked():
    report = FundReportingService.build(
        fund_status={
            "fund_id": "test-fund",
            "base_currency": "EUR",
            "risk": {
                "nav_eur": 50000.0,
                "peak_nav_eur": 51000.0,
                "drawdown_pct": 1.96,
                "daily_loss_pct": 0.1,
                "gross_exposure_eur": 12000.0,
                "gross_exposure_pct": 24.0,
                "nav_verified": True,
                "nav_source": "bitvavo_account_liquidation_nav",
                "capital_floor_armed": True,
                "protected_capital_floor_eur": 25000.0,
                "required_deleveraging_eur": 0.0,
            },
            "growth": {
                "active_stage": "institutional_personal",
                "active_stage_label": "€50.000+ / Track Record",
                "next_nav_target_eur": None,
                "policy": {"effective_live_budget_eur": 32500.0},
                "track_record": {
                    "elapsed_days": 365,
                    "observation_days": 250,
                    "completed_exits": 250,
                    "win_rate_pct": 55.0,
                    "net_realized_pnl_eur": 5000.0,
                    "profit_factor": 1.40,
                    "sharpe_ratio": 1.10,
                    "sortino_ratio": 1.50,
                    "max_drawdown_pct": 6.0,
                    "verified": True,
                },
                "governance": {
                    "ready": False,
                    "investor_outreach_ready": False,
                    "external_capital_acceptance_allowed": False,
                    "investor_capital_enabled": False,
                },
            },
            "portfolio": {
                "sector_exposure_eur": {"bitcoin": 5000.0},
                "allocation": {"targets": []},
            },
            "research": {"signal_buffer_count": 12, "blended_signals": []},
            "ledger": {
                "valid": True,
                "count": 1000,
                "head_hash": "abc",
            },
        },
        profit_summary={
            "total_pnl": 123.45,
            "total_fees": 10.0,
            "trade_count": 300,
            "by_strategy": {},
        },
        agent_status={
            "agents": {
                "risk": {"implementation": "FundRiskEngine"},
            }
        },
    )

    assert report["performance"]["realized_net_pnl_eur"] == 123.45
    assert report["performance"]["verified_live_track_record"]["verified"] is True
    assert report["accounting"]["ledger_valid"] is True
    assert report["accounting"]["paper_results_count_as_verified_track_record"] is False
    assert report["governance"]["withdrawals_by_trading_runtime_allowed"] is False
    assert report["governance"]["bridging_without_owner_authorization_allowed"] is False
    assert report["governance"]["private_key_export_allowed"] is False
    assert report["investor_reporting"]["outreach_ready"] is False
    assert report["investor_reporting"]["external_capital_acceptance_allowed"] is False


def test_fund_report_accepts_profit_engine_summary_shape():
    report = FundReportingService.build(
        fund_status={
            "risk": {},
            "growth": {"track_record": {}, "governance": {}, "policy": {}},
            "portfolio": {},
            "research": {},
            "ledger": {},
        },
        profit_summary={
            "total_pnl": -1.25,
            "total_fees": 0.75,
            "trade_count": 4,
            "by_strategy": {},
        },
    )
    assert report["performance"]["realized_net_pnl_eur"] == -1.25
