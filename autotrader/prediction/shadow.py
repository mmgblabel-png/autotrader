"""Persistent settlement-based shadow ledger for Polymarket BTC Up/Down."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ShadowPosition:
    market_slug: str
    side: str
    stake: float
    entry_price: float
    probability: float
    expected_edge: float
    fee_bps: float
    opened_at: float
    window_end: float
    strike: float


@dataclass
class ShadowStats:
    bankroll_start: float = 80.0
    realized_pnl: float = 0.0
    settled_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    peak_equity: float = 80.0
    max_drawdown: float = 0.0
    positions: dict[str, ShadowPosition] = field(default_factory=dict)
    settled_markets: list[str] = field(default_factory=list)


class PolymarketShadowLedger:
    """Atomic JSON ledger.  It cannot place, sign, cancel or submit orders."""

    def __init__(
        self,
        path: str | Path,
        *,
        bankroll_start: float = 80.0,
        promotion_min_trades: int = 200,
        promotion_min_profit_factor: float = 1.20,
        promotion_max_drawdown_pct: float = 8.0,
    ) -> None:
        self.path = Path(path)
        self.promotion_min_trades = max(20, int(promotion_min_trades))
        self.promotion_min_profit_factor = max(1.0, float(promotion_min_profit_factor))
        self.promotion_max_drawdown_pct = max(0.1, float(promotion_max_drawdown_pct))
        self.stats = ShadowStats(bankroll_start=max(1.0, float(bankroll_start)), peak_equity=max(1.0, float(bankroll_start)))
        self._load()

    @property
    def equity(self) -> float:
        return self.stats.bankroll_start + self.stats.realized_pnl

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        stats = raw.get("stats") if isinstance(raw, dict) else None
        if not isinstance(stats, dict):
            return
        positions: dict[str, ShadowPosition] = {}
        for slug, row in (stats.get("positions") or {}).items():
            if isinstance(row, dict):
                try:
                    positions[str(slug)] = ShadowPosition(**row)
                except TypeError:
                    continue
        for key in (
            "bankroll_start", "realized_pnl", "settled_trades", "wins", "losses",
            "gross_profit", "gross_loss", "peak_equity", "max_drawdown", "settled_markets",
        ):
            if key in stats:
                setattr(self.stats, key, stats[key])
        self.stats.positions = positions
        self.stats.settled_markets = [str(x) for x in self.stats.settled_markets][-2000:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"stats": asdict(self.stats), "live_orders_sent": False, "mode": "shadow"}
        fd, tmp = tempfile.mkstemp(prefix="polymarket-shadow-", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def can_open(self, market_slug: str) -> bool:
        return market_slug not in self.stats.positions and market_slug not in self.stats.settled_markets

    def open(self, position: ShadowPosition) -> bool:
        if position.side not in {"UP", "DOWN"}:
            raise ValueError("position side must be UP or DOWN")
        if position.stake <= 0 or not 0 < position.entry_price < 1:
            raise ValueError("invalid shadow position economics")
        if not self.can_open(position.market_slug):
            return False
        if position.stake > max(0.0, self.equity):
            return False
        self.stats.positions[position.market_slug] = position
        self.save()
        return True

    def settle(self, market_slug: str, settlement_price: float) -> float | None:
        position = self.stats.positions.get(market_slug)
        if position is None:
            return None
        won = settlement_price >= position.strike if position.side == "UP" else settlement_price < position.strike
        shares = position.stake / position.entry_price
        entry_fee = position.stake * max(0.0, position.fee_bps) / 10_000.0
        payout = shares if won else 0.0
        pnl = payout - position.stake - entry_fee
        self.stats.realized_pnl += pnl
        self.stats.settled_trades += 1
        self.stats.wins += int(pnl > 0)
        self.stats.losses += int(pnl <= 0)
        if pnl > 0:
            self.stats.gross_profit += pnl
        else:
            self.stats.gross_loss += abs(pnl)
        equity = self.equity
        self.stats.peak_equity = max(self.stats.peak_equity, equity)
        self.stats.max_drawdown = max(self.stats.max_drawdown, self.stats.peak_equity - equity)
        self.stats.positions.pop(market_slug, None)
        self.stats.settled_markets.append(market_slug)
        self.stats.settled_markets = self.stats.settled_markets[-2000:]
        self.save()
        return pnl

    def status(self) -> dict[str, Any]:
        trades = int(self.stats.settled_trades)
        profit_factor = (
            self.stats.gross_profit / self.stats.gross_loss
            if self.stats.gross_loss > 0
            else (float("inf") if self.stats.gross_profit > 0 else 0.0)
        )
        drawdown_pct = self.stats.max_drawdown / max(self.stats.peak_equity, 1e-9) * 100.0
        promotion_ready = bool(
            trades >= self.promotion_min_trades
            and self.stats.realized_pnl > 0
            and profit_factor >= self.promotion_min_profit_factor
            and drawdown_pct <= self.promotion_max_drawdown_pct
        )
        return {
            "mode": "shadow",
            "live_orders_sent": False,
            "bankroll_start": round(self.stats.bankroll_start, 8),
            "equity": round(self.equity, 8),
            "realized_pnl": round(self.stats.realized_pnl, 8),
            "settled_trades": trades,
            "wins": self.stats.wins,
            "losses": self.stats.losses,
            "winrate_pct": round(self.stats.wins / trades * 100.0, 4) if trades else 0.0,
            "profit_factor": None if profit_factor == float("inf") else round(profit_factor, 6),
            "max_drawdown_pct": round(drawdown_pct, 6),
            "open_positions": [asdict(row) for row in self.stats.positions.values()],
            "promotion_ready": promotion_ready,
            "promotion_policy": {
                "min_settled_trades": self.promotion_min_trades,
                "min_profit_factor": self.promotion_min_profit_factor,
                "max_drawdown_pct": self.promotion_max_drawdown_pct,
                "positive_realized_pnl_required": True,
                "automatic_live_promotion": False,
            },
        }
