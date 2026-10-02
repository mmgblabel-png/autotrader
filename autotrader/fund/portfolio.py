"""Deterministic signal blending for strategy pods."""

from __future__ import annotations

from collections import defaultdict
import math
import time
from typing import Iterable, Mapping

from autotrader.fund.models import AgentSignal, BlendedSignal, FundMandate


class SignalBlender:
    """Blend independent agent views without giving any agent execution authority."""

    def __init__(
        self,
        mandate: FundMandate,
        agent_weights: Mapping[str, float] | None = None,
    ) -> None:
        self._mandate = mandate
        self._weights = {
            str(name): max(0.0, float(weight))
            for name, weight in dict(agent_weights or {}).items()
        }

    def blend(
        self,
        signals: Iterable[AgentSignal],
        *,
        now: float | None = None,
    ) -> list[BlendedSignal]:
        current = float(now if now is not None else time.time())
        grouped: dict[tuple[str, str], list[AgentSignal]] = defaultdict(list)

        for raw in signals:
            signal = raw.validated()
            if signal.confidence < self._mandate.min_signal_confidence:
                continue
            age = max(0.0, current - signal.timestamp)
            if age > max(float(signal.horizon_seconds), self._mandate.signal_half_life_seconds * 8.0):
                continue
            grouped[(signal.strategy, signal.symbol)].append(signal)

        output: list[BlendedSignal] = []
        for (strategy, symbol), group in grouped.items():
            weighted_direction = 0.0
            weighted_confidence = 0.0
            weighted_score = 0.0
            total_weight = 0.0
            latest = 0.0

            for signal in group:
                age = max(0.0, current - signal.timestamp)
                recency = math.exp(
                    -math.log(2.0) * age / self._mandate.signal_half_life_seconds
                )
                agent_weight = self._weights.get(signal.agent, 1.0)
                weight = agent_weight * signal.confidence * recency
                if weight <= 0:
                    continue
                weighted_direction += signal.direction * weight
                weighted_confidence += signal.confidence * weight
                weighted_score += signal.score * weight
                total_weight += weight
                latest = max(latest, signal.timestamp)

            if total_weight <= 0:
                continue

            direction = max(-1.0, min(1.0, weighted_direction / total_weight))
            confidence = max(0.0, min(1.0, weighted_confidence / total_weight))
            score = max(0.0, min(100.0, weighted_score / total_weight))
            output.append(
                BlendedSignal(
                    strategy=strategy,
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    score=score,
                    source_count=len(group),
                    timestamp=latest or current,
                )
            )

        output.sort(
            key=lambda row: (row.confidence * abs(row.direction) * row.score),
            reverse=True,
        )
        return output
