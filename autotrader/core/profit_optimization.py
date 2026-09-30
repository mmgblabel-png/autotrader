"""Read-only profit optimization services for live/shadow evaluation.

Nothing in this module sends, cancels, replaces, or arms live orders. It exists
to measure opportunity quality, stale-order execution quality, and fee drag
before any future live rollout is explicitly approved.
"""
from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarketSnapshot:
    market: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    mid: float
    spread_bps: float
    momentum_pct: float
    volatility_pct: float
    liquidity_eur: float


class OpportunityRouter:
    """Rank allowlisted EUR markets from executable public top-of-book data."""

    def __init__(self, adapter, config: dict[str, Any] | None = None) -> None:
        self.adapter = adapter
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        raw = self.config.get(
            "markets",
            ["BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR", "ADA-EUR", "LINK-EUR"],
        )
        self.markets = [str(x).upper() for x in raw]
        self.history_size = max(8, min(240, int(self.config.get("history_size", 48))))
        self.min_top_depth_eur = max(5.0, float(self.config.get("min_top_depth_eur", 25.0)))
        self.max_spread_bps = max(1.0, float(self.config.get("max_spread_bps", 35.0)))
        self._history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.history_size))
        self._latest: dict[str, MarketSnapshot] = {}
        self._last_error: dict[str, str] = {}
        self.updated_at = 0.0

    def refresh(self) -> None:
        latest: dict[str, MarketSnapshot] = {}
        errors: dict[str, str] = {}
        for market in self.markets:
            try:
                book = self.adapter.ticker_book(market)
                bid = float(book["bid"])
                ask = float(book["ask"])
                bid_size = float(book["bid_size"])
                ask_size = float(book["ask_size"])
                mid = (bid + ask) / 2.0
                spread_bps = ((ask - bid) / mid * 10000.0) if mid > 0 else 0.0
                hist = self._history[market]
                hist.append(mid)
                momentum_pct = 0.0
                volatility_pct = 0.0
                if len(hist) >= 4 and hist[-4] > 0:
                    momentum_pct = (hist[-1] / hist[-4] - 1.0) * 100.0
                if len(hist) >= 6:
                    returns = [
                        (hist[i] / hist[i - 1] - 1.0) * 100.0
                        for i in range(1, len(hist))
                        if hist[i - 1] > 0
                    ]
                    volatility_pct = statistics.pstdev(returns[-12:]) if len(returns) >= 2 else 0.0
                liquidity_eur = min(bid * bid_size, ask * ask_size)
                latest[market] = MarketSnapshot(
                    market=market,
                    bid=bid,
                    ask=ask,
                    bid_size=bid_size,
                    ask_size=ask_size,
                    mid=mid,
                    spread_bps=spread_bps,
                    momentum_pct=momentum_pct,
                    volatility_pct=volatility_pct,
                    liquidity_eur=liquidity_eur,
                )
            except Exception as exc:
                errors[market] = type(exc).__name__
        self._latest = latest
        self._last_error = errors
        self.updated_at = time.time()

    def _features(self, snap: MarketSnapshot) -> dict[str, float]:
        spread_quality = max(0.0, min(100.0, 100.0 * (1.0 - snap.spread_bps / self.max_spread_bps)))
        liquidity = max(0.0, min(100.0, snap.liquidity_eur / self.min_top_depth_eur * 100.0))
        momentum = max(0.0, min(100.0, 50.0 + snap.momentum_pct * 40.0))
        volatility_quality = max(0.0, min(100.0, 100.0 - abs(snap.volatility_pct - 0.18) * 220.0))
        trend = max(0.0, min(100.0, 50.0 + snap.momentum_pct * 55.0))
        return {
            "trend": trend,
            "momentum": momentum,
            "volatility_quality": volatility_quality,
            "liquidity": liquidity,
            "spread_quality": spread_quality,
        }

    @staticmethod
    def _weighted(features: dict[str, float], weights: dict[str, float]) -> float:
        return sum(features.get(k, 0.0) * v for k, v in weights.items())

    def rankings(self) -> dict[str, Any]:
        profiles = {
            "market_maker": {"spread_quality": 0.35, "liquidity": 0.35, "volatility_quality": 0.20, "trend": 0.10},
            "grid": {"volatility_quality": 0.35, "liquidity": 0.25, "spread_quality": 0.20, "momentum": 0.20},
            "sniper": {"momentum": 0.40, "trend": 0.30, "liquidity": 0.20, "spread_quality": 0.10},
            "mean_reversion": {"volatility_quality": 0.35, "liquidity": 0.25, "spread_quality": 0.20, "trend": 0.20},
            "volatility_breakout": {"momentum": 0.35, "volatility_quality": 0.30, "liquidity": 0.25, "spread_quality": 0.10},
        }
        by_strategy: dict[str, list[dict[str, Any]]] = {}
        for strategy, weights in profiles.items():
            rows = []
            for snap in self._latest.values():
                features = self._features(snap)
                score = self._weighted(features, weights)
                eligible = (
                    snap.liquidity_eur >= self.min_top_depth_eur
                    and snap.spread_bps <= self.max_spread_bps
                )
                rows.append({
                    "market": snap.market,
                    "score": round(score, 2),
                    "eligible": eligible,
                    "mid": round(snap.mid, 10),
                    "spread_bps": round(snap.spread_bps, 3),
                    "liquidity_eur": round(snap.liquidity_eur, 2),
                    "momentum_pct": round(snap.momentum_pct, 4),
                    "volatility_pct": round(snap.volatility_pct, 4),
                    "features": {k: round(v, 2) for k, v in features.items()},
                })
            by_strategy[strategy] = sorted(rows, key=lambda x: (x["eligible"], x["score"]), reverse=True)
        return {
            "mode": "read_only_shadow",
            "live_orders_sent": False,
            "updated_at": self.updated_at,
            "markets_scanned": len(self._latest),
            "errors": self._last_error,
            "rankings": by_strategy,
        }


