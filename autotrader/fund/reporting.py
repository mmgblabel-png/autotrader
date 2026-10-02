"""Fund-level operating, accounting and investor-readiness reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


class FundReportingService:
    """Build audit-friendly fund reports from existing verified state."""

    @staticmethod
    def build(
        *,
        fund_status: Mapping[str, Any],
        profit_summary: Mapping[str, Any] | None = None,
        agent_status: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        risk = dict(fund_status.get("risk") or {})
        growth = dict(fund_status.get("growth") or {})
        track = dict(growth.get("track_record") or {})
        governance = dict(growth.get("governance") or {})
        portfolio = dict(fund_status.get("portfolio") or {})
        ledger = dict(fund_status.get("ledger") or {})
        research = dict(fund_status.get("research") or {})
        profit = dict(profit_summary or {})
        totals = dict(profit.get("totals") or {})
        agents = dict((agent_status or {}).get("agents") or {})

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_type": "internal_fund_operating_report",
            "fund": {
                "fund_id": fund_status.get("fund_id"),
                "base_currency": fund_status.get("base_currency", "EUR"),
                "nav_eur": risk.get("nav_eur"),
                "peak_nav_eur": risk.get("peak_nav_eur"),
                "drawdown_pct": risk.get("drawdown_pct"),
                "growth_stage": growth.get("active_stage"),
                "growth_stage_label": growth.get("active_stage_label"),
                "next_nav_target_eur": growth.get("next_nav_target_eur"),
                "nav_verified": risk.get("nav_verified"),
                "nav_source": risk.get("nav_source"),
            },
            "performance": {
                "realized_net_pnl_eur": totals.get(
                    "realized_net_pnl_eur",
                    track.get("net_realized_pnl_eur"),
                ),
                "economic_pnl_eur": totals.get("economic_pnl_eur"),
                "verified_live_track_record": {
                    "elapsed_days": track.get("elapsed_days", 0),
                    "observation_days": track.get("observation_days", 0),
                    "completed_exits": track.get("completed_exits", 0),
                    "win_rate_pct": track.get("win_rate_pct", 0.0),
                    "profit_factor": track.get("profit_factor"),
                    "sharpe_ratio": track.get("sharpe_ratio"),
                    "sortino_ratio": track.get("sortino_ratio"),
                    "max_drawdown_pct": track.get("max_drawdown_pct", 0.0),
                    "verified": track.get("verified", False),
                },
            },
            "risk": {
                "daily_loss_pct": risk.get("daily_loss_pct"),
                "gross_exposure_eur": risk.get("gross_exposure_eur"),
                "gross_exposure_pct": risk.get("gross_exposure_pct"),
                "capital_floor_armed": risk.get("capital_floor_armed"),
                "protected_capital_floor_eur": risk.get(
                    "protected_capital_floor_eur"
                ),
                "required_deleveraging_eur": risk.get(
                    "required_deleveraging_eur"
                ),
                "stage_policy": growth.get("policy", {}),
            },
            "portfolio": {
                "sector_exposure_eur": portfolio.get(
                    "sector_exposure_eur", {}
                ),
                "target_allocation": portfolio.get("allocation", {}),
            },
            "research": {
                "signal_buffer_count": research.get("signal_buffer_count", 0),
                "blended_signals": research.get("blended_signals", []),
                "agents": agents,
            },
            "accounting": {
                "ledger_valid": ledger.get("valid", False),
                "ledger_event_count": ledger.get("count", 0),
                "ledger_head_hash": ledger.get("head_hash"),
                "nav_provenance_required": True,
                "paper_results_count_as_verified_track_record": False,
            },
            "governance": {
                **governance,
                "withdrawals_by_trading_runtime_allowed": False,
                "bridging_without_owner_authorization_allowed": False,
                "private_key_export_allowed": False,
            },
            "investor_reporting": {
                "track_record_verified": track.get("verified", False),
                "outreach_ready": governance.get(
                    "investor_outreach_ready", False
                ),
                "external_capital_acceptance_allowed": governance.get(
                    "external_capital_acceptance_allowed", False
                ),
                "statement": (
                    "External capital is locked until verified performance and "
                    "legal/compliance/accounting/audit gates are all satisfied."
                ),
            },
        }
