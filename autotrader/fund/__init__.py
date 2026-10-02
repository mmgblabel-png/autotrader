"""Institutional-style fund orchestration for AutoTrader."""

from autotrader.fund.agents import AGENT_SPECS, AgentSpec, ResearchDepartment
from autotrader.fund.engine import HedgeFundEngine
from autotrader.fund.growth import FundGrowthController, GrowthStage
from autotrader.fund.models import AgentSignal, BlendedSignal, FundMandate, RiskDecision
from autotrader.fund.reporting import FundReporter, GovernancePolicy

__all__ = [
    "AGENT_SPECS",
    "AgentSignal",
    "AgentSpec",
    "BlendedSignal",
    "FundGrowthController",
    "FundMandate",
    "GrowthStage",
    "HedgeFundEngine",
    "FundReporter",
    "GovernancePolicy",
    "ResearchDepartment",
    "RiskDecision",
]
