"""Small, deterministic ML shadow model for paper trading.

It uses an online logistic classifier implemented with the standard library,
walk-forward evaluation, and never places orders. Input rows are dictionaries
with close/volume values; missing or malformed rows are skipped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ShadowSignal:
    probability_up: float
    action: str
    confidence: float
    model: str = "online-logistic-shadow"


def _features(rows: list[dict]) -> list[tuple[list[float], int]]:
    result: list[tuple[list[float], int]] = []
    for i in range(2, len(rows) - 1):
        try:
            p0 = float(rows[i - 2]["close"])
            p1 = float(rows[i - 1]["close"])
            p2 = float(rows[i]["close"])
            v1 = float(rows[i - 1].get("volume", 0.0))
            v2 = float(rows[i].get("volume", 0.0))
            if min(p0, p1, p2) <= 0:
                continue
            momentum = (p2 / p1) - 1.0
            acceleration = (p2 / p1) - (p1 / p0)
            volume_change = (v2 / v1 - 1.0) if v1 > 0 and v2 >= 0 else 0.0
            label = 1 if float(rows[i + 1]["close"]) > p2 else 0
            result.append(([momentum, acceleration, max(-2.0, min(2.0, volume_change))], label))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    return result


def _sigmoid(value: float) -> float:
    value = max(-40.0, min(40.0, value))
    return 1.0 / (1.0 + math.exp(-value))


class OnlineLogistic:
    def __init__(self, learning_rate: float = 0.15, l2: float = 0.001) -> None:
        self.weights = [0.0, 0.0, 0.0]
        self.bias = 0.0
        self.learning_rate = learning_rate
        self.l2 = l2

    def predict_proba(self, x: list[float]) -> float:
        return _sigmoid(self.bias + sum(w * v for w, v in zip(self.weights, x)))

    def update(self, x: list[float], y: int) -> None:
        p = self.predict_proba(x)
        error = p - y
        self.bias -= self.learning_rate * error
        self.weights = [w - self.learning_rate * (error * v + self.l2 * w) for w, v in zip(self.weights, x)]


def walk_forward(rows: Iterable[dict], minimum_train: int = 50) -> dict:
    samples = _features(list(rows))
    if len(samples) <= minimum_train:
        return {"model": "online-logistic-shadow", "samples": len(samples), "train_samples": 0, "test_samples": 0, "accuracy_pct": 0.0, "status": "insufficient_data"}
    model = OnlineLogistic()
    for x, y in samples[:minimum_train]:
        model.update(x, y)
    correct = 0
    for x, y in samples[minimum_train:]:
        predicted = 1 if model.predict_proba(x) >= 0.5 else 0
        correct += int(predicted == y)
        model.update(x, y)
    test_count = len(samples) - minimum_train
    return {"model": "online-logistic-shadow", "samples": len(samples), "train_samples": minimum_train, "test_samples": test_count, "accuracy_pct": round(correct / test_count * 100, 2), "weights": [round(w, 8) for w in model.weights], "bias": round(model.bias, 8), "status": "ok"}


def signal_from_recent(rows: Iterable[dict], model: OnlineLogistic | None = None) -> ShadowSignal:
    samples = _features(list(rows))
    if not samples:
        return ShadowSignal(0.5, "HOLD", 0.0)
    model = model or OnlineLogistic()
    for x, y in samples[:-1]:
        model.update(x, y)
    probability = model.predict_proba(samples[-1][0])
    confidence = abs(probability - 0.5) * 2
    action = "BUY" if probability >= 0.60 else "SELL" if probability <= 0.40 else "HOLD"
    return ShadowSignal(round(probability, 6), action, round(confidence, 6))


__all__ = ["OnlineLogistic", "ShadowSignal", "signal_from_recent", "walk_forward"]
