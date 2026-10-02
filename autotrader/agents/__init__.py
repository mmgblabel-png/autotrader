"""Specialized research agents for the AutoTrader hedge-fund control plane."""

from autotrader.agents.research import (
    MarketResearchAgent,
    OnChainAnalysisAgent,
    ResearchAgentSuite,
    SentimentAgent,
    TrendDetectionAgent,
    WhaleTrackingAgent,
)

__all__ = [
    "MarketResearchAgent",
    "TrendDetectionAgent",
    "OnChainAnalysisAgent",
    "WhaleTrackingAgent",
    "SentimentAgent",
    "ResearchAgentSuite",
]
