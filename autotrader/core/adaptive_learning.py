"""Bounded adaptive learning from realized trading outcomes.

The learner never sends orders and never changes exchange/risk gates. It only
adjusts a small allow-list of strategy parameters within hard bounds, persists
its memory, and rolls changes back when post-change results regress.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autotrader.core.logger import get_logger

log = get_logger("AdaptiveLearning")


@dataclass(frozen=True)
class Tunable:
    parameter: str
    minimum: float
    maximum: float
    bad_multiplier: float
    good_multiplier: float


_TUNABLES: dict[str, Tunable] = {
    "MarketMaker": Tunable("target_spread", 0.80, 1.50, 1.05, 0.98),
    "GridRunner": Tunable("entry_offset_pct", 0.60, 1.50, 1.05, 0.99),
    "SniperBot": Tunable("momentum_pct", 0.50, 1.50, 1.05, 0.98),
    "MeanReversionShadow": Tunable("entry_z", 1.40, 3.00, 1.06, 0.99),
    "VolatilityBreakoutShadow": Tunable("breakout_buffer_pct", 0.08, 0.60, 1.06, 0.99),
    "SniperV2Shadow": Tunable("momentum_pct", 0.15, 0.80, 1.05, 0.99),
}


class AdaptiveLearning:
    """Persistent, conservative parameter learner.

    Learning is based only on realized SELL outcome deltas after fees. Changes
    are delayed until enough samples exist, limited to an allow-list, and
    automatically reverted when the evaluation window underperforms the
    pre-change baseline.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        raw = config or {}
        self.enabled = bool(raw.get("enabled", True))
        self.path = Path(
            os.getenv(
                "ADAPTIVE_LEARNING_PATH",
                str(raw.get("path", "/data/adaptive_learning.json")),
            )
        )
        self.min_samples = max(6, int(raw.get("min_samples", 12)))
        self.lookback = max(self.min_samples, int(raw.get("lookback", 24)))
        self.evaluation_window = max(4, int(raw.get("evaluation_window", 6)))
        self.change_cooldown = max(2, int(raw.get("change_cooldown", 4)))
        self.good_winrate_pct = float(raw.get("good_winrate_pct", 62.0))
        self.max_regression_pct = max(1.0, float(raw.get("max_regression_pct", 20.0)))
        self._state = self._load()

    def _blank_strategy(self) -> dict[str, Any]:
        return {
            "completed_exits": 0,
            "wins": 0,
            "losses": 0,
            "total_net_pnl_eur": 0.0,
            "recent_outcomes": [],
            "current_overrides": {},
            "last_change_exit": -10_000,
            "pending_change": None,
            "history": [],
            "seen_outcome_keys": [],
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "strategies": {}}
        try:
            raw = json.loads(self.path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("root must be object")
            raw.setdefault("version", 1)
            raw.setdefault("strategies", {})
            return raw
        except Exception as exc:
            log.warning("Adaptive learning memory could not be loaded: %s", type(exc).__name__)
            return {"version": 1, "strategies": {}}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._state, indent=2, sort_keys=True)
            with tempfile.NamedTemporaryFile(
                "w",
                dir=str(self.path.parent),
                prefix=".adaptive-learning-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                temp_name = handle.name
            os.replace(temp_name, self.path)
        except Exception as exc:
            log.warning("Adaptive learning memory could not be saved: %s", type(exc).__name__)

    @staticmethod
    def _score(values: list[float]) -> float:
        if not values:
            return 0.0
        avg = sum(values) / len(values)
        downside = sum(abs(v) for v in values if v < 0) / len(values)
        return avg - (0.35 * downside)

    @staticmethod
    def _winrate(values: list[float]) -> float:
        decided = [v for v in values if abs(v) > 1e-12]
        if not decided:
            return 0.0
        return sum(1 for v in decided if v > 0) / len(decided) * 100.0

    @staticmethod
    def _bounded(value: float, minimum: float, maximum: float) -> float:
        return round(max(minimum, min(maximum, value)), 8)

    def apply_overrides(self, strategy_name: str, strategy_config: dict[str, Any]) -> dict[str, Any]:
        state = self._state.setdefault("strategies", {}).setdefault(strategy_name, self._blank_strategy())
        tunable = _TUNABLES.get(strategy_name)
        if tunable is None:
            return {}
        raw = state.get("current_overrides") or {}
        overrides: dict[str, float] = {}
        if tunable.parameter in raw and tunable.parameter in strategy_config:
            try:
                value = self._bounded(float(raw[tunable.parameter]), tunable.minimum, tunable.maximum)
            except (TypeError, ValueError):
                value = self._bounded(float(strategy_config[tunable.parameter]), tunable.minimum, tunable.maximum)
            strategy_config[tunable.parameter] = value
            overrides[tunable.parameter] = value
            state["current_overrides"] = dict(overrides)
        return overrides

    def record_realized_outcome(
        self,
        *,
        strategy_name: str,
        side: str,
        net_pnl_delta_eur: float,
        strategy_config: dict[str, Any],
        symbol: str = "",
        outcome_key: str = "",
    ) -> dict[str, Any]:
        if not self.enabled or side.upper() != "SELL" or not math.isfinite(net_pnl_delta_eur):
            return {"changed": False, "reason": "not_eligible"}

        tunable = _TUNABLES.get(strategy_name)
        if tunable is None:
            return {"changed": False, "reason": "strategy_not_tunable"}

        states = self._state.setdefault("strategies", {})
        state = states.setdefault(strategy_name, self._blank_strategy())
        seen = list(state.get("seen_outcome_keys") or [])
        if outcome_key and outcome_key in seen:
            return {"changed": False, "reason": "duplicate_outcome"}
        if outcome_key:
            seen.append(outcome_key)
            state["seen_outcome_keys"] = seen[-1000:]
        outcomes = list(state.get("recent_outcomes") or [])
        outcomes.append(float(net_pnl_delta_eur))
        outcomes = outcomes[-self.lookback :]
        state["recent_outcomes"] = outcomes
        state["completed_exits"] = int(state.get("completed_exits", 0)) + 1
        state["total_net_pnl_eur"] = float(state.get("total_net_pnl_eur", 0.0)) + float(net_pnl_delta_eur)
        if net_pnl_delta_eur > 0:
            state["wins"] = int(state.get("wins", 0)) + 1
        elif net_pnl_delta_eur < 0:
            state["losses"] = int(state.get("losses", 0)) + 1

        exit_count = int(state["completed_exits"])
        pending = state.get("pending_change")
        if pending:
            post = list(pending.get("post_outcomes") or [])
            post.append(float(net_pnl_delta_eur))
            pending["post_outcomes"] = post
            if len(post) >= self.evaluation_window:
                before = float(pending.get("baseline_score", 0.0))
                after = self._score(post[-self.evaluation_window :])
                regression = 0.0
                scale = max(abs(before), 0.01)
                if after < before:
                    regression = (before - after) / scale * 100.0
                if after < 0 or regression > self.max_regression_pct:
                    old = float(pending["old_value"])
                    state.setdefault("current_overrides", {})[tunable.parameter] = old
                    strategy_config[tunable.parameter] = old
                    state.setdefault("history", []).append({
                        "timestamp": time.time(),
                        "action": "rollback",
                        "parameter": tunable.parameter,
                        "from": float(pending["new_value"]),
                        "to": old,
                        "baseline_score": before,
                        "evaluation_score": after,
                    })
                    log.info("[%s] learner rolled back %s %.8f -> %.8f", strategy_name, tunable.parameter, float(pending["new_value"]), old)
                else:
                    state.setdefault("history", []).append({
                        "timestamp": time.time(),
                        "action": "keep",
                        "parameter": tunable.parameter,
                        "value": float(pending["new_value"]),
                        "baseline_score": before,
                        "evaluation_score": after,
                    })
                state["pending_change"] = None
                self._save()
                return {"changed": True, "action": state["history"][-1]["action"], "parameter": tunable.parameter}
            self._save()
            return {"changed": False, "reason": "evaluating_change", "evaluation_samples": len(post)}

        if len(outcomes) < self.min_samples:
            self._save()
            return {"changed": False, "reason": "insufficient_samples"}

        if exit_count - int(state.get("last_change_exit", -10_000)) < self.change_cooldown:
            self._save()
            return {"changed": False, "reason": "cooldown"}

        recent = outcomes[-self.min_samples :]
        recent_score = self._score(recent)
        winrate = self._winrate(recent)
        current = float(
            state.get("current_overrides", {}).get(
                tunable.parameter,
                strategy_config.get(tunable.parameter, tunable.minimum),
            )
        )

        if recent_score <= 0:
            candidate = self._bounded(current * tunable.bad_multiplier, tunable.minimum, tunable.maximum)
            reason = "defensive"
        elif winrate >= self.good_winrate_pct:
            candidate = self._bounded(current * tunable.good_multiplier, tunable.minimum, tunable.maximum)
            reason = "cautious_expansion"
        else:
            self._save()
            return {"changed": False, "reason": "no_clear_edge"}

        if abs(candidate - current) < 1e-12:
            self._save()
            return {"changed": False, "reason": "at_bound"}

        state.setdefault("current_overrides", {})[tunable.parameter] = candidate
        strategy_config[tunable.parameter] = candidate
        state["last_change_exit"] = exit_count
        state["pending_change"] = {
            "parameter": tunable.parameter,
            "old_value": current,
            "new_value": candidate,
            "baseline_score": recent_score,
            "post_outcomes": [],
            "reason": reason,
            "symbol": symbol.upper(),
            "started_exit": exit_count,
            "timestamp": time.time(),
        }
        state.setdefault("history", []).append({
            "timestamp": time.time(),
            "action": "adjust",
            "parameter": tunable.parameter,
            "from": current,
            "to": candidate,
            "reason": reason,
            "score": recent_score,
            "winrate_pct": winrate,
        })
        state["history"] = state["history"][-100:]
        self._save()
        log.info("[%s] learner adjusted %s %.8f -> %.8f (%s)", strategy_name, tunable.parameter, current, candidate, reason)
        return {"changed": True, "action": "adjust", "parameter": tunable.parameter, "value": candidate, "reason": reason}

    def snapshot(self) -> dict[str, Any]:
        result = deepcopy(self._state)
        for name, state in result.get("strategies", {}).items():
            recent = list(state.get("recent_outcomes") or [])
            state["rolling_score"] = round(self._score(recent), 8)
            state["rolling_winrate_pct"] = round(self._winrate(recent), 2)
            state["recent_outcomes"] = recent[-self.lookback :]
            if state.get("history"):
                state["history"] = state["history"][-20:]
        result["enabled"] = self.enabled
        result["path"] = str(self.path)
        result["policy"] = {
            "min_samples": self.min_samples,
            "lookback": self.lookback,
            "evaluation_window": self.evaluation_window,
            "change_cooldown": self.change_cooldown,
            "good_winrate_pct": self.good_winrate_pct,
            "max_regression_pct": self.max_regression_pct,
            "tunables": {name: vars(item) for name, item in _TUNABLES.items()},
        }
        return result
