"""Institutional research-department contracts and runtime health for Fund Core."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import time
from typing import Iterable

from autotrader.fund.models import AgentSignal


@dataclass(frozen=True)
class AgentSpec:
    key: str
    label: str
    responsibilities: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    decision_process: tuple[str, ...]
    kpis: tuple[str, ...]
    signal_expected: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "responsibilities": list(self.responsibilities),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "decision_process": list(self.decision_process),
            "kpis": list(self.kpis),
            "signal_expected": self.signal_expected,
        }


AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec(
        "market_research",
        "Market Research Agent",
        ("rank tradable markets", "identify regime and opportunity candidates"),
        ("prices", "volume", "order books", "market metadata"),
        ("ranked universe", "market-quality scores", "research evidence"),
        ("filter invalid markets", "normalize features", "rank by expected net edge"),
        ("forward information coefficient", "net edge after costs", "coverage"),
    ),
    AgentSpec(
        "trend_detection",
        "Trend Detection Agent",
        ("detect directional regimes", "measure trend persistence"),
        ("OHLCV", "ATR", "moving averages", "breakout levels"),
        ("trend direction", "trend confidence", "regime"),
        ("multi-timeframe confirmation", "volatility normalization", "signal decay"),
        ("hit rate", "risk-adjusted return", "signal decay"),
    ),
    AgentSpec(
        "onchain_analysis",
        "On-Chain Analysis Agent",
        ("measure network and supply conditions", "identify structural flow changes"),
        ("exchange flows", "activity", "staking", "supply metrics"),
        ("on-chain factor", "flow regime", "risk flags"),
        ("clean point-in-time data", "normalize factors", "apply slow-factor decay"),
        ("forward IC", "coverage", "false-positive rate"),
    ),
    AgentSpec(
        "whale_tracking",
        "Whale Tracking Agent",
        ("classify large-wallet flows", "detect unusual exchange-directed transfers"),
        ("wallet clusters", "transfer graph", "exchange labels", "historical behavior"),
        ("accumulation/distribution score", "flow anomaly score"),
        ("classify wallet", "classify destination", "compare with history and liquidity"),
        ("precision", "lead time", "false-positive rate"),
    ),
    AgentSpec(
        "sentiment",
        "Sentiment Agent",
        ("measure market narrative", "detect sentiment shocks"),
        ("news", "public sentiment feeds", "source credibility", "time"),
        ("sentiment factor", "novelty score", "event-risk flag"),
        ("deduplicate", "weight sources", "apply novelty and time decay"),
        ("forward IC", "latency", "source-quality weighted precision"),
    ),
    AgentSpec(
        "risk",
        "Risk Agent",
        ("enforce capital preservation", "veto unsafe risk"),
        ("verified NAV", "drawdown", "exposure", "liquidity", "strategy state"),
        ("approve", "resize", "block", "deleveraging requirement"),
        ("apply deterministic hard limits", "allow risk-reducing exits", "fail closed"),
        ("hard breaches", "drawdown", "risk-of-ruin proxy"),
        signal_expected=False,
    ),
    AgentSpec(
        "portfolio_allocation",
        "Portfolio Allocation Agent",
        ("allocate scarce risk capital", "diversify strategy and asset exposure"),
        ("blended alpha", "risk limits", "correlation", "liquidity", "cost"),
        ("target weights", "risk budgets", "cash target"),
        ("rank net alpha", "apply constraints", "preserve cash and diversification"),
        ("portfolio Sharpe", "turnover", "concentration", "drawdown"),
        signal_expected=False,
    ),
    AgentSpec(
        "execution",
        "Execution Agent",
        ("translate approved intents into safe orders", "minimize implementation shortfall"),
        ("approved order intent", "book", "fees", "tick size", "balances"),
        ("orders", "fills", "execution telemetry"),
        ("validate venue rules", "prefer maker when rational", "reconcile every order"),
        ("slippage", "fill rate", "fees", "reject rate", "latency"),
        signal_expected=False,
    ),
    AgentSpec(
        "performance_review",
        "Performance Review Agent",
        ("review strategy evidence", "promote, keep or quarantine strategies"),
        ("fills", "PnL", "drawdown", "backtests", "shadow results"),
        ("PROMOTE", "KEEP", "DROP", "QUARANTINE"),
        ("require sample maturity", "penalize drawdown", "compare net performance after costs"),
        ("out-of-sample expectancy", "profit factor", "max drawdown", "sample size"),
        signal_expected=False,
    ),
)


class ResearchDepartment:
    """Track the institutional agent roster and evidence-producing signal health."""

    def __init__(self, specs: Iterable[AgentSpec] = AGENT_SPECS) -> None:
        self.specs = {spec.key: spec for spec in specs}
        self._signals: dict[str, list[AgentSignal]] = defaultdict(list)

    def ingest(self, signal: AgentSignal) -> None:
        key = signal.agent.strip().lower()
        if key in self.specs:
            rows = self._signals[key]
            rows.append(signal)
            if len(rows) > 1000:
                del rows[:-1000]

    def status(self, *, now: float | None = None) -> dict[str, object]:
        current = time.time() if now is None else float(now)
        rows: list[dict[str, object]] = []
        evidence_agents = 0
        healthy_signal_agents = 0

        for key, spec in self.specs.items():
            signals = self._signals.get(key, [])
            latest = max(signals, key=lambda row: row.timestamp) if signals else None
            if latest is None:
                state = "CONTROL" if not spec.signal_expected else "NO_DATA"
                age = None
                mean_confidence = 0.0
                mean_score = 0.0
            else:
                evidence_agents += 1
                age = max(0.0, current - latest.timestamp)
                freshness_limit = max(float(latest.horizon_seconds), 60.0)
                state = "ACTIVE" if age <= freshness_limit else "STALE"
                if state == "ACTIVE":
                    healthy_signal_agents += 1
                mean_confidence = sum(x.confidence for x in signals) / len(signals)
                mean_score = sum(x.score for x in signals) / len(signals)

            rows.append(
                {
                    **spec.as_dict(),
                    "state": state,
                    "signal_count": len(signals),
                    "latest_signal_age_seconds": None if age is None else round(age, 3),
                    "mean_confidence": round(mean_confidence, 6),
                    "mean_score": round(mean_score, 6),
                }
            )

        signal_specs = sum(1 for spec in self.specs.values() if spec.signal_expected)
        return {
            "department": "AI Research Department",
            "agent_count": len(self.specs),
            "signal_agent_count": signal_specs,
            "evidence_agent_count": evidence_agents,
            "healthy_signal_agent_count": healthy_signal_agents,
            "signal_coverage_pct": round(
                (evidence_agents / signal_specs * 100.0) if signal_specs else 100.0,
                6,
            ),
            "agents": rows,
        }
