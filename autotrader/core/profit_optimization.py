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
    imbalance_pct: float
    observed_at: float
    expected_slippage_bps: float
    quote_to_eur: float = 1.0


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
        self.auto_discover_all = bool(self.config.get("auto_discover_all", False))
        self.max_markets = max(1, min(500, int(self.config.get("max_markets", 250))))
        self.discovery_refresh_seconds = max(
            60.0, float(self.config.get("discovery_refresh_seconds", 1800.0))
        )
        self._last_discovery_at = 0.0
        self.history_size = max(8, min(240, int(self.config.get("history_size", 48))))
        self.min_top_depth_eur = max(5.0, float(self.config.get("min_top_depth_eur", 25.0)))
        self.max_spread_bps = max(1.0, float(self.config.get("max_spread_bps", 35.0)))
        self.probe_order_eur = max(1.0, float(self.config.get("probe_order_eur", 6.0)))
        self.max_snapshot_age_seconds = max(
            1.0, float(self.config.get("max_snapshot_age_seconds", 30.0))
        )
        # Fee-aware ranking stays read-only. Values are conservative low-tier
        # Bitvavo estimates and can be overridden in config without changing
        # live execution support.
        self.maker_fee_bps_by_quote = {
            str(key).upper(): max(0.0, float(value))
            for key, value in (self.config.get("maker_fee_bps_by_quote", {
                "EUR": 15.0,
                "USDC": 5.0,
            }) or {}).items()
        }
        self.taker_fee_bps_by_quote = {
            str(key).upper(): max(0.0, float(value))
            for key, value in (self.config.get("taker_fee_bps_by_quote", {
                "EUR": 25.0,
                "USDC": 5.0,
            }) or {}).items()
        }
        self.default_maker_fee_bps = max(
            0.0, float(self.config.get("default_maker_fee_bps", 25.0))
        )
        self.default_taker_fee_bps = max(
            0.0, float(self.config.get("default_taker_fee_bps", 25.0))
        )
        self.live_quote_assets = {
            str(x).upper()
            for x in (self.config.get("live_quote_assets") or ["EUR"])
            if str(x).strip()
        }
        self._history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.history_size))
        self._latest: dict[str, MarketSnapshot] = {}
        self._last_error: dict[str, str] = {}
        self.updated_at = 0.0

    def _discover_markets(self) -> None:
        if not (self.auto_discover_eur or self.auto_discover_all):
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
                if status != "trading":
                    continue
                if self.auto_discover_all or market.endswith("-EUR"):
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

    @staticmethod
    def _market_graph(books: dict[str, Any]) -> dict[str, list[tuple[str, float]]]:
        graph: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for market, book in books.items():
            if "-" not in market or not isinstance(book, dict):
                continue
            base, quote = market.rsplit("-", 1)
            try:
                bid = float(book["bid"])
                ask = float(book["ask"])
            except (KeyError, TypeError, ValueError):
                continue
            mid = (bid + ask) / 2.0
            if mid <= 0 or not math.isfinite(mid):
                continue
            graph[base].append((quote, mid))
            graph[quote].append((base, 1.0 / mid))
        return graph

    @staticmethod
    def _quote_to_eur(asset: str, graph: dict[str, list[tuple[str, float]]], max_hops: int = 3) -> float | None:
        asset = str(asset or "").upper()
        if asset == "EUR":
            return 1.0
        queue = deque([(asset, 1.0, 0)])
        seen = {asset}
        while queue:
            node, rate, hops = queue.popleft()
            if hops >= max_hops:
                continue
            for target, edge in graph.get(node, []):
                if target in seen:
                    continue
                nxt = rate * edge
                if target == "EUR":
                    return nxt
                seen.add(target)
                queue.append((target, nxt, hops + 1))
        return None

    def refresh(self) -> None:
        self._discover_markets()
        latest: dict[str, MarketSnapshot] = {}
        errors: dict[str, str] = {}
        bulk_books: dict[str, Any] = {}
        if hasattr(self.adapter, "ticker_books"):
            try:
                raw_books = self.adapter.ticker_books()
                if isinstance(raw_books, dict):
                    bulk_books = raw_books
            except Exception:
                bulk_books = {}
        conversion_graph = self._market_graph(bulk_books) if bulk_books else {}
        for market in self.markets:
            try:
                book = bulk_books.get(market) if bulk_books else None
                if not isinstance(book, dict):
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
                quote = market.rsplit("-", 1)[1] if "-" in market else ""
                quote_to_eur = self._quote_to_eur(quote, conversion_graph)
                liquidity_quote = min(bid * bid_size, ask * ask_size)
                liquidity_eur = liquidity_quote * quote_to_eur if quote_to_eur is not None else 0.0
                size_total = bid_size + ask_size
                imbalance_pct = (
                    (bid_size - ask_size) / size_total * 100.0
                    if size_total > 0 else 0.0
                )
                # Conservative top-of-book slippage proxy for the configured
                # probe notional. It is not a fill prediction.
                depth_ratio = self.probe_order_eur / max(0.01, liquidity_eur)
                expected_slippage_bps = max(
                    0.0,
                    spread_bps * max(0.0, depth_ratio - 1.0),
                )
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
                    imbalance_pct=imbalance_pct,
                    observed_at=time.time(),
                    expected_slippage_bps=expected_slippage_bps,
                    quote_to_eur=float(quote_to_eur or 0.0),
                )
            except Exception as exc:
                errors[market] = type(exc).__name__
        self._latest = latest
        self._last_error = errors
        self.updated_at = time.time()

    def _fee_bps(self, market: str, *, maker: bool) -> float:
        quote = market.rsplit("-", 1)[1].upper() if "-" in market else ""
        table = self.maker_fee_bps_by_quote if maker else self.taker_fee_bps_by_quote
        default = self.default_maker_fee_bps if maker else self.default_taker_fee_bps
        return max(0.0, float(table.get(quote, default)))

    @staticmethod
    def _fee_quality(one_way_fee_bps: float) -> float:
        # 0 bps => 100 quality, 50 bps => 0 quality. This is deliberately
        # simple and transparent; it ranks execution cost without pretending
        # fees alone predict returns.
        return max(0.0, min(100.0, 100.0 - max(0.0, one_way_fee_bps) * 2.0))

    def _features(self, snap: MarketSnapshot) -> dict[str, float]:
        spread_quality = max(0.0, min(100.0, 100.0 * (1.0 - snap.spread_bps / self.max_spread_bps)))
        liquidity = max(0.0, min(100.0, snap.liquidity_eur / self.min_top_depth_eur * 100.0))
        momentum = max(0.0, min(100.0, 50.0 + snap.momentum_pct * 40.0))
        volatility_quality = max(0.0, min(100.0, 100.0 - abs(snap.volatility_pct - 0.18) * 220.0))
        trend = max(0.0, min(100.0, 50.0 + snap.momentum_pct * 55.0))
        age = max(0.0, time.time() - snap.observed_at)
        freshness = max(
            0.0,
            min(100.0, 100.0 * (1.0 - age / self.max_snapshot_age_seconds)),
        )
        balance_quality = max(0.0, 100.0 - abs(snap.imbalance_pct))
        buy_imbalance = max(0.0, min(100.0, 50.0 + snap.imbalance_pct / 2.0))
        slippage_quality = max(
            0.0,
            min(100.0, 100.0 * (1.0 - snap.expected_slippage_bps / self.max_spread_bps)),
        )
        return {
            "trend": trend,
            "momentum": momentum,
            "volatility_quality": volatility_quality,
            "liquidity": liquidity,
            "spread_quality": spread_quality,
            "book_balance_quality": balance_quality,
            "buy_imbalance": buy_imbalance,
            "freshness": freshness,
            "slippage_quality": slippage_quality,
        }

    @staticmethod
    def _weighted(features: dict[str, float], weights: dict[str, float]) -> float:
        return sum(features.get(k, 0.0) * v for k, v in weights.items())

    @staticmethod
    def _signal_strength(
        strategy: str,
        features: dict[str, float],
        snap: MarketSnapshot,
    ) -> tuple[float, str]:
        """Return strategy-specific signal strength separate from market quality."""
        if strategy == "sniper":
            value = (
                features["momentum"] * 0.35
                + features["trend"] * 0.30
                + features["buy_imbalance"] * 0.20
                + features["liquidity"] * 0.10
                + features["freshness"] * 0.05
            )
            if snap.momentum_pct <= 0 or snap.imbalance_pct <= 0:
                value *= 0.55
            direction = "LONG" if snap.momentum_pct > 0 and snap.imbalance_pct > 0 else "WAIT"
        elif strategy == "grid":
            value = (
                features["volatility_quality"] * 0.30
                + features["book_balance_quality"] * 0.25
                + features["liquidity"] * 0.20
                + features["spread_quality"] * 0.15
                + features["slippage_quality"] * 0.10
            )
            if abs(snap.momentum_pct) > 0.25:
                value *= 0.70
            direction = "RANGE"
        elif strategy == "market_maker":
            value = (
                features["book_balance_quality"] * 0.25
                + features["spread_quality"] * 0.25
                + features["liquidity"] * 0.20
                + features["freshness"] * 0.15
                + features["slippage_quality"] * 0.15
            )
            if abs(snap.momentum_pct) > 0.30:
                value *= 0.65
            direction = "NEUTRAL"
        elif strategy == "volatility_breakout":
            value = (
                features["momentum"] * 0.30
                + features["trend"] * 0.25
                + features["liquidity"] * 0.20
                + features["buy_imbalance"] * 0.15
                + features["freshness"] * 0.10
            )
            direction = "LONG" if snap.momentum_pct > 0 else "WAIT"
        else:
            value = (
                features["volatility_quality"] * 0.30
                + features["book_balance_quality"] * 0.25
                + features["liquidity"] * 0.20
                + features["spread_quality"] * 0.15
                + features["freshness"] * 0.10
            )
            direction = "MEAN_REVERT"
        return max(0.0, min(100.0, value)), direction

    def rankings(self) -> dict[str, Any]:
        profiles = {
            "market_maker": {"spread_quality": 0.25, "liquidity": 0.25, "volatility_quality": 0.15, "book_balance_quality": 0.15, "freshness": 0.10, "slippage_quality": 0.10},
            "grid": {"volatility_quality": 0.25, "liquidity": 0.20, "spread_quality": 0.15, "book_balance_quality": 0.15, "momentum": 0.10, "freshness": 0.05, "slippage_quality": 0.10},
            "sniper": {"momentum": 0.30, "trend": 0.25, "liquidity": 0.15, "spread_quality": 0.10, "buy_imbalance": 0.10, "freshness": 0.05, "slippage_quality": 0.05},
            "mean_reversion": {"volatility_quality": 0.25, "liquidity": 0.20, "spread_quality": 0.15, "book_balance_quality": 0.15, "trend": 0.10, "freshness": 0.05, "slippage_quality": 0.10},
            "volatility_breakout": {"momentum": 0.25, "volatility_quality": 0.20, "liquidity": 0.20, "spread_quality": 0.10, "buy_imbalance": 0.10, "freshness": 0.05, "slippage_quality": 0.10},
        }
        by_strategy: dict[str, list[dict[str, Any]]] = {}
        for strategy, weights in profiles.items():
            rows = []
            for snap in self._latest.values():
                features = self._features(snap)
                maker_profile = strategy in {"market_maker", "grid", "mean_reversion"}
                fee_bps = self._fee_bps(snap.market, maker=maker_profile)
                fee_quality = self._fee_quality(fee_bps)
                # Keep the existing score untouched because it is consumed
                # by the live EUR autonomous router. Fee economics are exposed
                # separately for shadow/research ranking so this feature cannot
                # silently change live order selection.
                score = self._weighted(features, weights)
                fee_weight = max(
                    0.0,
                    min(0.25, float(self.config.get("fee_quality_weight", 0.10))),
                )
                economic_shadow_score = (
                    score * (1.0 - fee_weight) + fee_quality * fee_weight
                )
                signal_strength, signal_direction = self._signal_strength(
                    strategy, features, snap
                )
                eligible = (
                    snap.liquidity_eur >= self.min_top_depth_eur
                    and snap.spread_bps <= self.max_spread_bps
                )
                rows.append({
                    "market": snap.market,
                    "quote": snap.market.rsplit("-", 1)[1] if "-" in snap.market else "",
                    "pair_type": "crypto_fiat" if snap.market.endswith("-EUR") else "crypto_crypto",
                    "quote_to_eur": round(float(snap.quote_to_eur or 0.0), 12),
                    "live_execution_supported_now": (
                        (snap.market.rsplit("-", 1)[1] if "-" in snap.market else "")
                        in self.live_quote_assets
                        and float(snap.quote_to_eur or 0.0) > 0
                    ),
                    "score": round(score, 2),
                    "economic_shadow_score": round(economic_shadow_score, 2),
                    "signal_strength": round(signal_strength, 2),
                    "signal_direction": signal_direction,
                    "eligible": eligible,
                    "mid": round(snap.mid, 10),
                    "spread_bps": round(snap.spread_bps, 3),
                    "liquidity_eur": round(snap.liquidity_eur, 2),
                    "orderbook_imbalance_pct": round(snap.imbalance_pct, 3),
                    "snapshot_age_seconds": round(max(0.0, time.time() - snap.observed_at), 3),
                    "expected_slippage_bps": round(snap.expected_slippage_bps, 3),
                    "estimated_execution_fee_bps": round(fee_bps, 3),
                    "estimated_round_trip_fee_bps": round(fee_bps * 2.0, 3),
                    "fee_quality": round(fee_quality, 2),
                    "fee_profile": "maker" if maker_profile else "taker",
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
            "auto_discover_all": self.auto_discover_all,
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
        self.starting_equity_eur = max(0.01, float(self.config.get("starting_equity_eur", 80.0)))
        self.target_equity_eur = max(
            self.starting_equity_eur,
            float(self.config.get("target_equity_eur", 100000.0)),
        )
        self.target_days = max(1, int(self.config.get("target_days", 365)))
        raw = self.config.get(
            "milestones_eur",
            [250, 500, 1000, 5000, 10000, 50000, 100000],
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
        required_daily_linear_eur = max(
            0.0, self.target_equity_eur - current
        ) / self.target_days
        required_daily_compound_pct = 0.0
        if current > 0 and current < self.target_equity_eur:
            required_daily_compound_pct = (
                (self.target_equity_eur / current) ** (1.0 / self.target_days) - 1.0
            ) * 100.0
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
            "target_days": self.target_days,
            "required_daily_linear_eur": round(required_daily_linear_eur, 2),
            "required_daily_compound_pct": round(required_daily_compound_pct, 4),
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


class CalculatedRiskSizer:
    """Risk-adjusted sizing recommendations within existing hard caps.

    This class never mutates budgets, risk limits, leverage, or armed state.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.apply_live = bool(self.config.get("apply_live", False))
        self.profile = str(self.config.get("profile", "balanced_aggressive"))
        self.max_size_multiplier = max(
            1.0, min(2.0, float(self.config.get("max_size_multiplier", 1.35)))
        )
        self.min_confidence = max(
            0.0, min(1.0, float(self.config.get("min_confidence", 0.62)))
        )
        self.max_drawdown_pct = max(
            0.1, float(self.config.get("max_drawdown_pct", 8.0))
        )
        self.max_fee_drag_pct = max(
            1.0, float(self.config.get("max_fee_drag_pct", 55.0))
        )

    def recommend(
        self,
        opportunities: list[dict[str, Any]],
        fee_rows: list[dict[str, Any]],
        strategy_snapshots: list[dict[str, Any]],
        base_allocations: dict[str, float],
        max_order_eur: dict[str, float],
    ) -> dict[str, Any]:
        fee_by = {str(x.get("strategy")): x for x in fee_rows}
        snap_by = {str(x.get("strategy")): x for x in strategy_snapshots}
        rows = []
        for opp in opportunities:
            strategy = str(opp.get("strategy") or "")
            score = max(0.0, min(100.0, float(opp.get("score") or 0.0)))
            eligible = bool(opp.get("eligible", False))
            snap = snap_by.get(strategy, {})
            fee = fee_by.get(strategy, {})
            dd = abs(float(snap.get("max_drawdown_pct") or 0.0))
            fee_drag = fee.get("fee_drag_pct")
            fee_drag = float(fee_drag) if fee_drag is not None else 0.0
            samples = int(
                snap.get("profitable_exits") or 0
            ) + int(snap.get("losing_exits") or 0)
            sample_conf = min(1.0, samples / 20.0)
            quality_conf = score / 100.0
            signal_conf = max(
                0.0,
                min(1.0, float(opp.get("signal_strength", score) or 0.0) / 100.0),
            )
            # Cold start no longer forces a high-quality, high-signal market
            # below the execution threshold merely because it has few exits.
            # Historical samples still increase confidence as evidence accrues.
            evidence_conf = 0.50 + 0.50 * sample_conf
            confidence = (
                0.45 * quality_conf
                + 0.35 * signal_conf
                + 0.20 * evidence_conf
            )
            risk_penalty = 1.0
            if dd > self.max_drawdown_pct:
                risk_penalty *= 0.45
            elif dd > self.max_drawdown_pct * 0.65:
                risk_penalty *= 0.75
            if fee_drag > self.max_fee_drag_pct:
                risk_penalty *= 0.65
            if not eligible:
                risk_penalty *= 0.0

            multiplier = 1.0
            if confidence >= self.min_confidence:
                upside = (confidence - self.min_confidence) / max(0.01, 1.0 - self.min_confidence)
                multiplier = 1.0 + upside * (self.max_size_multiplier - 1.0)
            multiplier *= risk_penalty
            if confidence < self.min_confidence:
                multiplier = min(multiplier, 0.85)

            base = max(0.0, float(base_allocations.get(strategy, 0.0)))
            order_cap = max(0.0, float(max_order_eur.get(strategy, 0.0)))
            recommended = min(order_cap, base * multiplier) if order_cap > 0 else base * multiplier

            rows.append({
                "strategy": strategy,
                "market": opp.get("market"),
                "opportunity_score": round(score, 2),
                "signal_strength": round(signal_conf * 100.0, 2),
                "confidence": round(confidence, 4),
                "drawdown_pct": round(dd, 3),
                "fee_drag_pct": round(fee_drag, 2),
                "size_multiplier": round(multiplier, 3),
                "recommended_order_eur": round(max(0.0, recommended), 2),
                "eligible": eligible,
                "reason": (
                    "calculated_risk_upsize"
                    if multiplier > 1.0
                    else "risk_reduced"
                    if multiplier < 1.0
                    else "base_size"
                ),
            })
        return {
            "enabled": self.enabled,
            "apply_live": self.apply_live,
            "mode": "bounded_live_input" if self.apply_live else "advisory",
            "profile": self.profile,
            "max_size_multiplier": self.max_size_multiplier,
            "live_budget_changed": False,
            "hard_risk_limits_changed": False,
            "leverage_changed": False,
            "rows": rows,
        }


class ExecutionV2Advisor:
    """Recommend maker-first repricing for stale orders without executing it."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.apply_live = bool(self.config.get("apply_live", False))
        self.stale_after_seconds = max(30.0, float(self.config.get("stale_after_seconds", 180.0)))
        self.min_move_bps = max(
            0.1,
            float(
                self.config.get(
                    "order_refresh_tolerance_bps",
                    self.config.get("min_reprice_move_bps", 4.0),
                )
            ),
        )
        self.max_order_age_seconds = max(
            self.stale_after_seconds,
            float(self.config.get("max_order_age_seconds", 900.0)),
        )
        self.filled_order_delay_seconds = max(
            0.0, float(self.config.get("filled_order_delay_seconds", 60.0))
        )

    def evaluate(
        self,
        activity: list[dict[str, Any]],
        books: dict[str, dict[str, float]],
        min_profit_exit_by_strategy: dict[str, float],
        target_edge_by_strategy: dict[str, float],
        required_entry_edge_pct: float,
        last_fill_at_by_strategy: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        last_fill_at_by_strategy = last_fill_at_by_strategy or {}
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
            last_fill_at = float(last_fill_at_by_strategy.get(strategy) or 0.0)
            fill_delay_remaining = max(
                0.0,
                self.filled_order_delay_seconds - max(0.0, now - last_fill_at),
            ) if last_fill_at > 0 else 0.0
            fill_delay_active = fill_delay_remaining > 0
            should_reprice = (
                stale
                and move_bps >= self.min_move_bps
                and profit_ok
                and not fill_delay_active
            )
            if fill_delay_active:
                reason = "post_fill_delay_active"
            elif not profit_ok:
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
                "recommend_cancel_at_max_age": bool(too_old and not should_reprice),
                "post_fill_delay_active": fill_delay_active,
                "post_fill_delay_remaining_seconds": round(fill_delay_remaining, 1),
                "refresh_tolerance_bps": round(self.min_move_bps, 3),
                "max_order_age_seconds": round(self.max_order_age_seconds, 1),
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