class ExecutionV2Advisor:
    """Recommend maker-first repricing for stale orders without executing it."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.apply_live = bool(self.config.get("apply_live", False))
        self.stale_after_seconds = max(30.0, float(self.config.get("stale_after_seconds", 180.0)))
        self.min_move_bps = max(0.1, float(self.config.get("min_reprice_move_bps", 4.0)))
        self.max_order_age_seconds = max(
            self.stale_after_seconds,
            float(self.config.get("max_order_age_seconds", 900.0)),
        )

    def evaluate(
        self,
        activity: list[dict[str, Any]],
        books: dict[str, dict[str, float]],
        min_profit_exit_by_strategy: dict[str, float],
        target_edge_by_strategy: dict[str, float],
        required_entry_edge_pct: float,
    ) -> dict[str, Any]:
        now = time.time()
        rows: list[dict[str, Any]] = []
        for order in activity:
            status = str(order.get("status") or "").lower()
            if status not in {"new", "open", "submitted", "partially_filled"}:
                continue
            market = str(order.get("market") or "").upper()
            side = str(order.get("side") or "").lower()
            strategy = str(order.get("strategy") or "unassigned")
            old_price = float(order.get("price") or 0)
            created_at = float(order.get("created_at") or now)
            age = max(0.0, now - created_at)
            book = books.get(market)
            if not book or old_price <= 0:
                continue
            target = float(book["bid"] if side == "buy" else book["ask"])
            move_bps = abs(target - old_price) / old_price * 10000.0
            target_edge = float(target_edge_by_strategy.get(strategy, 0.0))
            min_exit = float(min_profit_exit_by_strategy.get(strategy, 0.0))
            profit_ok = True
            reason = "fresh"
            if side == "buy":
                profit_ok = target_edge >= required_entry_edge_pct
            elif side == "sell" and min_exit > 0:
                profit_ok = target >= min_exit
            stale = age >= self.stale_after_seconds
            too_old = age >= self.max_order_age_seconds
            should_reprice = stale and move_bps >= self.min_move_bps and profit_ok
            if not profit_ok:
                reason = "profit_guard_blocks_reprice"
            elif should_reprice:
                reason = "maker_reprice_recommended"
            elif too_old:
                reason = "stale_but_no_safe_reprice"
            elif stale:
                reason = "stale_price_still_competitive"
            rows.append({
                "strategy": strategy,
                "market": market,
                "side": side,
                "age_seconds": round(age, 1),
                "current_limit_price": old_price,
                "maker_target_price": target,
                "move_bps": round(move_bps, 3),
                "profit_guard_passed": profit_ok,
                "recommend_reprice": should_reprice,
                "reason": reason,
            })
        return {
            "enabled": self.enabled,
            "mode": "advisory",
            "apply_live": self.apply_live,
            "orders": rows,
            "live_orders_changed": False,
        }


def fee_efficiency_rows(strategy_snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for snap in strategy_snapshots:
        net = float(snap.get("realized_net_pnl_eur") or 0.0)
        fees = float(snap.get("fees_quote_equivalent_eur") or 0.0)
        wins = int(snap.get("profitable_exits") or 0)
        losses = int(snap.get("losing_exits") or 0)
        exits = wins + losses
        gross_before_fees = net + fees
        fee_drag_pct = (fees / gross_before_fees * 100.0) if gross_before_fees > 0 else None
        net_per_exit = net / exits if exits else 0.0
        if exits == 0:
            state = "insufficient_data"
        elif net <= 0:
            state = "net_negative"
        elif fee_drag_pct is not None and fee_drag_pct > 50:
            state = "fee_heavy"
        else:
            state = "efficient"
        rows.append({
            "strategy": snap.get("strategy"),
            "market": snap.get("market"),
            "realized_net_pnl_eur": round(net, 6),
            "fees_eur": round(fees, 6),
            "completed_exits": exits,
            "net_per_exit_eur": round(net_per_exit, 6),
            "fee_drag_pct": round(fee_drag_pct, 2) if fee_drag_pct is not None else None,
            "state": state,
        })
    return {"rows": rows, "live_changes": False}
