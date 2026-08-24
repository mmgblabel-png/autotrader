"""Profit Engine – tracks PnL, fees, and win-rate per strategy."""

from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List

from autotrader.core.logger import get_logger

log = get_logger("ProfitEngine")

# Fire an event when a single realized-PnL change exceeds this USD amount
_LARGE_PNL_THRESHOLD = 10.0


@dataclass
class Trade:
    strategy: str
    symbol: str
    side: str          # BUY / SELL
    quantity: float
    price: float
    fee: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def notional(self) -> float:
        return self.quantity * self.price

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "notional": self.notional,
            "fee": self.fee,
            "timestamp": self.timestamp,
        }


@dataclass
class StrategyStats:
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees: float = 0.0
    wins: int = 0
    losses: int = 0
    trades: List[Trade] = field(default_factory=list)

    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total else 0.0

    @property
    def net_pnl(self) -> float:
        return self.realized_pnl - self.total_fees


class ProfitEngine:
    """Aggregates trade results and exports reports."""

    def __init__(self, export_dir: str = "exports") -> None:
        self._stats: Dict[str, StrategyStats] = {}
        self._export_dir = export_dir
        self._events: List[dict] = []          # event log (risk + large PnL)
        os.makedirs(export_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_trade(self, trade: Trade) -> None:
        stats = self._ensure(trade.strategy)
        stats.trades.append(trade)
        stats.total_fees += trade.fee
        log.info("[%s] Trade recorded: %s %s %.4f @ %.4f (fee=%.4f)",
                 trade.strategy, trade.side, trade.symbol, trade.quantity, trade.price, trade.fee)

    def record_realized_pnl(self, strategy: str, pnl: float) -> None:
        stats = self._ensure(strategy)
        stats.realized_pnl += pnl
        if pnl >= 0:
            stats.wins += 1
        else:
            stats.losses += 1
        log.info("[%s] Realized PnL: %.4f (total=%.4f)", strategy, pnl, stats.realized_pnl)

        if abs(pnl) >= _LARGE_PNL_THRESHOLD:
            self._add_event("large_pnl", strategy,
                            f"Large PnL movement: {pnl:+.4f} USD (total={stats.realized_pnl:.4f})")

    def update_unrealized_pnl(self, strategy: str, pnl: float) -> None:
        self._ensure(strategy).unrealized_pnl = pnl

    def add_risk_event(self, strategy: str, message: str) -> None:
        """Called by RiskManager to surface risk events in the event log."""
        self._add_event("risk", strategy, message)

    # ------------------------------------------------------------------
    # Dashboard queries
    # ------------------------------------------------------------------

    def as_summary(self) -> dict:
        """Return a single dashboard-ready dict.

        Shape::

            {
                "total_pnl": 42.5,
                "total_fees": 1.2,
                "trade_count": 18,
                "by_strategy": {
                    "MarketMaker": {"net_pnl": ..., "winrate_pct": ..., ...},
                    ...
                }
            }
        """
        by_strategy = self.summary()
        total_pnl = sum(s["net_pnl"] for s in by_strategy.values())
        total_fees = sum(s["total_fees"] for s in by_strategy.values())
        trade_count = sum(s["num_trades"] for s in by_strategy.values())
        return {
            "total_pnl": round(total_pnl, 4),
            "total_fees": round(total_fees, 4),
            "trade_count": trade_count,
            "by_strategy": by_strategy,
        }

    def recent_trades(self, limit: int = 50) -> List[dict]:
        """Return the most recent ``limit`` trades across all strategies."""
        all_trades: List[Trade] = []
        for s in self._stats.values():
            all_trades.extend(s.trades)
        all_trades.sort(key=lambda t: t.timestamp, reverse=True)
        return [t.as_dict() for t in all_trades[:limit]]

    def events(self, limit: int = 100) -> List[dict]:
        """Return the most recent ``limit`` events (risk + large PnL)."""
        return list(reversed(self._events[-limit:]))

    def summary(self) -> Dict[str, dict]:
        return {
            strat: {
                "realized_pnl": s.realized_pnl,
                "unrealized_pnl": s.unrealized_pnl,
                "net_pnl": s.net_pnl,
                "total_fees": s.total_fees,
                "wins": s.wins,
                "losses": s.losses,
                "winrate_pct": round(s.winrate, 2),
                "num_trades": len(s.trades),
            }
            for strat, s in self._stats.items()
        }

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    def export_json(self, filename: str = "pnl_report.json") -> str:
        path = os.path.join(self._export_dir, filename)
        with open(path, "w") as f:
            json.dump(self.as_summary(), f, indent=2)
        log.info("PnL report exported to %s", path)
        return path

    def export_csv(self, filename: str = "pnl_report.csv") -> str:
        path = os.path.join(self._export_dir, filename)
        rows = []
        for strat, s in self._stats.items():
            for t in s.trades:
                rows.append({
                    "strategy": strat,
                    "symbol": t.symbol,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                    "notional": t.notional,
                    "fee": t.fee,
                    "timestamp": t.timestamp,
                })
        if rows:
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
        log.info("Trade log exported to %s", path)
        return path

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _ensure(self, strategy: str) -> StrategyStats:
        if strategy not in self._stats:
            self._stats[strategy] = StrategyStats()
        return self._stats[strategy]

    def _add_event(self, kind: str, strategy: str, message: str) -> None:
        self._events.append({
            "timestamp": time.time(),
            "kind": kind,
            "strategy": strategy,
            "message": message,
        })
