"""Persistent shadow evaluation for candidate strategies.

This module never places exchange orders. It consumes observed prices and
simulates long-only round trips with explicit fee/slippage assumptions.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from autotrader.core.adaptive_learning import AdaptiveLearning


@dataclass
class ShadowStats:
    prices: list[float] = field(default_factory=list)
    position_qty: float = 0.0
    entry_price: float = 0.0
    entry_cost_eur: float = 0.0
    position_peak_price: float = 0.0
    peak_equity_eur: float = 0.0
    realized_net_pnl_eur: float = 0.0
    completed_trades: int = 0
    wins: int = 0
    losses: int = 0
    max_drawdown_eur: float = 0.0
    last_signal: str = "warming_up"
    last_trade_at: float = 0.0
    outcomes: list[float] = field(default_factory=list)
    strategy_version: str = "v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "prices": self.prices[-240:],
            "position_qty": self.position_qty,
            "entry_price": self.entry_price,
            "entry_cost_eur": self.entry_cost_eur,
            "position_peak_price": self.position_peak_price,
            "peak_equity_eur": self.peak_equity_eur,
            "realized_net_pnl_eur": self.realized_net_pnl_eur,
            "completed_trades": self.completed_trades,
            "wins": self.wins,
            "losses": self.losses,
            "max_drawdown_eur": self.max_drawdown_eur,
            "last_signal": self.last_signal,
            "last_trade_at": self.last_trade_at,
            "outcomes": self.outcomes[-100:],
            "strategy_version": self.strategy_version,
        }


class ShadowStrategyEngine:
    """Run candidate strategies in a persistent no-order shadow account."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        learner: "AdaptiveLearning | None" = None,
    ) -> None:
        self.config = config or {}
        self.learner = learner
        self.path = Path(str(self.config.get("path", "/data/shadow_strategies.json")))
        self.fee_pct = float(self.config.get("fee_pct_each_leg", 0.25))
        self.slippage_pct = float(self.config.get("slippage_pct_each_leg", 0.05))
        self.min_completed_trades = int(self.config.get("promotion_min_completed_trades", 20))
        self.min_winrate_pct = float(self.config.get("promotion_min_winrate_pct", 52.0))
        self.max_drawdown_pct = float(self.config.get("promotion_max_drawdown_pct", 8.0))
        self.min_net_pnl_eur = float(self.config.get("promotion_min_net_pnl_eur", 0.50))
        self.min_profit_factor = max(1.0, float(self.config.get("promotion_min_profit_factor", 1.10)))
        self.min_q10_return_pct = float(
            self.config.get("promotion_min_q10_return_pct", -2.50)
        )
        self.cost_stress_multiplier = max(1.0, float(self.config.get("promotion_cost_stress_multiplier", 1.25)))
        self.canary_min_completed_trades = max(
            4, int(self.config.get("canary_min_completed_trades", 12))
        )
        self.canary_min_winrate_pct = float(
            self.config.get("canary_min_winrate_pct", 52.0)
        )
        self.canary_min_net_pnl_eur = float(
            self.config.get("canary_min_net_pnl_eur", 0.10)
        )
        self.canary_min_profit_factor = max(
            1.0, float(self.config.get("canary_min_profit_factor", 1.05))
        )
        self.canary_max_drawdown_pct = max(
            0.1, float(self.config.get("canary_max_drawdown_pct", 5.0))
        )
        self._states: dict[str, ShadowStats] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            raw = {}
        for name, item in (raw.get("strategies") or {}).items():
            if not isinstance(item, dict):
                continue
            allowed = ShadowStats.__dataclass_fields__.keys()
            self._states[name] = ShadowStats(**{k: item[k] for k in allowed if k in item})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"strategies": {k: v.as_dict() for k, v in self._states.items()}}
        fd, tmp = tempfile.mkstemp(prefix="shadow-", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _state(self, name: str) -> ShadowStats:
        return self._states.setdefault(name, ShadowStats())

    @staticmethod
    def _learner_name(name: str) -> str:
        # Dynamic fast-lane candidates are named "kind@MARKET". Learning is
        # strategy-family bounded, so normalize the dynamic suffix before
        # looking up the allow-listed tunable.
        base_name = str(name).split("@", 1)[0]
        return {
            "mean_reversion": "MeanReversionShadow",
            "volatility_breakout": "VolatilityBreakoutShadow",
            "sniper_v2": "SniperV2Shadow",
        }.get(base_name, name)

    def _ensure_version(self, name: str, cfg: dict[str, Any]) -> ShadowStats:
        state = self._state(name)
        version = str(cfg.get("strategy_version", "v1"))
        if state.strategy_version == version:
            return state
        self._states[name] = ShadowStats(
            prices=state.prices[-240:],
            strategy_version=version,
            last_signal=f"version_reset_{version}",
        )
        return self._states[name]

    @staticmethod
    def _percentile(values: list[float], quantile: float) -> float:
        """Deterministic linear percentile for small shadow-trade samples."""
        if not values:
            return 0.0
        ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
        if not ordered:
            return 0.0
        if len(ordered) == 1:
            return ordered[0]
        q = max(0.0, min(1.0, float(quantile)))
        position = (len(ordered) - 1) * q
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    @property
    def round_trip_cost_pct(self) -> float:
        return 2.0 * (self.fee_pct + self.slippage_pct)

    def update(self, name: str, price: float, cfg: dict[str, Any], *, persist: bool = True) -> None:
        if price <= 0 or not math.isfinite(price):
            return
        state = self._ensure_version(name, cfg)
        learner_name = self._learner_name(name)
        if self.learner is not None:
            self.learner.apply_overrides(learner_name, cfg)
        state.prices.append(float(price))
        state.prices = state.prices[-240:]
        before_trades = state.completed_trades
        kind = str(cfg.get("kind", name)).lower()
        if kind == "mean_reversion":
            self._mean_reversion(state, price, cfg)
        elif kind == "volatility_breakout":
            self._volatility_breakout(state, price, cfg)
        elif kind == "sniper_v2":
            self._sniper_v2(state, price, cfg)
        if self.learner is not None and state.completed_trades > before_trades and state.outcomes:
            self.learner.record_realized_outcome(
                strategy_name=learner_name,
                side="SELL",
                net_pnl_delta_eur=float(state.outcomes[-1]),
                strategy_config=cfg,
                symbol=str(cfg.get("symbol", "")),
                outcome_key=f"shadow:{name}:{state.strategy_version}:{state.completed_trades}",
            )
        if persist:
            self._save()

    def flush(self) -> None:
        """Persist all shadow states once after a batch of market updates."""
        self._save()

    def sample_count(self, name: str) -> int:
        state = self._states.get(name)
        return len(state.prices) if state is not None else 0

    def _buy(self, state: ShadowStats, price: float, cfg: dict[str, Any], signal: str) -> None:
        if state.position_qty > 0:
            return
        budget = max(1.0, float(cfg.get("shadow_order_eur", 6.0)))
        effective = price * (1 + self.slippage_pct / 100)
        entry_fee = budget * self.fee_pct / 100
        spendable = max(0.0, budget - entry_fee)
        qty = spendable / effective
        if qty <= 0:
            return
        state.position_qty = qty
        state.entry_price = effective
        state.entry_cost_eur = budget
        state.position_peak_price = price
        state.last_signal = signal
        state.last_trade_at = time.time()

    def _sell(self, state: ShadowStats, price: float, signal: str) -> None:
        if state.position_qty <= 0:
            return
        effective = price * (1 - self.slippage_pct / 100)
        gross = state.position_qty * effective
        exit_fee = gross * self.fee_pct / 100
        proceeds = gross - exit_fee
        pnl = proceeds - state.entry_cost_eur
        state.realized_net_pnl_eur += pnl
        state.completed_trades += 1
        state.wins += int(pnl > 0)
        state.losses += int(pnl < 0)
        state.outcomes.append(pnl)
        state.outcomes = state.outcomes[-100:]
        state.peak_equity_eur = max(state.peak_equity_eur, state.realized_net_pnl_eur)
        drawdown = state.peak_equity_eur - state.realized_net_pnl_eur
        state.max_drawdown_eur = max(state.max_drawdown_eur, drawdown)
        state.position_qty = 0.0
        state.entry_price = 0.0
        state.entry_cost_eur = 0.0
        state.position_peak_price = 0.0
        state.last_signal = signal
        state.last_trade_at = time.time()

    def _mean_reversion(self, state: ShadowStats, price: float, cfg: dict[str, Any]) -> None:
        lookback = max(12, int(cfg.get("lookback", 40)))
        if len(state.prices) < lookback:
            state.last_signal = "warming_up"
            return
        window = state.prices[-lookback:]
        mean = statistics.fmean(window)
        stdev = statistics.pstdev(window)
        z = (price - mean) / stdev if stdev > 1e-12 else 0.0
        entry_z = -abs(float(cfg.get("entry_z", 2.0)))
        exit_z = float(cfg.get("exit_z", -0.05))
        take_profit = float(cfg.get("take_profit_pct", 1.35))
        stop_loss = float(cfg.get("stop_loss_pct", 1.20))
        rebound_pct = max(0.0, float(cfg.get("entry_rebound_pct", 0.08)))
        max_downtrend_pct = max(0.0, float(cfg.get("max_downtrend_pct", 1.20)))
        min_exit_net_pct = max(
            self.round_trip_cost_pct + 0.15,
            float(cfg.get("min_exit_net_pct", 0.75)),
        )
        previous = state.prices[-2] if len(state.prices) >= 2 else price
        rebound = (price / previous - 1) * 100 if previous > 0 else 0.0
        segment = max(4, min(8, lookback // 4))
        early_mean = statistics.fmean(window[:segment])
        late_mean = statistics.fmean(window[-segment:])
        trend_pct = (late_mean / early_mean - 1) * 100 if early_mean > 0 else 0.0

        if state.position_qty <= 0:
            if z <= entry_z and rebound >= rebound_pct and trend_pct >= -max_downtrend_pct:
                self._buy(state, price, cfg, f"buy_z_{z:.2f}_rebound_{rebound:.2f}")
            elif z <= entry_z and trend_pct < -max_downtrend_pct:
                state.last_signal = f"skip_downtrend_{trend_pct:.2f}%"
            elif z <= entry_z:
                state.last_signal = f"wait_rebound_{rebound:.2f}%"
            else:
                state.last_signal = f"wait_z_{z:.2f}"
            return

        move = (price / state.entry_price - 1) * 100
        if move >= take_profit:
            self._sell(state, price, "take_profit")
        elif z >= exit_z and move >= min_exit_net_pct:
            self._sell(state, price, f"mean_exit_{z:.2f}")
        elif move <= -stop_loss:
            self._sell(state, price, "stop_loss")
        else:
            state.last_signal = f"hold_{move:.2f}%_z_{z:.2f}"
    def _volatility_breakout(self, state: ShadowStats, price: float, cfg: dict[str, Any]) -> None:
        lookback = max(10, int(cfg.get("lookback", 30)))
        if len(state.prices) <= lookback:
            state.last_signal = "warming_up"
            return
        previous = state.prices[-lookback-1:-1]
        buffer_pct = float(cfg.get("breakout_buffer_pct", 0.16))
        breakout = max(previous) * (1 + buffer_pct / 100)
        returns = [
            abs(previous[i] / previous[i - 1] - 1) * 100
            for i in range(1, len(previous))
            if previous[i - 1] > 0
        ]
        avg_move = statistics.fmean(returns) if returns else 0.0
        recent_move = statistics.fmean(returns[-5:]) if len(returns) >= 5 else avg_move
        expansion_ratio = recent_move / avg_move if avg_move > 1e-9 else 0.0
        min_vol = float(cfg.get("min_avg_move_pct", 0.03))
        min_expansion = float(cfg.get("min_vol_expansion_ratio", 0.0))
        max_entry_spike = float(cfg.get("max_entry_spike_pct", 1.25))
        take_profit = float(cfg.get("take_profit_pct", 1.5))
        stop_loss = float(cfg.get("stop_loss_pct", 0.75))
        trailing = float(cfg.get("trailing_exit_pct", 0.45))
        min_exit_net_pct = max(self.round_trip_cost_pct + 0.15, float(cfg.get("min_exit_net_pct", 0.75)))
        breakout_move = (price / max(previous) - 1.0) * 100 if max(previous) > 0 else 0.0
        if state.position_qty <= 0:
            if (
                price >= breakout
                and avg_move >= min_vol
                and expansion_ratio >= min_expansion
                and breakout_move <= max_entry_spike
            ):
                self._buy(state, price, cfg, f"breakout_{avg_move:.3f}_x{expansion_ratio:.2f}")
            elif breakout_move > max_entry_spike:
                state.last_signal = f"skip_spike_{breakout_move:.2f}%"
            else:
                state.last_signal = f"wait_breakout_vol_{avg_move:.3f}_x{expansion_ratio:.2f}"
            return
        peak = max(state.position_peak_price or state.entry_price, price)
        state.position_peak_price = peak
        move = (price / state.entry_price - 1) * 100
        trail_move = (price / peak - 1) * 100
        if move >= take_profit:
            self._sell(state, price, "take_profit")
        elif move <= -stop_loss:
            self._sell(state, price, "stop_loss")
        elif trail_move <= -trailing and move >= min_exit_net_pct:
            self._sell(state, price, "trailing_profit_exit")
        else:
            state.last_signal = f"hold_{move:.2f}%"

    def _sniper_v2(self, state: ShadowStats, price: float, cfg: dict[str, Any]) -> None:
        fast = max(3, int(cfg.get("ema_fast", 6)))
        slow = max(fast + 2, int(cfg.get("ema_slow", 18)))
        if len(state.prices) < slow + 1:
            state.last_signal = "warming_up"
            return

        def ema(values: list[float], span: int) -> float:
            alpha = 2.0 / (span + 1.0)
            value = values[0]
            for item in values[1:]:
                value = alpha * item + (1.0 - alpha) * value
            return value

        recent = state.prices[-max(slow * 2, slow + 3):]
        fast_ema = ema(recent[-max(fast * 2, fast):], fast)
        slow_ema = ema(recent, slow)
        lookback = max(2, int(cfg.get("momentum_lookback", 3)))
        ref = state.prices[-lookback - 1]
        momentum = (price / ref - 1.0) * 100 if ref > 0 else 0.0
        min_momentum = float(cfg.get("momentum_pct", 0.22))
        max_spike = max(min_momentum, float(cfg.get("max_entry_spike_pct", 0.90)))
        take_profit = float(cfg.get("take_profit_pct", 1.10))
        stop_loss = float(cfg.get("stop_loss_pct", 0.45))
        trailing = float(cfg.get("trailing_exit_pct", 0.35))
        min_exit_net_pct = max(self.round_trip_cost_pct + 0.15, float(cfg.get("min_exit_net_pct", 0.75)))

        if state.position_qty <= 0:
            trend_ok = fast_ema > slow_ema
            if trend_ok and min_momentum <= momentum <= max_spike:
                self._buy(state, price, cfg, f"enter_mom_{momentum:.2f}")
            elif momentum > max_spike:
                state.last_signal = f"skip_spike_{momentum:.2f}%"
            elif not trend_ok:
                state.last_signal = "wait_trend"
            else:
                state.last_signal = f"wait_momentum_{momentum:.2f}%"
            return

        peak = max(state.position_peak_price or state.entry_price, price)
        state.position_peak_price = peak
        move = (price / state.entry_price - 1.0) * 100
        trail_move = (price / peak - 1.0) * 100
        if move >= take_profit:
            self._sell(state, price, "take_profit")
        elif move <= -stop_loss:
            self._sell(state, price, "stop_loss")
        elif move >= min_exit_net_pct and trail_move <= -trailing:
            self._sell(state, price, "trailing_profit_exit")
        else:
            state.last_signal = f"hold_{move:.2f}%"

    def status(self, configs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        rows = []
        learning = self.learner.snapshot() if self.learner is not None else {}
        learned_states = learning.get("strategies", {}) if isinstance(learning, dict) else {}
        for name, cfg in configs.items():
            state = self._state(name)
            trades = state.completed_trades
            winrate = (state.wins / trades * 100) if trades else 0.0
            capital = max(1.0, float(cfg.get("shadow_order_eur", 6.0)))
            max_dd_pct = state.max_drawdown_eur / capital * 100
            positive_outcomes = sum(value for value in state.outcomes if value > 0)
            negative_outcomes = abs(sum(value for value in state.outcomes if value < 0))
            profit_factor = (
                positive_outcomes / negative_outcomes
                if negative_outcomes > 1e-12
                else (float("inf") if positive_outcomes > 0 else 0.0)
            )
            outcome_returns_pct = [
                (float(value) / capital) * 100.0 for value in state.outcomes
            ]
            q10_return_pct = self._percentile(outcome_returns_pct, 0.10)
            q50_return_pct = self._percentile(outcome_returns_pct, 0.50)
            q90_return_pct = self._percentile(outcome_returns_pct, 0.90)
            tail_sample_count = len(outcome_returns_pct)
            extra_stress_cost = (
                trades
                * capital
                * (self.round_trip_cost_pct / 100.0)
                * (self.cost_stress_multiplier - 1.0)
            )
            stressed_net_pnl = state.realized_net_pnl_eur - extra_stress_cost
            learned_state = (
                learned_states.get(self._learner_name(name), {})
                if isinstance(learned_states.get(self._learner_name(name), {}), dict)
                else {}
            )
            adaptive_change_pending = bool(learned_state.get("pending_change"))
            promotable = (
                trades >= self.min_completed_trades
                and state.realized_net_pnl_eur >= self.min_net_pnl_eur
                and stressed_net_pnl > 0.0
                and winrate >= self.min_winrate_pct
                and profit_factor >= self.min_profit_factor
                and tail_sample_count >= self.min_completed_trades
                and q10_return_pct >= self.min_q10_return_pct
                and max_dd_pct <= self.max_drawdown_pct
                and not adaptive_change_pending
            )

            promotion_blockers = []
            if trades < self.min_completed_trades:
                promotion_blockers.append("completed_trades")
            if state.realized_net_pnl_eur < self.min_net_pnl_eur:
                promotion_blockers.append("net_pnl")
            if stressed_net_pnl <= 0.0:
                promotion_blockers.append("stressed_net_pnl")
            if winrate < self.min_winrate_pct:
                promotion_blockers.append("winrate")
            if profit_factor < self.min_profit_factor:
                promotion_blockers.append("profit_factor")
            if tail_sample_count < self.min_completed_trades:
                promotion_blockers.append("tail_samples")
            elif q10_return_pct < self.min_q10_return_pct:
                promotion_blockers.append("tail_risk_q10")
            if max_dd_pct > self.max_drawdown_pct:
                promotion_blockers.append("drawdown")
            if adaptive_change_pending:
                promotion_blockers.append("adaptive_change_pending")

            canary_blockers = []
            if trades < self.canary_min_completed_trades:
                canary_blockers.append("completed_trades")
            if state.realized_net_pnl_eur < self.canary_min_net_pnl_eur:
                canary_blockers.append("net_pnl")
            if stressed_net_pnl <= 0.0:
                canary_blockers.append("stressed_net_pnl")
            if winrate < self.canary_min_winrate_pct:
                canary_blockers.append("winrate")
            if profit_factor < self.canary_min_profit_factor:
                canary_blockers.append("profit_factor")
            if max_dd_pct > self.canary_max_drawdown_pct:
                canary_blockers.append("drawdown")
            if adaptive_change_pending:
                canary_blockers.append("adaptive_change_pending")
            canary_ready = not canary_blockers

            # Transparent 0-100 score for comparing shadow candidates only.
            # It never authorizes live trading and deliberately rewards sample
            # maturity while penalizing drawdown and negative net performance.
            sample_score = min(100.0, trades / max(1, self.min_completed_trades) * 100.0)
            win_score = min(100.0, winrate / max(1.0, self.min_winrate_pct) * 100.0)
            pnl_scale = max(0.01, abs(self.min_net_pnl_eur))
            pnl_score = max(
                0.0,
                min(100.0, 50.0 + (state.realized_net_pnl_eur / pnl_scale) * 25.0),
            )
            drawdown_score = max(
                0.0,
                min(100.0, 100.0 - (max_dd_pct / max(0.01, self.max_drawdown_pct)) * 100.0),
            )
            score = (
                sample_score * 0.20
                + win_score * 0.30
                + pnl_score * 0.30
                + drawdown_score * 0.20
            )

            drop_ready = (
                trades >= self.min_completed_trades
                and (
                    state.realized_net_pnl_eur < 0.0
                    or winrate < max(0.0, self.min_winrate_pct - 10.0)
                    or max_dd_pct > self.max_drawdown_pct
                )
            )
            review_status = "PROMOTE" if promotable else ("DROP" if drop_ready else "KEEP")
            mark_price = state.prices[-1] if state.prices else 0.0
            position_value_eur = state.position_qty * mark_price if state.position_qty > 0 else 0.0

            rows.append({
                "name": name,
                "kind": cfg.get("kind", name),
                "symbol": cfg.get("symbol"),
                "mode": "shadow",
                "live_capable": False,
                "samples": len(state.prices),
                "position_open": state.position_qty > 0,
                "position_qty": round(state.position_qty, 10),
                "entry_price": round(state.entry_price, 8),
                "mark_price": round(mark_price, 8),
                "position_value_eur": round(position_value_eur, 4),
                "completed_trades": trades,
                "wins": state.wins,
                "losses": state.losses,
                "winrate_pct": round(winrate, 2),
                "realized_net_pnl_eur": round(state.realized_net_pnl_eur, 4),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else None,
                "tail_sample_count": tail_sample_count,
                "outcome_q10_return_pct": round(q10_return_pct, 4),
                "outcome_q50_return_pct": round(q50_return_pct, 4),
                "outcome_q90_return_pct": round(q90_return_pct, 4),
                "promotion_min_q10_return_pct": round(self.min_q10_return_pct, 4),
                "stressed_net_pnl_eur": round(stressed_net_pnl, 4),
                "cost_stress_multiplier": round(self.cost_stress_multiplier, 2),
                "adaptive_change_pending": adaptive_change_pending,
                "score": round(score, 1),
                "review_status": review_status,
                "last_signal": state.last_signal,
                "strategy_version": state.strategy_version,
                "adaptive_overrides": learned_state.get("current_overrides", {}),
                "promotable": promotable,
                "promotion_ready": promotable,
                "promotion_blockers": promotion_blockers,
                "canary_ready": canary_ready,
                "canary_blockers": canary_blockers,
                "canary_action": (
                    "lock_into_single_live_canary_slot"
                    if canary_ready else "continue_shadow_validation"
                ),
                "promotion_action": (
                    "queue_for_operator_approved_live_release"
                    if promotable else "continue_shadow_validation"
                ),
            })
        return {
            "mode": "shadow",
            "live_orders_sent": False,
            "round_trip_cost_pct": round(self.round_trip_cost_pct, 4),
            "score_method": {
                "range": "0-100",
                "weights": {
                    "sample_maturity": 0.20,
                    "winrate": 0.30,
                    "net_pnl": 0.30,
                    "drawdown": 0.20,
                },
                "purpose": "shadow_candidate_comparison_only",
                "authorizes_live_trading": False,
            },
            "auto_promotion_policy": {
                "auto_queue_when_ready": True,
                "auto_set_live_capable": False,
                "auto_send_live_orders": False,
                "operator_live_release_required": True,
            },
            "canary_rules": {
                "min_completed_trades": self.canary_min_completed_trades,
                "min_winrate_pct": self.canary_min_winrate_pct,
                "min_net_pnl_eur": self.canary_min_net_pnl_eur,
                "min_profit_factor": self.canary_min_profit_factor,
                "require_positive_stressed_net_pnl": True,
                "require_no_pending_adaptive_change": True,
                "max_drawdown_pct": self.canary_max_drawdown_pct,
            },
            "promotion_rules": {
                "min_completed_trades": self.min_completed_trades,
                "min_winrate_pct": self.min_winrate_pct,
                "min_net_pnl_eur": self.min_net_pnl_eur,
                "min_profit_factor": self.min_profit_factor,
                "min_q10_return_pct": self.min_q10_return_pct,
                "require_tail_sample_count": self.min_completed_trades,
                "cost_stress_multiplier": self.cost_stress_multiplier,
                "require_no_pending_adaptive_change": True,
                "max_drawdown_pct": self.max_drawdown_pct,
            },
            "strategies": rows,
        }
