"""Read-only profit optimization services for live/shadow evaluation.

Nothing in this module sends, cancels, replaces, or arms live orders. It exists
to measure opportunity quality, stale-order execution quality, and fee drag
before any future live rollout is explicitly approved.
"""
from __future__ import annotations

import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable


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
        self.auto_discover_eur = bool(self.config.get("auto_discover_eur", False))
        self.max_markets = max(1, min(100, int(self.config.get("max_markets", 60))))
        self.discovery_refresh_seconds = max(
            60.0, float(self.config.get("discovery_refresh_seconds", 1800.0))
        )
        self._last_discovery_at = 0.0
        self.history_size = max(8, min(240, int(self.config.get("history_size", 48))))
        self.min_top_depth_eur = max(5.0, float(self.config.get("min_top_depth_eur", 25.0)))
        self.max_spread_bps = max(1.0, float(self.config.get("max_spread_bps", 35.0)))
        self._history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.history_size))
        self._latest: dict[str, MarketSnapshot] = {}
        self._last_error: dict[str, str] = {}
        self.updated_at = 0.0

    def _discover_markets(self) -> None:
        if not self.auto_discover_eur:
            return
        now = time.time()
        if self._last_discovery_at and now - self._last_discovery_at < self.discovery_refresh_seconds:
            return
        discovered: list[str] = []
        try:
            for row in self.adapter.markets():
                if not isinstance(row, dict):
                    continue
                market = str(row.get("market") or row.get("symbol") or "").upper()
                status = str(row.get("status") or "trading").lower()
                if market.endswith("-EUR") and status == "trading":
                    discovered.append(market)
        except Exception:
            return
        preferred = []
        for market in self.markets:
            if market not in preferred:
                preferred.append(market)
        for market in sorted(set(discovered)):
            if market not in preferred:
                preferred.append(market)
        if preferred:
            self.markets = preferred[: self.max_markets]
        self._last_discovery_at = now

    def refresh(self) -> None:
        self._discover_markets()
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
            "markets_configured": len(self.markets),
            "auto_discover_eur": self.auto_discover_eur,
            "max_markets": self.max_markets,
            "errors": self._last_error,
            "rankings": by_strategy,
        }


class BinanceReferenceFeed:
    """Read-only Binance BTC reference price. Never authenticates or trades."""

    BASE_URL = "https://api.binance.com/api/v3/ticker/price"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        fetcher: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.symbol = str(self.config.get("symbol", "BTCUSDT")).upper()
        self.interval_seconds = max(1.0, float(self.config.get("interval_seconds", 1.0)))
        self.timeout_seconds = max(1.0, float(self.config.get("timeout_seconds", 3.0)))
        self._fetcher = fetcher
        self.price: float | None = None
        self.updated_at = 0.0
        self.error: str | None = None

    def _http_fetch(self, symbol: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"symbol": symbol})
        req = urllib.request.Request(
            f"{self.BASE_URL}?{query}",
            headers={"Accept": "application/json", "User-Agent": "AutoTraderReference/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode())
        if not isinstance(payload, dict):
            raise ValueError("unexpected Binance reference response")
        return payload

    def refresh(self) -> None:
        if not self.enabled:
            return
        try:
            payload = (self._fetcher or self._http_fetch)(self.symbol)
            price = float(payload["price"])
            if price <= 0 or not math.isfinite(price):
                raise ValueError("invalid Binance reference price")
            self.price = price
            self.updated_at = time.time()
            self.error = None
        except Exception as exc:
            self.error = type(exc).__name__

    def status(self) -> dict[str, Any]:
        return {
            "source": "binance_public",
            "symbol": self.symbol,
            "price": self.price,
            "updated_at": self.updated_at or None,
            "error": self.error,
            "read_only": True,
            "live_orders_sent": False,
            "interval_seconds": self.interval_seconds,
        }


class PortfolioGoalTracker:
    """Track a shared portfolio objective without using it as a risk input."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.starting_equity_eur = max(0.01, float(self.config.get("starting_equity_eur", 50.0)))
        self.target_equity_eur = max(
            self.starting_equity_eur,
            float(self.config.get("target_equity_eur", 25000.0)),
        )
        raw = self.config.get(
            "milestones_eur",
            [100, 250, 500, 1000, 2500, 5000, 10000, 25000],
        )
        self.milestones = sorted({
            float(x)
            for x in raw
            if float(x) > self.starting_equity_eur and float(x) <= self.target_equity_eur
        })
        if self.target_equity_eur not in self.milestones:
            self.milestones.append(self.target_equity_eur)

    def status(
        self,
        current_equity_eur: float,
        strategy_snapshots: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        current = max(0.0, float(current_equity_eur))
        span = max(0.01, self.target_equity_eur - self.starting_equity_eur)
        progress = max(
            0.0,
            min(100.0, (current - self.starting_equity_eur) / span * 100.0),
        )
        next_milestone = next((x for x in self.milestones if current < x), None)
        contributions = []
        for row in strategy_snapshots or []:
            contributions.append({
                "strategy": row.get("strategy"),
                "market": row.get("market"),
                "realized_net_pnl_eur": round(
                    float(row.get("realized_net_pnl_eur") or 0.0), 6
                ),
                "economic_pnl_eur": round(
                    float(row.get("economic_pnl_eur") or 0.0), 6
                ),
            })
        return {
            "enabled": self.enabled,
            "shared_goal": True,
            "starting_equity_eur": round(self.starting_equity_eur, 2),
            "target_equity_eur": round(self.target_equity_eur, 2),
            "current_equity_estimate_eur": round(current, 2),
            "progress_pct": round(progress, 4),
            "remaining_eur": round(max(0.0, self.target_equity_eur - current), 2),
            "next_milestone_eur": round(next_milestone, 2) if next_milestone else None,
            "target_reached": current >= self.target_equity_eur,
            "milestones_eur": self.milestones,
            "strategy_contributions": contributions,
            "risk_policy": {
                "goal_is_risk_input": False,
                "increase_risk_to_catch_up": False,
                "increase_leverage_to_catch_up": False,
                "increase_budget_to_catch_up": False,
                "martingale": False,
            },
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
