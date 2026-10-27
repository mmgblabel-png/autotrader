"""Coinbase multi-market opportunity engine for the local RiskTrader.

The engine scores the complete public SPOT universe, then performs deeper
order-book sampling only for directly fundable quote currencies. It never
places orders; live execution remains exclusively in CoinbaseAutonomousExecutor.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData


@dataclass(frozen=True)
class CoinbaseOpportunityConfig:
    enabled: bool = True
    interval_seconds: float = 20.0
    universe_refresh_seconds: float = 120.0
    candidate_limit: int = 24
    sample_lookback_seconds: float = 600.0
    min_samples: int = 4
    min_recent_momentum_bps: float = 20.0
    max_spread_bps: float = 20.0
    min_quote_balance: float = 1.0
    min_24h_quote_volume: float = 10_000.0
    quote_currencies: tuple[str, ...] = ("EUR", "USDC")
    decision_window_seconds: int = 300
    daily_trade_target: int = 10
    daily_profit_target_eur: float = 1.0
    high_risk_enabled: bool = True
    high_risk_min_samples: int = 3
    high_risk_min_recent_momentum_bps: float = 8.0
    high_risk_max_spread_bps: float = 35.0
    high_risk_min_24h_quote_volume: float = 5_000.0

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
            interval_seconds=max(10.0, float(cfg.get("interval_seconds", 20.0))),
            universe_refresh_seconds=max(60.0, float(cfg.get("universe_refresh_seconds", 120.0))),
            candidate_limit=max(5, min(100, int(cfg.get("candidate_limit", 24)))),
            sample_lookback_seconds=max(120.0, float(cfg.get("sample_lookback_seconds", 600.0))),
            min_samples=max(3, int(cfg.get("min_samples", 4))),
            min_recent_momentum_bps=max(0.0, float(cfg.get("min_recent_momentum_bps", 20.0))),
            max_spread_bps=max(1.0, float(cfg.get("max_spread_bps", 20.0))),
            min_quote_balance=max(0.01, float(cfg.get("min_quote_balance", 1.0))),
            min_24h_quote_volume=max(0.0, float(cfg.get("min_24h_quote_volume", 10_000.0))),
            quote_currencies=quotes,
            decision_window_seconds=max(60, int(cfg.get("decision_window_seconds", 300))),
            daily_trade_target=max(1, int(cfg.get("daily_trade_target", 10))),
            daily_profit_target_eur=max(0.0, float(cfg.get("daily_profit_target_eur", 1.0))),
            high_risk_enabled=bool(cfg.get("high_risk_enabled", True)),
            high_risk_min_samples=max(2, int(cfg.get("high_risk_min_samples", 3))),
            high_risk_min_recent_momentum_bps=max(0.0, float(cfg.get("high_risk_min_recent_momentum_bps", 8.0))),
            high_risk_max_spread_bps=max(1.0, float(cfg.get("high_risk_max_spread_bps", 35.0))),
            high_risk_min_24h_quote_volume=max(0.0, float(cfg.get("high_risk_min_24h_quote_volume", 5_000.0))),
        )


class CoinbaseOpportunityEngine:
    def __init__(
        self,
        config: CoinbaseOpportunityConfig | dict[str, Any] | None = None,
        *,
        market_data: CoinbaseAdvancedMarketData | None = None,
        portfolio_id: str = "",
    ) -> None:
        self.config = config if isinstance(config, CoinbaseOpportunityConfig) else CoinbaseOpportunityConfig.from_mapping(config)
        self.market = market_data or CoinbaseAdvancedMarketData(timeout=5.0)
        self.portfolio_id = str(portfolio_id or "").strip()
        self._products: list[dict[str, Any]] = []
        self._universe_refreshed_at = 0.0
        self._samples: dict[str, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=80))
        self.last_status: dict[str, Any] = {
            "enabled": self.config.enabled,
            "last_signal": {"decisions": []},
            "scanned_markets": 0,
            "tradable_markets": 0,
            "fundable_markets": 0,
            "top_candidates": [],
        }

    @staticmethod
    def _float(value: object, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else default
        except (TypeError, ValueError):
            return default

    def _refresh_products(self, now: float) -> None:
        if self._products and now - self._universe_refreshed_at < self.config.universe_refresh_seconds:
            return
        self._products = self.market.list_spot_products()
        self._universe_refreshed_at = now

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

    def tick(self, now: float | None = None) -> dict[str, Any]:
        ts = float(time.time() if now is None else now)
        if not self.config.enabled:
            return dict(self.last_status)

        self._refresh_products(ts)
        balances = self._quote_balances()
        fundable_quotes = {
            q for q in self.config.quote_currencies
            if balances.get(q, 0.0) >= self.config.min_quote_balance
        }

        tradable = [p for p in self._products if bool(p.get("tradable"))]
        fundable = [
            p for p in tradable
            if str(p.get("quote") or "").upper() in fundable_quotes
        ]

        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in fundable:
            price = self._float(row.get("price"))
            change_pct = self._float(row.get("price_change_24h_pct"))
            volume_base = self._float(row.get("volume_24h"))
            quote_volume = price * volume_base if price > 0 and volume_base > 0 else 0.0
            if price <= 0 or quote_volume < min(
                self.config.min_24h_quote_volume,
                self.config.high_risk_min_24h_quote_volume if self.config.high_risk_enabled else self.config.min_24h_quote_volume,
            ):
                continue
            # Long-only SPOT: positive regime gets priority, but negative names
            # remain scanned and simply do not become LONG decisions.
            liquidity_score = math.log10(max(quote_volume, 1.0)) * 8.0
            score = max(-500.0, change_pct * 100.0) + liquidity_score
            ranked.append((score, row))
        ranked.sort(key=lambda item: item[0], reverse=True)

        candidates: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        for _, row in ranked[: self.config.candidate_limit]:
            product_id = str(row.get("product_id") or "").upper()
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
            forecast_bps = max(0.0, recent_bps * 0.85 + max(0.0, day_bps) * 0.05)
            probability_up = min(0.88, max(0.50, 0.50 + forecast_bps / 400.0))
            quote_volume = self._float(row.get("price")) * self._float(row.get("volume_24h"))
            candidate = {
                "product_id": product_id,
                "base": str(row.get("base") or "").upper(),
                "quote": str(row.get("quote") or "").upper(),
                "mid": mid,
                "spread_bps": spread_bps,
                "recent_momentum_bps": recent_bps,
                "change_24h_bps": day_bps,
                "forecast_move_bps": forecast_bps,
                "probability_up": probability_up,
                "reference_z": reference_z,
                "samples": sample_count,
                "quote_volume_24h": quote_volume,
            }
            candidates.append(candidate)

            normal_setup = (
                sample_count >= self.config.min_samples
                and recent_bps >= self.config.min_recent_momentum_bps
                and day_bps > 0
                and spread_bps <= self.config.max_spread_bps
                and quote_volume >= self.config.min_24h_quote_volume
                and forecast_bps > 0
            )
            high_risk_setup = (
                self.config.high_risk_enabled
                and not normal_setup
                and sample_count >= self.config.high_risk_min_samples
                and recent_bps >= self.config.high_risk_min_recent_momentum_bps
                and day_bps > -50.0
                and spread_bps <= self.config.high_risk_max_spread_bps
                and quote_volume >= self.config.high_risk_min_24h_quote_volume
                and forecast_bps > 0
            )
            if normal_setup or high_risk_setup:
                risk_tier = "normal" if normal_setup else "high"
                window = self.config.decision_window_seconds
                bucket = int(ts // window)
                window_end = float((bucket + 1) * window)
                decisions.append({
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
                    "reason": (
                        "multi_market_positive_momentum"
                        if normal_setup else "high_risk_positive_momentum_fallback"
                    ),
                })

        decisions.sort(
            key=lambda d: (
                self._float(d.get("forecast_move_bps")),
                self._float(d.get("probability_up")),
            ),
            reverse=True,
        )
        candidates.sort(
            key=lambda c: self._float(c.get("forecast_move_bps")),
            reverse=True,
        )

        self.last_status = {
            "enabled": True,
            "mode": "coinbase_multi_market_opportunity",
            "read_only": True,
            "scanned_markets": len(self._products),
            "tradable_markets": len(tradable),
            "fundable_markets": len(fundable),
            "fundable_quotes": sorted(fundable_quotes),
            "last_signal": {"decisions": decisions},
            "top_candidates": candidates[:10],
            "daily_trade_target": self.config.daily_trade_target,
            "daily_profit_target_eur": self.config.daily_profit_target_eur,
            "high_risk_enabled": self.config.high_risk_enabled,
            "high_risk_policy": "fallback_only_when_normal_route_unavailable",
            "target_policy": "aggregate_realized_pnl_target_never_force_negative_edge",
            "generated_at": ts,
        }
        return dict(self.last_status)

    def status(self) -> dict[str, Any]:
        return dict(self.last_status)
