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
        return {
            "mean_reversion": "MeanReversionShadow",
            "volatility_breakout": "VolatilityBreakoutShadow",
        }.get(name, name)

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

    @property
    def round_trip_cost_pct(self) -> float:
        return 2.0 * (self.fee_pct + self.slippage_pct)

    def update(self, name: str, price: float, cfg: dict[str, Any]) -> None:
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
        if self.learner is not None and state.completed_trades > before_trades and state.outcomes:
            self.learner.record_realized_outcome(
                strategy_name=learner_name,
                side="SELL",
                net_pnl_delta_eur=float(state.outcomes[-1]),
                strategy_config=cfg,
                symbol=str(cfg.get("symbol", "")),
                outcome_key=f"shadow:{name}:{state.strategy_version}:{state.completed_trades}",
            )
        self._save()

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
        state.last_signal = signal
        state.last_trade_at = time.time()

    def _mean_reversion(self, state: ShadowStats, price: float, cfg: dict[str, Any]) -> None:
        lookback = max(8, int(cfg.get("lookback", 30)))
        if len(state.prices) < lookback:
            state.last_signal = "warming_up"
            return
        window = state.prices[-lookback:]
        mean = statistics.fmean(window)
        stdev = statistics.pstdev(window)
        z = (price - mean) / stdev if stdev > 1e-12 else 0.0
        entry_z = -abs(float(cfg.get("entry_z", 1.6)))
        exit_z = float(cfg.get("exit_z", -0.15))
        take_profit = float(cfg.get("take_profit_pct", 1.2))
        stop_loss = float(cfg.get("stop_loss_pct", 1.0))
        if state.position_qty <= 0:
            if z <= entry_z:
                self._buy(state, price, cfg, f"buy_z_{z:.2f}")
            else:
                state.last_signal = f"wait_z_{z:.2f}"
            return
        move = (price / state.entry_price - 1) * 100
        if z >= exit_z or move >= take_profit:
            self._sell(state, price, f"mean_exit_{z:.2f}")
        elif move <= -stop_loss:
            self._sell(state, price, "stop_loss")
        else:
            state.last_signal = f"hold_{move:.2f}%"

    def _volatility_breakout(self, state: ShadowStats, price: float, cfg: dict[str, Any]) -> None:
        lookback = max(10, int(cfg.get("lookback", 24)))
        if len(state.prices) <= lookback:
            state.last_signal = "warming_up"
            return
        previous = state.prices[-lookback-1:-1]
        breakout = max(previous) * (1 + float(cfg.get("breakout_buffer_pct", 0.12)) / 100)
        returns = [
            abs(previous[i] / previous[i - 1] - 1) * 100
            for i in range(1, len(previous))
            if previous[i - 1] > 0
        ]
        avg_move = statistics.fmean(returns) if returns else 0.0
        min_vol = float(cfg.get("min_avg_move_pct", 0.03))
        take_profit = float(cfg.get("take_profit_pct", 1.4))
        stop_loss = float(cfg.get("stop_loss_pct", 0.7))
        trailing = float(cfg.get("trailing_exit_pct", 0.45))
        if state.position_qty <= 0:
            if price >= breakout and avg_move >= min_vol:
                self._buy(state, price, cfg, f"breakout_{avg_move:.3f}")
                cfg["_shadow_peak_price"] = price
            else:
                state.last_signal = f"wait_vol_{avg_move:.3f}"
            return
        peak = max(float(cfg.get("_shadow_peak_price", state.entry_price)), price)
        cfg["_shadow_peak_price"] = peak
        move = (price / state.entry_price - 1) * 100
        trail_move = (price / peak - 1) * 100
        if move >= take_profit:
            self._sell(state, price, "take_profit")
        elif move <= -stop_loss:
            self._sell(state, price, "stop_loss")
        elif trail_move <= -trailing and move > 0:
            self._sell(state, price, "trailing_exit")
        else:
            state.last_signal = f"hold_{move:.2f}%"

    def status(self, configs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        rows = []
        for name, cfg in configs.items():
            state = self._state(name)
            trades = state.completed_trades
            winrate = (state.wins / trades * 100) if trades else 0.0
            capital = max(1.0, float(cfg.get("shadow_order_eur", 6.0)))
            max_dd_pct = state.max_drawdown_eur / capital * 100
            promotable = (
                trades >= self.min_completed_trades
                and state.realized_net_pnl_eur >= self.min_net_pnl_eur
                and winrate >= self.min_winrate_pct
                and max_dd_pct <= self.max_drawdown_pct
            )
            rows.append({
                "name": name,
                "kind": cfg.get("kind", name),
                "symbol": cfg.get("symbol"),
                "mode": "shadow",
                "live_capable": False,
                "samples": len(state.prices),
                "position_open": state.position_qty > 0,
                "completed_trades": trades,
                "wins": state.wins,
                "losses": state.losses,
                "winrate_pct": round(winrate, 2),
                "realized_net_pnl_eur": round(state.realized_net_pnl_eur, 4),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "last_signal": state.last_signal,
                "promotable": promotable,
            })
        return {
            "mode": "shadow",
            "live_orders_sent": False,
            "round_trip_cost_pct": round(self.round_trip_cost_pct, 4),
            "promotion_rules": {
                "min_completed_trades": self.min_completed_trades,
                "min_winrate_pct": self.min_winrate_pct,
                "min_net_pnl_eur": self.min_net_pnl_eur,
                "max_drawdown_pct": self.max_drawdown_pct,
            },
            "strategies": rows,
        }
