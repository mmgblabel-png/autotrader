"""Fund accounting, governance and investor-readiness reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class GovernancePolicy:
    withdrawals_automated: bool = False
    private_key_export_allowed: bool = False
    unknown_wallet_transfers_allowed: bool = False
    bridge_without_owner_approval: bool = False
    third_party_capital_enabled: bool = False
    operator_live_arm_required: bool = True

    def as_dict(self) -> dict[str, bool]:
        return {
            "withdrawals_automated": self.withdrawals_automated,
            "private_key_export_allowed": self.private_key_export_allowed,
            "unknown_wallet_transfers_allowed": self.unknown_wallet_transfers_allowed,
            "bridge_without_owner_approval": self.bridge_without_owner_approval,
            "third_party_capital_enabled": self.third_party_capital_enabled,
            "operator_live_arm_required": self.operator_live_arm_required,
        }


class FundReporter:
    """Build a deterministic fund-level operating and diligence snapshot."""

    def __init__(self, policy: GovernancePolicy | None = None) -> None:
        self.policy = policy or GovernancePolicy()

    def build(
        self,
        *,
        fund_id: str,
        risk: Mapping[str, object],
        growth: Mapping[str, object],
        ledger: Mapping[str, object],
        performance: Mapping[str, object],
        research: Mapping[str, object],
    ) -> dict[str, object]:
        ledger_valid = bool(ledger.get("valid"))
        nav_verified = bool(risk.get("nav_verified"))
        growth_investor_ready = bool(growth.get("investor_ready"))
        investor_diligence_ready = bool(
            growth_investor_ready
            and ledger_valid
            and nav_verified
        )

        compliance_checks = {
            "ledger_integrity": ledger_valid,
            "verified_nav": nav_verified,
            "withdrawals_disabled_by_policy": not self.policy.withdrawals_automated,
            "private_key_export_forbidden": not self.policy.private_key_export_allowed,
            "unknown_wallet_transfers_forbidden": not self.policy.unknown_wallet_transfers_allowed,
            "bridges_require_owner_approval": not self.policy.bridge_without_owner_approval,
            "third_party_capital_disabled": not self.policy.third_party_capital_enabled,
            "operator_live_arm_required": self.policy.operator_live_arm_required,
        }

        return {
            "fund_id": fund_id,
            "operating_model": {
                "research": "AI Research Department",
                "portfolio_management": "Fund Manager / Portfolio Allocation",
                "risk": "Independent deterministic risk veto",
                "execution": "Gated execution engine",
                "operations": "Reconciliation + durable event ledger",
                "accounting": "Recorded-fill net PnL accounting",
                "compliance": "Internal controls; no third-party capital acceptance",
                "investor_reporting": "Diligence snapshot only until track record is verified",
            },
            "accounting": {
                "base_currency": "EUR",
                "nav_eur": float(risk.get("nav_eur") or 0.0),
                "peak_nav_eur": float(risk.get("peak_nav_eur") or 0.0),
                "drawdown_pct": float(risk.get("drawdown_pct") or 0.0),
                **dict(performance),
            },
            "compliance": {
                "state": "INTERNAL_PERSONAL_FUND",
                "all_internal_controls_passed": all(compliance_checks.values()),
                "checks": compliance_checks,
                "policy": self.policy.as_dict(),
            },
            "research": {
                "agent_count": int(research.get("agent_count") or 0),
                "signal_coverage_pct": float(research.get("signal_coverage_pct") or 0.0),
                "healthy_signal_agent_count": int(research.get("healthy_signal_agent_count") or 0),
            },
            "investor_reporting": {
                "verified_track_record": bool(growth.get("verified_track_record")),
                "diligence_ready": investor_diligence_ready,
                "third_party_capital_acceptance_enabled": False,
                "status": (
                    "DILIGENCE_READY"
                    if investor_diligence_ready
                    else "BUILDING_VERIFIED_TRACK_RECORD"
                ),
                "requirements": {
                    "growth_gate": bool(growth.get("verified_track_record")),
                    "ledger_valid": ledger_valid,
                    "verified_nav": nav_verified,
                    "legal_and_regulatory_setup_required_before_external_capital": True,
                },
            },
        }
