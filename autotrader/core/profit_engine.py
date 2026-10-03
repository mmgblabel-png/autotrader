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
    fee_currency: str = ""
    fill_key: str = ""
    quote_to_eur: float = 1.0
    timestamp: float = field(default_factory=time.time)
    _recorded_order: int = field(default=-1, init=False, repr=False, compare=False)

    @property
    def notional(self) -> float:
        return self.quantity * self.price

    @property
    def notional_eur(self) -> float:
        return self.notional * max(0.0, float(self.quote_to_eur or 0.0))

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "notional": self.notional,
            "notional_eur": self.notional_eur,
            "quote_to_eur": self.quote_to_eur,
            "fee": self.fee,
            "fee_currency": self.fee_currency,
            "timestamp": self.timestamp,
        }


@dataclass
class PositionCost:
    quantity: float = 0.0
    cost: float = 0.0

    @property
    def average_price(self) -> float:
        return self.cost / self.quantity if self.quantity > 0 else 0.0


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
        self._trade_sequence = 0
        self._positions: Dict[tuple[str, str], PositionCost] = {}
        self._seen_trade_keys: set[str] = set()
        os.makedirs(export_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_trade(self, trade: Trade) -> float:
        """Record a fill and return the fill's risk-PnL delta after its fee.

        BUY fills build average-cost inventory and return only their fee as a
        negative risk delta. SELL fills realize PnL only
        against inventory already owned by the same strategy and symbol. Fees
        are converted to quote-currency value and remain separate so net_pnl
        stays realized_pnl minus fees.
        """
        if trade.fill_key and trade.fill_key in self._seen_trade_keys:
            return 0.0
        stats = self._ensure(trade.strategy)
        if trade.fill_key:
            self._seen_trade_keys.add(trade.fill_key)
        trade._recorded_order = self._trade_sequence
        self._trade_sequence += 1
        stats.trades.append(trade)

        symbol = trade.symbol.upper().replace("/", "-")
        parts = symbol.split("-", 1)
        base = parts[0]
        quote = parts[1] if len(parts) == 2 else ""
        fee_currency = (trade.fee_currency or quote).upper()
        fee = abs(float(trade.fee or 0.0))
        quote_to_eur = max(0.0, float(trade.quote_to_eur or 0.0))
        if quote == "EUR":
            quote_to_eur = 1.0
        if quote_to_eur <= 0:
            self._add_event(
                "accounting",
                trade.strategy,
                f"Missing quote-to-EUR valuation for {symbol}; fill PnL was not fabricated.",
            )
            return 0.0

        if fee_currency == base:
            fee_eur = fee * trade.price * quote_to_eur
        elif not fee_currency or fee_currency == quote:
            fee_eur = fee * quote_to_eur
        elif fee_currency == "EUR":
            fee_eur = fee
        else:
            fee_eur = 0.0
            if fee > 0:
                self._add_event(
                    "accounting",
                    trade.strategy,
                    f"Fee currency {fee_currency} for {symbol} could not be converted to EUR.",
                )
        stats.total_fees += fee_eur

        key = (trade.strategy, symbol)
        position = self._positions.setdefault(key, PositionCost())
        realized = 0.0
        side = trade.side.upper()
        amount = max(0.0, float(trade.quantity))
        price = max(0.0, float(trade.price))
        price_eur = price * quote_to_eur

        if side == "BUY" and amount > 0 and price > 0:
            base_fee = fee if fee_currency == base else 0.0
            received = max(0.0, amount - base_fee)
            position.quantity += received
            position.cost += received * price_eur
        elif side == "SELL" and amount > 0 and price > 0:
            if position.quantity <= 0:
                self._add_event(
                    "accounting",
                    trade.strategy,
                    f"Unmatched SELL fill for {symbol}; realized PnL was not fabricated.",
                )
            else:
                avg = position.average_price
                base_fee = fee if fee_currency == base else 0.0
                outgoing = min(position.quantity, amount + base_fee)
                # For a base-asset fee, model the fee unit as inventory that
                # exits at the current mark, then subtract its quote value
                # through total_fees. This avoids double-counting its cost.
                realized = outgoing * (price_eur - avg)
                position.quantity -= outgoing
                position.cost = max(0.0, position.cost - avg * outgoing)
                if position.quantity <= 1e-15:
                    position.quantity = 0.0
                    position.cost = 0.0
                stats.realized_pnl += realized
                if realized > 0:
                    stats.wins += 1
                elif realized < 0:
                    stats.losses += 1
                if abs(realized) >= _LARGE_PNL_THRESHOLD:
                    self._add_event(
                        "large_pnl",
                        trade.strategy,
                        f"Large realized PnL movement: {realized:+.4f} EUR.",
                    )

        risk_pnl_delta = realized - fee_eur
        log.info(
            "[%s] Trade recorded: %s %s %.8f @ %.8f quote_to_eur=%.8f (fee=%.8f %s realized_eur=%+.4f risk_delta_eur=%+.4f)",
            trade.strategy, trade.side, trade.symbol, trade.quantity, trade.price,
            quote_to_eur, trade.fee, fee_currency, realized, risk_pnl_delta,
        )
        return risk_pnl_delta

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

    def mark_to_market(
        self,
        strategy: str,
        symbol: str,
        price: float,
        *,
        quote_to_eur: float = 1.0,
    ) -> float:
        """Update unrealized PnL in EUR for one strategy/symbol."""
        key = (strategy, symbol.upper().replace("/", "-"))
        position = self._positions.get(key)
        rate = 1.0 if key[1].endswith("-EUR") else max(0.0, float(quote_to_eur or 0.0))
        if position is None or position.quantity <= 0 or price <= 0 or rate <= 0:
            self._ensure(strategy).unrealized_pnl = 0.0
            return 0.0
        price_eur = float(price) * rate
        pnl = position.quantity * (price_eur - position.average_price)
        self._ensure(strategy).unrealized_pnl = pnl
        return pnl

    def position_state(self, strategy: str, symbol: str) -> dict[str, float]:
        position = self._positions.get((strategy, symbol.upper().replace("/", "-")), PositionCost())
        return {
            "quantity": position.quantity,
            "average_price": position.average_price,
            "cost": position.cost,
        }

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
                "pnl_per_strategy": {"MarketMaker": 10.0, ...},
                "total_fees": 1.2,
                "trade_count": 18,
                "by_strategy": {
                    "MarketMaker": {"net_pnl": ..., "winrate_pct": ..., ...},
                    ...
                }
            }
        """
        by_strategy = self.summary()
        return {
            "total_pnl": self.total_pnl(),
            "pnl_per_strategy": self.pnl_per_strategy(),
            "total_fees": round(sum(s["total_fees"] for s in by_strategy.values()), 4),
            "trade_count": len(list(
                t for s in self._stats.values() for t in s.trades
            )),
            "by_strategy": by_strategy,
        }

    def recent_trades(self, limit: int = 50) -> List[dict]:
        """Return the most recent ``limit`` trades across all strategies."""
        all_trades: List[Trade] = []
        for s in self._stats.values():
            all_trades.extend(s.trades)
        all_trades.sort(
            key=lambda t: (t.timestamp, t._recorded_order),
            reverse=True,
        )
        return [t.as_dict() for t in all_trades[:limit]]

    def events(self, limit: int = 100) -> List[dict]:
        """Return the most recent ``limit`` events (risk + large PnL)."""
        return list(reversed(self._events[-limit:]))

    def last_trades(self, n: int) -> List[dict]:
        """Return the last ``n`` trades across all strategies (alias for ``recent_trades``)."""
        return self.recent_trades(limit=n)

    def total_pnl(self) -> float:
        """Return aggregate net PnL across all strategies."""
        return round(sum(s.net_pnl for s in self._stats.values()), 4)

    def pnl_per_strategy(self) -> Dict[str, float]:
        """Return {strategy: net_pnl} mapping."""
        return {k: round(s.net_pnl, 4) for k, s in self._stats.items()}

    def summary(self) -> Dict[str, dict]:
        """Return per-strategy stats dict (used internally and by tests)."""
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
