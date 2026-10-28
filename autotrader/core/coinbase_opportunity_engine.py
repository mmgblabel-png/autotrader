"""Coinbase multi-market opportunity engine for the local RiskTrader.

REST scans the broad SPOT universe. A realtime WebSocket order-flow engine can
supply Level-2 depth and market-trade microstructure for the highest-ranked,
directly fundable products. This module only produces signals; order placement
remains exclusively in CoinbaseAutonomousExecutor.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData


@dataclass(frozen=True)
class CoinbaseOpportunityConfig:
    enabled: bool = True
    interval_seconds: float = 10.0
    universe_refresh_seconds: float = 120.0
    candidate_limit: int = 60
    sample_lookback_seconds: float = 600.0
    min_samples: int = 3
    min_recent_momentum_bps: float = 8.0
    max_spread_bps: float = 20.0
    min_quote_balance: float = 1.0
    min_24h_quote_volume: float = 5_000.0
    quote_currencies: tuple[str, ...] = ("EUR", "USDC")
    decision_window_seconds: int = 300
    daily_trade_target: int = 10
    daily_profit_target_eur: float = 1.0

    high_risk_enabled: bool = True
    high_risk_min_samples: int = 2
    high_risk_min_recent_momentum_bps: float = 3.0
    high_risk_max_spread_bps: float = 45.0
    high_risk_min_24h_quote_volume: float = 1_000.0

    realtime_product_limit: int = 20
    realtime_min_edge_bps: float = 4.0
    orderbook_imbalance_weight_bps: float = 22.0
    trade_flow_weight_bps: float = 15.0
    microprice_weight: float = 2.0
    velocity_weight_bps: float = 6.0

    state_path: str = "/data/coinbase_opportunity_state.json"
    new_listing_window_seconds: float = 259_200.0
    new_listing_score_bonus: float = 35.0
    new_listing_min_samples: int = 2

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "CoinbaseOpportunityConfig":
        cfg = raw or {}
        quotes = tuple(
            str(x).upper()
            for x in cfg.get("quote_currencies", ["EUR", "USDC"])
            if str(x).strip()
        ) or ("EUR", "USDC")
        return cls(
            enabled=bool(cfg.get("enabled", True)),
            interval_seconds=max(5.0, float(cfg.get("interval_seconds", 10.0))),
            universe_refresh_seconds=max(60.0, float(cfg.get("universe_refresh_seconds", 120.0))),
            candidate_limit=max(5, min(100, int(cfg.get("candidate_limit", 60)))),
            sample_lookback_seconds=max(120.0, float(cfg.get("sample_lookback_seconds", 600.0))),
            min_samples=max(2, int(cfg.get("min_samples", 3))),
            min_recent_momentum_bps=max(0.0, float(cfg.get("min_recent_momentum_bps", 8.0))),
            max_spread_bps=max(1.0, float(cfg.get("max_spread_bps", 20.0))),
            min_quote_balance=max(0.01, float(cfg.get("min_quote_balance", 1.0))),
            min_24h_quote_volume=max(0.0, float(cfg.get("min_24h_quote_volume", 5_000.0))),
            quote_currencies=quotes,
            decision_window_seconds=max(60, int(cfg.get("decision_window_seconds", 300))),
            daily_trade_target=max(1, int(cfg.get("daily_trade_target", 10))),
            daily_profit_target_eur=max(0.0, float(cfg.get("daily_profit_target_eur", 1.0))),
            high_risk_enabled=bool(cfg.get("high_risk_enabled", True)),
            high_risk_min_samples=max(2, int(cfg.get("high_risk_min_samples", 2))),
            high_risk_min_recent_momentum_bps=max(
                0.0, float(cfg.get("high_risk_min_recent_momentum_bps", 3.0))
            ),
            high_risk_max_spread_bps=max(1.0, float(cfg.get("high_risk_max_spread_bps", 45.0))),
            high_risk_min_24h_quote_volume=max(
                0.0, float(cfg.get("high_risk_min_24h_quote_volume", 1_000.0))
            ),
            realtime_product_limit=max(1, min(50, int(cfg.get("realtime_product_limit", 20)))),
            realtime_min_edge_bps=max(0.0, float(cfg.get("realtime_min_edge_bps", 4.0))),
            orderbook_imbalance_weight_bps=max(
                0.0, float(cfg.get("orderbook_imbalance_weight_bps", 22.0))
            ),
            trade_flow_weight_bps=max(0.0, float(cfg.get("trade_flow_weight_bps", 15.0))),
            microprice_weight=max(0.0, float(cfg.get("microprice_weight", 2.0))),
            velocity_weight_bps=max(0.0, float(cfg.get("velocity_weight_bps", 6.0))),
            state_path=str(cfg.get("state_path", "/data/coinbase_opportunity_state.json")),
            new_listing_window_seconds=max(
                3600.0, float(cfg.get("new_listing_window_seconds", 259_200.0))
            ),
            new_listing_score_bonus=max(0.0, float(cfg.get("new_listing_score_bonus", 35.0))),
            new_listing_min_samples=max(2, int(cfg.get("new_listing_min_samples", 2))),
        )


class CoinbaseOpportunityEngine:
    def __init__(
        self,
        config: CoinbaseOpportunityConfig | dict[str, Any] | None = None,
        *,
        market_data: CoinbaseAdvancedMarketData | None = None,
        portfolio_id: str = "",
        realtime_orderflow: Any | None = None,
    ) -> None:
        self.config = (
            config
            if isinstance(config, CoinbaseOpportunityConfig)
            else CoinbaseOpportunityConfig.from_mapping(config)
        )
        self.market = market_data or CoinbaseAdvancedMarketData(timeout=5.0)
        self.portfolio_id = str(portfolio_id or "").strip()
        self.realtime = realtime_orderflow
        self._products: list[dict[str, Any]] = []
        self._universe_refreshed_at = 0.0
        self._samples: dict[str, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=120))
        self._rotation_cursor = 0
        self._state_path = Path(self.config.state_path)
        self._known_products: dict[str, float] = self._load_known_products()
        self.last_status: dict[str, Any] = {
            "enabled": self.config.enabled,
            "last_signal": {"decisions": []},
            "scanned_markets": 0,
            "tradable_markets": 0,
            "fundable_markets": 0,
            "top_candidates": [],
            "realtime": {},
        }

    @staticmethod
    def _float(value: object, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else default
        except (TypeError, ValueError):
            return default

    def _load_known_products(self) -> dict[str, float]:
        try:
            raw = json.loads(self._state_path.read_text("utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        rows = raw.get("known_products") if isinstance(raw, dict) else None
        if not isinstance(rows, dict):
            return {}
        result: dict[str, float] = {}
        for key, value in rows.items():
            try:
                result[str(key).upper()] = float(value)
            except (TypeError, ValueError):
                continue
        return result

    def _save_known_products(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"known_products": self._known_products},
                sort_keys=True,
                separators=(",", ":"),
            )
            with tempfile.NamedTemporaryFile(
                "w",
                dir=str(self._state_path.parent),
                prefix=".coinbase-opportunity-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                temp_name = handle.name
            os.replace(temp_name, self._state_path)
        except Exception:
            # Listing detection is an enhancement, never a reason to break trading.
            pass

    def _refresh_products(self, now: float) -> None:
        if self._products and now - self._universe_refreshed_at < self.config.universe_refresh_seconds:
            return
        self._products = self.market.list_spot_products()
        product_ids = {
            str(row.get("product_id") or "").upper()
            for row in self._products
            if isinstance(row, dict) and str(row.get("product_id") or "").strip()
        }
        if not self._known_products:
            # First start is the baseline. Existing Coinbase products are not
            # misclassified as new listings.
            self._known_products = {product_id: 0.0 for product_id in product_ids}
            self._save_known_products()
        else:
            changed = False
            for product_id in product_ids:
                if product_id not in self._known_products:
                    self._known_products[product_id] = now
                    changed = True
            if changed:
                self._save_known_products()
        self._universe_refreshed_at = now

    def _is_new_listing(self, product_id: str, now: float) -> tuple[bool, float | None]:
        first_seen = float(self._known_products.get(product_id, 0.0) or 0.0)
        is_new = bool(
            first_seen > 0
            and now >= first_seen
            and now - first_seen <= self.config.new_listing_window_seconds
        )
        return is_new, (first_seen or None)

    def _quote_balances(self) -> dict[str, float]:
        if not self.portfolio_id:
            return {}
        payload = self.market.account_balances(self.portfolio_id)
        result: dict[str, float] = {}
        for row in payload.get("assets", []) if isinstance(payload, dict) else []:
            if not isinstance(row, dict):
                continue
            currency = str(row.get("currency") or "").upper()
            result[currency] = max(0.0, self._float(row.get("available")))
        return result

    def _recent_stats(self, product_id: str, now: float) -> tuple[float, float, int]:
        samples = self._samples[product_id]
        cutoff = now - self.config.sample_lookback_seconds
        while samples and samples[0][0] < cutoff:
            samples.popleft()
        if len(samples) < 2:
            return 0.0, 0.0, len(samples)
        first = samples[0][1]
        last = samples[-1][1]
        momentum_bps = ((last / first) - 1.0) * 10_000.0 if first > 0 else 0.0
        returns = []
        prev = samples[0][1]
        for _, value in list(samples)[1:]:
            if prev > 0 and value > 0:
                returns.append((value / prev - 1.0) * 10_000.0)
            prev = value
        if len(returns) < 2:
            return momentum_bps, 0.0, len(samples)
        mean = sum(returns) / len(returns)
        variance = sum((x - mean) ** 2 for x in returns) / max(1, len(returns) - 1)
        sigma = math.sqrt(max(0.0, variance))
        z = momentum_bps / max(sigma * math.sqrt(len(returns)), 1e-9)
        return momentum_bps, z, len(samples)

    def _realtime_snapshot(self, product_id: str) -> dict[str, Any]:
        if self.realtime is None:
            return {}
        try:
            row = self.realtime.snapshot(product_id)
        except Exception:
            return {}
        return dict(row) if isinstance(row, dict) else {}

    def _realtime_edge(self, realtime: dict[str, Any]) -> float:
        if not realtime.get("fresh"):
            return 0.0
        imbalance = max(-1.0, min(1.0, self._float(realtime.get("book_imbalance"))))
        flow = max(-1.0, min(1.0, self._float(realtime.get("trade_flow_imbalance"))))
        micro = self._float(realtime.get("microprice_edge_bps"))
        velocity = max(0.0, self._float(realtime.get("trade_velocity_ratio"), 1.0))
        velocity_term = max(-1.0, min(2.0, velocity - 1.0))
        return (
            imbalance * self.config.orderbook_imbalance_weight_bps
            + flow * self.config.trade_flow_weight_bps
            + micro * self.config.microprice_weight
            + velocity_term * self.config.velocity_weight_bps
        )

    def tick(self, now: float | None = None) -> dict[str, Any]:
        ts = float(time.time() if now is None else now)
        if not self.config.enabled:
            return dict(self.last_status)

        self._refresh_products(ts)
        balances = self._quote_balances()
        fundable_quotes = {
            q
            for q in self.config.quote_currencies
            if balances.get(q, 0.0) >= self.config.min_quote_balance
        }

        tradable = [p for p in self._products if bool(p.get("tradable"))]
        fundable = [
            p for p in tradable if str(p.get("quote") or "").upper() in fundable_quotes
        ]

        ranked: list[tuple[float, dict[str, Any]]] = []
        minimum_volume = min(
            self.config.min_24h_quote_volume,
            self.config.high_risk_min_24h_quote_volume
            if self.config.high_risk_enabled
            else self.config.min_24h_quote_volume,
        )
        for row in fundable:
            product_id = str(row.get("product_id") or "").upper()
            price = self._float(row.get("price"))
            change_pct = self._float(row.get("price_change_24h_pct"))
            volume_base = self._float(row.get("volume_24h"))
            quote_volume = price * volume_base if price > 0 and volume_base > 0 else 0.0
            if price <= 0 or quote_volume < minimum_volume:
                continue
            liquidity_score = math.log10(max(quote_volume, 1.0)) * 8.0
            is_new, _ = self._is_new_listing(product_id, ts)
            score = (
                max(-500.0, change_pct * 100.0)
                + liquidity_score
                + (self.config.new_listing_score_bonus if is_new else 0.0)
            )
            ranked.append((score, row))
        ranked.sort(key=lambda item: item[0], reverse=True)

        realtime_products = [
            str(row.get("product_id") or "").upper()
            for _, row in ranked[: self.config.realtime_product_limit]
        ]
        if self.realtime is not None:
            try:
                self.realtime.set_products(realtime_products)
            except Exception:
                pass

        candidates: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []

        # Always inspect the strongest ranked markets, but rotate the remaining
        # slots through the rest so the full fundable universe is genuinely
        # evaluated over time without exploding REST top-of-book traffic.
        limit = min(self.config.candidate_limit, len(ranked))
        always_top = min(30, limit)
        selected = list(ranked[:always_top])
        remaining_slots = max(0, limit - always_top)
        tail = ranked[always_top:]
        if remaining_slots > 0 and tail:
            start = self._rotation_cursor % len(tail)
            for offset in range(min(remaining_slots, len(tail))):
                selected.append(tail[(start + offset) % len(tail)])
            self._rotation_cursor = (start + remaining_slots) % len(tail)
        elif not tail:
            self._rotation_cursor = 0

        for _, row in selected:
            product_id = str(row.get("product_id") or "").upper()
            realtime = self._realtime_snapshot(product_id)

            bid = self._float(realtime.get("best_bid")) if realtime.get("fresh") else 0.0
            ask = self._float(realtime.get("best_ask")) if realtime.get("fresh") else 0.0
            if bid <= 0 or ask <= 0:
                try:
                    book = self.market.top_of_book(product_id)
                    bid = float(book.bid_price)
                    ask = float(book.ask_price)
                except Exception:
                    continue
            if bid <= 0 or ask <= 0 or ask < bid:
                continue

            mid = (bid + ask) / 2.0
            spread_bps = (ask - bid) / mid * 10_000.0
            self._samples[product_id].append((ts, mid))
            recent_bps, reference_z, sample_count = self._recent_stats(product_id, ts)
            day_bps = self._float(row.get("price_change_24h_pct")) * 100.0
            realtime_edge_bps = self._realtime_edge(realtime)
            base_forecast_bps = recent_bps * 0.85 + max(0.0, day_bps) * 0.05
            forecast_bps = max(0.0, base_forecast_bps + realtime_edge_bps)
            probability_up = min(0.92, max(0.50, 0.50 + forecast_bps / 360.0))
            quote_volume = self._float(row.get("price")) * self._float(row.get("volume_24h"))
            is_new_listing, first_seen = self._is_new_listing(product_id, ts)

            candidate = {
                "product_id": product_id,
                "base": str(row.get("base") or "").upper(),
                "quote": str(row.get("quote") or "").upper(),
                "mid": mid,
                "spread_bps": spread_bps,
                "recent_momentum_bps": recent_bps,
                "change_24h_bps": day_bps,
                "base_forecast_bps": base_forecast_bps,
                "realtime_edge_bps": realtime_edge_bps,
                "forecast_move_bps": forecast_bps,
                "probability_up": probability_up,
                "reference_z": reference_z,
                "samples": sample_count,
                "quote_volume_24h": quote_volume,
                "new_listing": is_new_listing,
                "first_seen_at": first_seen,
                "base_increment": row.get("base_increment"),
                "quote_increment": row.get("quote_increment"),
                "base_min_size": row.get("base_min_size"),
                "quote_min_size": row.get("quote_min_size"),
                "orderflow_fresh": bool(realtime.get("fresh")),
                "book_imbalance": self._float(realtime.get("book_imbalance")),
                "trade_flow_imbalance": self._float(realtime.get("trade_flow_imbalance")),
                "microprice_edge_bps": self._float(realtime.get("microprice_edge_bps")),
                "trade_velocity_ratio": self._float(realtime.get("trade_velocity_ratio"), 1.0),
                "trade_count": int(self._float(realtime.get("trade_count"))),
            }
            candidates.append(candidate)

            normal_setup = (
                sample_count >= self.config.min_samples
                and day_bps > 0
                and spread_bps <= self.config.max_spread_bps
                and quote_volume >= self.config.min_24h_quote_volume
                and forecast_bps > 0
                and (
                    recent_bps >= self.config.min_recent_momentum_bps
                    or realtime_edge_bps >= self.config.realtime_min_edge_bps
                )
            )
            high_risk_setup = (
                self.config.high_risk_enabled
                and not normal_setup
                and sample_count >= self.config.high_risk_min_samples
                and spread_bps <= self.config.high_risk_max_spread_bps
                and quote_volume >= self.config.high_risk_min_24h_quote_volume
                and forecast_bps > 0
                and (
                    recent_bps >= self.config.high_risk_min_recent_momentum_bps
                    or realtime_edge_bps > 0
                )
            )
            new_listing_setup = (
                self.config.high_risk_enabled
                and is_new_listing
                and sample_count >= self.config.new_listing_min_samples
                and spread_bps <= self.config.high_risk_max_spread_bps
                and quote_volume >= self.config.high_risk_min_24h_quote_volume
                and forecast_bps > 0
                and (recent_bps > 0 or realtime_edge_bps > 0)
            )

            if normal_setup or high_risk_setup or new_listing_setup:
                risk_tier = "normal" if normal_setup else "high"
                window = self.config.decision_window_seconds
                bucket = int(ts // window)
                window_end = float((bucket + 1) * window)
                reason = "multi_market_positive_momentum"
                if new_listing_setup and not normal_setup:
                    reason = "new_listing_orderflow_momentum"
                elif high_risk_setup and not normal_setup:
                    reason = "high_risk_orderflow_momentum"

                decisions.append(
                    {
                        "decision": "LONG",
                        "product_id": product_id,
                        "window_key": f"{product_id}:{window}:{bucket}:{risk_tier}",
                        "duration_seconds": window,
                        "seconds_remaining": max(1.0, window_end - ts),
                        "forecast_move_bps": forecast_bps,
                        "required_move_bps": 0.0,
                        "probability_up": probability_up,
                        "reference_z": reference_z,
                        "risk_tier": risk_tier,
                        "reason": reason,
                        "new_listing": is_new_listing,
                        "realtime_edge_bps": realtime_edge_bps,
                        "book_imbalance": candidate["book_imbalance"],
                        "trade_flow_imbalance": candidate["trade_flow_imbalance"],
                        "trade_velocity_ratio": candidate["trade_velocity_ratio"],
                        "base_increment": candidate.get("base_increment"),
                        "quote_increment": candidate.get("quote_increment"),
                        "base_min_size": candidate.get("base_min_size"),
                        "quote_min_size": candidate.get("quote_min_size"),
                    }
                )

        decisions.sort(
            key=lambda d: (
                self._float(d.get("forecast_move_bps")),
                self._float(d.get("probability_up")),
            ),
            reverse=True,
        )
        candidates.sort(
            key=lambda c: (
                self._float(c.get("forecast_move_bps")),
                self._float(c.get("quote_volume_24h")),
            ),
            reverse=True,
        )

        realtime_status: dict[str, Any] = {}
        if self.realtime is not None:
            try:
                realtime_status = dict(self.realtime.status())
            except Exception:
                realtime_status = {"last_error": "status_failed"}

        self.last_status = {
            "enabled": True,
            "mode": "coinbase_multi_market_orderflow",
            "read_only": True,
            "scanned_markets": len(self._products),
            "tradable_markets": len(tradable),
            "fundable_markets": len(fundable),
            "fundable_quotes": sorted(fundable_quotes),
            "last_signal": {"decisions": decisions},
            "top_candidates": candidates[:10],
            "realtime": realtime_status,
            "realtime_products": realtime_products,
            "evaluated_markets_this_tick": len(selected),
            "rotation_cursor": self._rotation_cursor,
            "daily_trade_target": self.config.daily_trade_target,
            "daily_profit_target_eur": self.config.daily_profit_target_eur,
            "high_risk_enabled": self.config.high_risk_enabled,
            "high_risk_policy": "normal_first_then_high_risk_positive_edge",
            "new_listing_policy": "baseline_then_boost_new_products_with_live_orderflow",
            "target_policy": "aggregate_realized_pnl_target_never_force_negative_edge",
            "generated_at": ts,
        }
        return dict(self.last_status)

    def status(self) -> dict[str, Any]:
        return dict(self.last_status)
