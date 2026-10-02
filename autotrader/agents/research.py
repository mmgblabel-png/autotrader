"""Specialized evidence-only agents.

Agents transform validated observations into normalized AgentSignal objects.
They have no exchange adapter and no execution method by design.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Mapping

from autotrader.fund.models import AgentSignal


def _bounded(value: Any, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def _direction_from_text(value: Any, fallback: float = 0.0) -> float:
    key = str(value or "").upper().strip()
    if key in {"BUY", "LONG", "BULL", "BULLISH"}:
        return 1.0
    if key in {"SELL", "SHORT", "BEAR", "BEARISH"}:
        return -1.0
    return max(-1.0, min(1.0, float(fallback)))


@dataclass(frozen=True)
class AgentDescriptor:
    name: str
    responsibilities: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    decision_process: tuple[str, ...]
    kpis: tuple[str, ...]


class MarketResearchAgent:
    descriptor = AgentDescriptor(
        name="market_research",
        responsibilities=(
            "rank liquid tradeable markets",
            "penalize spread, slippage and stale data",
            "produce cost-aware opportunity evidence",
        ),
        inputs=(
            "router score",
            "signal strength/direction",
            "liquidity",
            "spread",
            "expected slippage",
            "fee estimate",
            "snapshot age",
        ),
        outputs=("AgentSignal",),
        decision_process=(
            "reject ineligible/stale markets",
            "combine execution quality with router score",
            "emit normalized directional confidence",
        ),
        kpis=(
            "forward information coefficient",
            "net edge after costs",
            "false-positive opportunity rate",
        ),
    )

    def evaluate(
        self,
        row: Mapping[str, Any],
        *,
        strategy: str,
        timestamp: float,
    ) -> AgentSignal | None:
        if not bool(row.get("eligible")):
            return None
        symbol = str(row.get("market") or "").upper().strip()
        if not symbol:
            return None
        score = _bounded(
            row.get("economic_shadow_score", row.get("score")),
            0.0,
            100.0,
        )
        signal_strength = _bounded(
            row.get("signal_strength", score),
            0.0,
            100.0,
        )
        spread_bps = max(0.0, _bounded(row.get("spread_bps"), 0.0, 100000.0))
        slippage_bps = max(
            0.0, _bounded(row.get("expected_slippage_bps"), 0.0, 100000.0)
        )
        age = max(
            0.0, _bounded(row.get("snapshot_age_seconds"), 0.0, 100000.0)
        )
        liquidity = max(
            0.0, _bounded(row.get("liquidity_eur"), 0.0, 1e18)
        )
        cost_quality = max(0.0, 1.0 - (spread_bps + slippage_bps) / 100.0)
        freshness = max(0.0, 1.0 - age / 30.0)
        liquidity_quality = min(1.0, liquidity / 1000.0)
        confidence = _bounded(
            (signal_strength / 100.0)
            * (0.55 + 0.20 * cost_quality + 0.15 * freshness + 0.10 * liquidity_quality),
            0.0,
            1.0,
        )
        momentum = _bounded(row.get("momentum_pct"), -1000.0, 1000.0)
        direction = _direction_from_text(
            row.get("signal_direction"),
            1.0 if momentum > 0 else (-1.0 if momentum < 0 else 0.0),
        )
        return AgentSignal(
            agent=self.descriptor.name,
            strategy=strategy,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            score=score,
            horizon_seconds=900,
            timestamp=timestamp,
            metadata={
                "spread_bps": spread_bps,
                "liquidity_eur": liquidity,
                "expected_slippage_bps": slippage_bps,
                "estimated_round_trip_fee_bps": _bounded(
                    row.get("estimated_round_trip_fee_bps"), 0.0, 10000.0
                ),
                "snapshot_age_seconds": age,
                "source": "opportunity_router",
            },
        ).validated()


class TrendDetectionAgent:
    descriptor = AgentDescriptor(
        name="trend_detection",
        responsibilities=(
            "detect directional persistence",
            "separate trend from range regimes",
            "down-weight stale or weak momentum",
        ),
        inputs=("trend feature", "momentum", "volatility", "freshness"),
        outputs=("AgentSignal",),
        decision_process=(
            "center trend score around neutral 50",
            "require directional agreement with momentum",
            "scale confidence by trend distance and freshness",
        ),
        kpis=("trend hit rate", "forward return IC", "whipsaw rate"),
    )

    def evaluate(
        self,
        row: Mapping[str, Any],
        *,
        strategy: str,
        timestamp: float,
    ) -> AgentSignal | None:
        symbol = str(row.get("market") or "").upper().strip()
        features = dict(row.get("features") or {})
        if not symbol or "trend" not in features:
            return None
        trend = _bounded(features.get("trend"), 0.0, 100.0, 50.0)
        momentum = _bounded(row.get("momentum_pct"), -1000.0, 1000.0)
        distance = abs(trend - 50.0) / 50.0
        if distance < 0.10:
            return None
        direction = 1.0 if trend > 50.0 else -1.0
        if momentum != 0 and (momentum > 0) != (direction > 0):
            distance *= 0.5
        age = max(
            0.0, _bounded(row.get("snapshot_age_seconds"), 0.0, 100000.0)
        )
        freshness = max(0.0, 1.0 - age / 30.0)
        confidence = _bounded(distance * (0.7 + 0.3 * freshness), 0.0, 1.0)
        score = _bounded(50.0 + direction * distance * 50.0, 0.0, 100.0)
        return AgentSignal(
            agent=self.descriptor.name,
            strategy=strategy,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            score=score,
            horizon_seconds=3600,
            timestamp=timestamp,
            metadata={
                "trend_feature": trend,
                "momentum_pct": momentum,
                "volatility_pct": _bounded(
                    row.get("volatility_pct"), 0.0, 1000.0
                ),
                "source": "opportunity_router",
            },
        ).validated()


class OnChainAnalysisAgent:
    descriptor = AgentDescriptor(
        name="onchain_analysis",
        responsibilities=(
            "measure exchange-flow pressure",
            "measure network/activity acceleration",
            "measure supply/staking pressure",
        ),
        inputs=(
            "exchange_netflow_z",
            "activity_z",
            "supply_pressure_z",
            "data_quality",
        ),
        outputs=("AgentSignal",),
        decision_process=(
            "treat exchange inflows as potential sell pressure",
            "reward activity growth",
            "penalize adverse supply pressure",
        ),
        kpis=("forward IC", "event precision", "coverage"),
    )

    def evaluate(
        self,
        observation: Mapping[str, Any],
        *,
        strategy: str = "multi_factor",
    ) -> AgentSignal | None:
        symbol = str(observation.get("symbol") or "").upper().strip()
        quality = _bounded(observation.get("data_quality"), 0.0, 1.0)
        if not symbol or quality <= 0:
            return None
        netflow = _bounded(observation.get("exchange_netflow_z"), -5.0, 5.0)
        activity = _bounded(observation.get("activity_z"), -5.0, 5.0)
        supply = _bounded(observation.get("supply_pressure_z"), -5.0, 5.0)
        raw = (-0.45 * netflow + 0.35 * activity - 0.20 * supply) / 5.0
        direction = _bounded(raw, -1.0, 1.0)
        confidence = _bounded(abs(direction) * quality, 0.0, 1.0)
        if confidence < 0.10:
            return None
        return AgentSignal(
            agent=self.descriptor.name,
            strategy=strategy,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            score=_bounded(50.0 + direction * 50.0, 0.0, 100.0),
            horizon_seconds=max(
                3600, int(observation.get("horizon_seconds") or 86400)
            ),
            timestamp=float(observation.get("timestamp") or time.time()),
            metadata={
                "exchange_netflow_z": netflow,
                "activity_z": activity,
                "supply_pressure_z": supply,
                "data_quality": quality,
            },
        ).validated()


class WhaleTrackingAgent:
    descriptor = AgentDescriptor(
        name="whale_tracking",
        responsibilities=(
            "classify large-wallet accumulation/distribution",
            "distinguish exchange deposits from self-transfers",
            "emit only quality-weighted wallet-flow evidence",
        ),
        inputs=(
            "accumulation_z",
            "exchange_inflow_z",
            "large_tx_z",
            "classification_quality",
        ),
        outputs=("AgentSignal",),
        decision_process=(
            "reward verified accumulation",
            "penalize verified exchange inflows",
            "scale by wallet classification quality",
        ),
        kpis=("large-move precision", "false alarm rate", "coverage"),
    )

    def evaluate(
        self,
        observation: Mapping[str, Any],
        *,
        strategy: str = "multi_factor",
    ) -> AgentSignal | None:
        symbol = str(observation.get("symbol") or "").upper().strip()
        quality = _bounded(
            observation.get("classification_quality"), 0.0, 1.0
        )
        if not symbol or quality <= 0:
            return None
        accumulation = _bounded(observation.get("accumulation_z"), -5.0, 5.0)
        inflow = _bounded(observation.get("exchange_inflow_z"), -5.0, 5.0)
        large_tx = abs(_bounded(observation.get("large_tx_z"), -5.0, 5.0))
        raw = (0.55 * accumulation - 0.45 * inflow) / 5.0
        direction = _bounded(raw, -1.0, 1.0)
        confidence = _bounded(
            abs(direction) * quality * (0.7 + 0.3 * min(1.0, large_tx / 3.0)),
            0.0,
            1.0,
        )
        if confidence < 0.10:
            return None
        return AgentSignal(
            agent=self.descriptor.name,
            strategy=strategy,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            score=_bounded(50.0 + direction * 50.0, 0.0, 100.0),
            horizon_seconds=max(
                1800, int(observation.get("horizon_seconds") or 21600)
            ),
            timestamp=float(observation.get("timestamp") or time.time()),
            metadata={
                "accumulation_z": accumulation,
                "exchange_inflow_z": inflow,
                "large_tx_z": large_tx,
                "classification_quality": quality,
            },
        ).validated()


class SentimentAgent:
    descriptor = AgentDescriptor(
        name="sentiment",
        responsibilities=(
            "convert source-weighted narrative into bounded evidence",
            "apply novelty and source-quality filters",
            "decay stale sentiment",
        ),
        inputs=("sentiment", "source_quality", "novelty", "age_seconds"),
        outputs=("AgentSignal",),
        decision_process=(
            "bound sentiment to [-1,1]",
            "multiply by source quality and novelty",
            "exponentially decay old observations",
        ),
        kpis=("forward IC", "source precision", "signal half-life"),
    )

    def evaluate(
        self,
        observation: Mapping[str, Any],
        *,
        strategy: str = "multi_factor",
    ) -> AgentSignal | None:
        symbol = str(observation.get("symbol") or "").upper().strip()
        sentiment = _bounded(observation.get("sentiment"), -1.0, 1.0)
        source_quality = _bounded(
            observation.get("source_quality"), 0.0, 1.0
        )
        novelty = _bounded(observation.get("novelty"), 0.0, 1.0)
        age = max(
            0.0, _bounded(observation.get("age_seconds"), 0.0, 604800.0)
        )
        if not symbol or source_quality <= 0 or novelty <= 0:
            return None
        decay = math.exp(-age / 21600.0)
        direction = sentiment
        confidence = _bounded(
            abs(sentiment) * source_quality * novelty * decay,
            0.0,
            1.0,
        )
        if confidence < 0.10:
            return None
        return AgentSignal(
            agent=self.descriptor.name,
            strategy=strategy,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            score=_bounded(50.0 + direction * confidence * 50.0, 0.0, 100.0),
            horizon_seconds=max(
                900, int(observation.get("horizon_seconds") or 14400)
            ),
            timestamp=float(observation.get("timestamp") or time.time()),
            metadata={
                "source_quality": source_quality,
                "novelty": novelty,
                "age_seconds": age,
            },
        ).validated()


class ResearchAgentSuite:
    """Create cost-aware research evidence from the live opportunity router."""

    def __init__(self) -> None:
        self.market_research = MarketResearchAgent()
        self.trend_detection = TrendDetectionAgent()
        self.onchain_analysis = OnChainAnalysisAgent()
        self.whale_tracking = WhaleTrackingAgent()
        self.sentiment = SentimentAgent()

    @property
    def descriptors(self) -> dict[str, AgentDescriptor]:
        agents = (
            self.market_research,
            self.trend_detection,
            self.onchain_analysis,
            self.whale_tracking,
            self.sentiment,
        )
        return {agent.descriptor.name: agent.descriptor for agent in agents}

    def from_router(
        self,
        router_payload: Mapping[str, Any],
        *,
        top_per_strategy: int = 1,
    ) -> list[AgentSignal]:
        rankings = dict(router_payload.get("rankings") or {})
        updated_at = float(router_payload.get("updated_at") or time.time())
        timestamp = float(int(updated_at // 60) * 60)
        strategy_map = {
            "market_maker": "MarketMaker",
            "grid": "GridRunner",
            "sniper": "SniperBot",
            "mean_reversion": "MeanReversion",
            "volatility_breakout": "VolatilityBreakout",
        }
        signals: list[AgentSignal] = []
        for router_key, strategy_name in strategy_map.items():
            accepted = 0
            for row in rankings.get(router_key, []) or []:
                if not bool(row.get("eligible")):
                    continue
                market_signal = self.market_research.evaluate(
                    row,
                    strategy=strategy_name,
                    timestamp=timestamp,
                )
                if market_signal is not None:
                    signals.append(market_signal)
                trend_signal = self.trend_detection.evaluate(
                    row,
                    strategy=strategy_name,
                    timestamp=timestamp,
                )
                if trend_signal is not None:
                    signals.append(trend_signal)
                accepted += 1
                if accepted >= max(1, int(top_per_strategy)):
                    break
        return signals
