"""Paper-only leverage and capped-martingale research lab.

This module never sends exchange orders. It simulates leveraged exposure and a
strictly capped martingale-style stake schedule so the behavior can be measured
before any separate operator-approved live implementation is considered.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class RiskLabState:
    last_price: float = 0.0
    entry_price: float = 0.0
    position_open: bool = False
    stake_eur: float = 0.0
    martingale_step: int = 0
    completed_trades: int = 0
    wins: int = 0
    losses: int = 0
    realized_net_pnl_eur: float = 0.0
    peak_equity_eur: float = 0.0
    max_drawdown_eur: float = 0.0
    last_signal: str = "warming_up"
    last_trade_at: float = 0.0


class LeverageMartingaleRiskLab:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.path = Path(str(self.config.get("path", "/data/leverage_martingale_lab.json")))
        self.starting_equity_eur = max(1.0, float(self.config.get("starting_equity_eur", 50.0)))
        self.base_stake_eur = max(1.0, float(self.config.get("base_stake_eur", 3.0)))
        self.max_stake_eur = max(self.base_stake_eur, float(self.config.get("max_stake_eur", 8.0)))
        self.leverage = max(1.0, min(3.0, float(self.config.get("leverage", 2.0))))
        self.martingale_multiplier = max(
            1.0, min(1.75, float(self.config.get("martingale_multiplier", 1.35)))
        )
        self.max_steps = max(0, min(3, int(self.config.get("max_martingale_steps", 2))))
        self.momentum_trigger_pct = max(0.01, float(self.config.get("momentum_trigger_pct", 0.20)))
        self.take_profit_pct = max(0.05, float(self.config.get("take_profit_pct", 0.75)))
        self.stop_loss_pct = max(0.05, float(self.config.get("stop_loss_pct", 0.45)))
        self.fee_pct_each_leg = max(0.0, float(self.config.get("fee_pct_each_leg", 0.25)))
        self.slippage_pct_each_leg = max(0.0, float(self.config.get("slippage_pct_each_leg", 0.05)))
        self.state = RiskLabState(stake_eur=self.base_stake_eur)
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if not isinstance(raw, dict):
            return
        allowed = RiskLabState.__dataclass_fields__.keys()
        self.state = RiskLabState(**{k: raw[k] for k in allowed if k in raw})
        if self.state.stake_eur <= 0:
            self.state.stake_eur = self.base_stake_eur

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="risk-lab-", suffix=".json", dir=str(self.path.parent))
            with os.fdopen(fd, "w") as handle:
                json.dump(asdict(self.state), handle, separators=(",", ":"))
            os.replace(tmp, self.path)
        except OSError:
            pass

    @property
    def round_trip_cost_pct(self) -> float:
        return 2.0 * (self.fee_pct_each_leg + self.slippage_pct_each_leg)

    def update(self, price: float) -> None:
        if not self.enabled or price <= 0 or not math.isfinite(price):
            return
        s = self.state
        if s.last_price <= 0:
            s.last_price = price
            s.last_signal = "warming_up"
            self._save()
            return

        move_from_last = (price / s.last_price - 1.0) * 100.0
        if not s.position_open:
            if move_from_last >= self.momentum_trigger_pct:
                s.position_open = True
                s.entry_price = price
                s.last_signal = f"enter_{move_from_last:.3f}%"
            else:
                s.last_signal = f"wait_{move_from_last:.3f}%"
            s.last_price = price
            self._save()
            return

        move = (price / s.entry_price - 1.0) * 100.0
        if move >= self.take_profit_pct:
            self._close(price, win=True, reason="take_profit")
        elif move <= -self.stop_loss_pct:
            self._close(price, win=False, reason="stop_loss")
        else:
            s.last_signal = f"hold_{move:.3f}%"
        s.last_price = price
        self._save()

    def _close(self, price: float, *, win: bool, reason: str) -> None:
        s = self.state
        if not s.position_open or s.entry_price <= 0:
            return
        raw_move = (price / s.entry_price - 1.0)
        notional = s.stake_eur * self.leverage
        gross = notional * raw_move
        costs = notional * (self.round_trip_cost_pct / 100.0)
        net = gross - costs
        s.realized_net_pnl_eur += net
        s.completed_trades += 1
        if net > 0:
            s.wins += 1
            s.martingale_step = 0
            s.stake_eur = self.base_stake_eur
        else:
            s.losses += 1
            if s.martingale_step < self.max_steps:
                s.martingale_step += 1
                s.stake_eur = min(
                    self.max_stake_eur,
                    max(self.base_stake_eur, s.stake_eur * self.martingale_multiplier),
                )
            else:
                s.martingale_step = 0
                s.stake_eur = self.base_stake_eur
        equity = self.starting_equity_eur + s.realized_net_pnl_eur
        s.peak_equity_eur = max(s.peak_equity_eur, equity)
        if s.peak_equity_eur > 0:
            s.max_drawdown_eur = max(s.max_drawdown_eur, s.peak_equity_eur - equity)
        s.position_open = False
        s.entry_price = 0.0
        s.last_trade_at = time.time()
        s.last_signal = f"{reason}_{net:.4f}"

    def status(self) -> dict[str, Any]:
        s = self.state
        winrate = (s.wins / s.completed_trades * 100.0) if s.completed_trades else 0.0
        max_dd_pct = (
            s.max_drawdown_eur / self.starting_equity_eur * 100.0
            if self.starting_equity_eur > 0 else 0.0
        )
        return {
            "mode": "shadow_risk_lab",
            "live_capable": False,
            "live_orders_sent": False,
            "leverage": self.leverage,
            "martingale_multiplier": self.martingale_multiplier,
            "max_martingale_steps": self.max_steps,
            "base_stake_eur": self.base_stake_eur,
            "current_stake_eur": round(s.stake_eur, 2),
            "max_stake_eur": self.max_stake_eur,
            "completed_trades": s.completed_trades,
            "wins": s.wins,
            "losses": s.losses,
            "winrate_pct": round(winrate, 2),
            "realized_net_pnl_eur": round(s.realized_net_pnl_eur, 4),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "position_open": s.position_open,
            "last_signal": s.last_signal,
            "promotion_ready": False,
            "note": "Research only: leverage and martingale-style sizing remain non-live.",
        }
