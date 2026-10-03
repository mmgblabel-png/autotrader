"""Autonomous read-only Polymarket BTC 5m/15m Z-score shadow worker.

It subscribes to Polymarket's public Chainlink 60-second TWAP stream, reads
public Gamma/CLOB market data and records hypothetical settlement PnL.  There
is no import of the Polymarket execution adapter and no order-submission code.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .market_data import BinaryMarket, PolymarketPublicData
from .model import (
    ZScoreConfig,
    annualized_realized_volatility,
    evaluate_binary_edge,
    fair_up_probability,
    fractional_kelly_stake,
)
from .shadow import PolymarketShadowLedger, ShadowPosition

log = logging.getLogger("autotrader.prediction.worker")


@dataclass
class WindowState:
    market: BinaryMarket
    strike: float | None = None
    strike_observed_at: float | None = None
    last_evaluation_at: float | None = None


class PolymarketZScoreShadowWorker:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        model_cfg = config.get("model", {}) or {}
        self.model_config = ZScoreConfig(
            min_sigma_annual=float(model_cfg.get("min_sigma_annual", 0.10)),
            max_sigma_annual=float(model_cfg.get("max_sigma_annual", 3.00)),
            min_seconds_to_expiry=float(model_cfg.get("min_seconds_to_expiry", 20.0)),
            twap_window_seconds=float(model_cfg.get("twap_window_seconds", 60.0)),
            log_drift_annual=float(model_cfg.get("log_drift_annual", 0.0)),
            min_after_cost_edge=float(model_cfg.get("min_after_cost_edge", 0.025)),
            safety_margin_bps=float(model_cfg.get("safety_margin_bps", 75.0)),
            kelly_fraction=float(model_cfg.get("kelly_fraction", 0.25)),
            max_bankroll_fraction=float(model_cfg.get("max_bankroll_fraction", 0.05)),
            max_stake=float(model_cfg.get("max_stake_usdc", 5.0)),
            min_stake=float(model_cfg.get("min_stake_usdc", 1.0)),
        )
        self.duration_seconds = tuple(
            int(x) for x in config.get("durations_seconds", [300, 900]) if int(x) in {300, 900}
        ) or (300, 900)
        self.fee_bps = max(0.0, float(config.get("assumed_fee_bps", 100.0)))
        self.slippage_bps = max(0.0, float(config.get("assumed_slippage_bps", 25.0)))
        self.strike_capture_grace_seconds = max(5.0, float(config.get("strike_capture_grace_seconds", 75.0)))
        self.max_sample_age_seconds = max(300.0, float(config.get("volatility_lookback_seconds", 3600.0)))
        self.market_data = PolymarketPublicData(float(config.get("http_timeout_seconds", 4.0)))
        self.ledger = PolymarketShadowLedger(
            config.get("state_path", "/data/polymarket_zscore_shadow.json"),
            bankroll_start=float(config.get("shadow_bankroll_usdc", 80.0)),
            promotion_min_trades=int(config.get("promotion_min_settled_trades", 200)),
            promotion_min_profit_factor=float(config.get("promotion_min_profit_factor", 1.20)),
            promotion_max_drawdown_pct=float(config.get("promotion_max_drawdown_pct", 8.0)),
        )
        self.samples: deque[tuple[float, float]] = deque(maxlen=10000)
        self.windows: dict[str, WindowState] = {}
        self.last_event_at = 0.0
        self.last_error: str | None = None

    def _prune_samples(self, now: float) -> None:
        cutoff = now - self.max_sample_age_seconds
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def _load_market(self, duration: int, timestamp: float) -> WindowState | None:
        slug = self.market_data.slug_for_window(duration, timestamp)
        existing = self.windows.get(slug)
        if existing is not None:
            return existing
        market = self.market_data.get_btc_updown_market(duration, timestamp)
        if market is None:
            return None
        state = WindowState(market=market)
        self.windows[slug] = state
        return state

    def _capture_strike(self, state: WindowState, timestamp: float, twap: float) -> None:
        if state.strike is not None:
            return
        if state.market.window_start <= timestamp <= state.market.window_start + self.strike_capture_grace_seconds:
            state.strike = twap
            state.strike_observed_at = timestamp

    def _settle_expired(self, timestamp: float, twap: float) -> None:
        for slug, state in list(self.windows.items()):
            if timestamp < state.market.window_end:
                continue
            if state.strike is not None:
                pnl = self.ledger.settle(slug, twap)
                if pnl is not None:
                    log.info("shadow settled slug=%s pnl=%.6f settlement=%.2f strike=%.2f", slug, pnl, twap, state.strike)
            self.windows.pop(slug, None)

    def _evaluate(self, state: WindowState, timestamp: float, twap: float) -> None:
        if state.strike is None or not self.ledger.can_open(state.market.slug):
            return
        seconds_left = state.market.window_end - timestamp
        if seconds_left < self.model_config.min_seconds_to_expiry:
            return
        if len(self.samples) < 12:
            return
        try:
            vol = annualized_realized_volatility(
                list(self.samples),
                min_observations=12,
                min_sigma_annual=self.model_config.min_sigma_annual,
                max_sigma_annual=self.model_config.max_sigma_annual,
            )
            estimate = fair_up_probability(
                spot=twap,
                strike=state.strike,
                sigma_annual=vol.sigma_annual,
                seconds_to_expiry=seconds_left,
                config=self.model_config,
            )
            up_book = self.market_data.order_book(state.market.up_token_id)
            down_book = self.market_data.order_book(state.market.down_token_id)
            if up_book.best_ask is None or down_book.best_ask is None:
                return
            decision = evaluate_binary_edge(
                estimate=estimate,
                up_ask=up_book.best_ask,
                down_ask=down_book.best_ask,
                fee_bps=self.fee_bps if state.market.fees_enabled else 0.0,
                slippage_bps=self.slippage_bps,
                config=self.model_config,
            )
            state.last_evaluation_at = timestamp
            if not decision.tradable:
                return
            stake = fractional_kelly_stake(
                bankroll=max(0.0, self.ledger.equity),
                probability=decision.probability,
                entry_price=decision.entry_price,
                config=self.model_config,
            )
            if stake <= 0:
                return
            if state.market.min_order_size > 0:
                min_cost = state.market.min_order_size * decision.entry_price
                if stake + 1e-9 < min_cost:
                    return
            position = ShadowPosition(
                market_slug=state.market.slug,
                side=decision.side,
                stake=stake,
                entry_price=decision.entry_price,
                probability=decision.probability,
                expected_edge=decision.after_cost_edge,
                fee_bps=self.fee_bps if state.market.fees_enabled else 0.0,
                opened_at=timestamp,
                window_end=state.market.window_end,
                strike=state.strike,
            )
            if self.ledger.open(position):
                log.info(
                    "shadow open slug=%s side=%s stake=%.4f price=%.4f fair=%.4f edge=%.4f z=%.3f sigma=%.3f",
                    state.market.slug,
                    decision.side,
                    stake,
                    decision.entry_price,
                    decision.probability,
                    decision.after_cost_edge,
                    estimate.z_score,
                    estimate.sigma_annual,
                )
        except (ValueError, OSError, TimeoutError) as exc:
            self.last_error = type(exc).__name__
            log.debug("shadow evaluation skipped slug=%s error=%s", state.market.slug, type(exc).__name__)

    def on_twap(self, timestamp: float, value: float) -> None:
        timestamp = float(timestamp)
        value = float(value)
        if not math.isfinite(timestamp) or not math.isfinite(value) or value <= 0:
            return
        self.last_event_at = time.time()
        self.last_error = None
        self._settle_expired(timestamp, value)
        self.samples.append((timestamp, value))
        self._prune_samples(timestamp)
        for duration in self.duration_seconds:
            try:
                state = self._load_market(duration, timestamp)
            except Exception as exc:
                self.last_error = type(exc).__name__
                continue
            if state is None:
                continue
            self._capture_strike(state, timestamp, value)
            self._evaluate(state, timestamp, value)

    def status(self) -> dict[str, Any]:
        payload = self.ledger.status()
        payload.update({
            "strategy": "polymarket_btc_zscore",
            "settlement_feed": "chainlink_btc_usd_twap_60s_via_polymarket_public_stream",
            "secondary_reference": "binance_reference_available_in_main_autotrader_only",
            "durations_seconds": list(self.duration_seconds),
            "volatility_samples": len(self.samples),
            "active_windows": [
                {
                    "slug": row.market.slug,
                    "window_start": row.market.window_start,
                    "window_end": row.market.window_end,
                    "strike": row.strike,
                    "strike_observed_at": row.strike_observed_at,
                    "last_evaluation_at": row.last_evaluation_at,
                }
                for row in self.windows.values()
            ],
            "last_stream_event_at": self.last_event_at or None,
            "last_error": self.last_error,
        })
        return payload


async def _run_stream(worker: PolymarketZScoreShadowWorker) -> None:
    try:
        from polymarket import AsyncPublicClient
        from polymarket.streams import CryptoPricesChainlinkTwapSpec
    except ImportError as exc:
        raise RuntimeError("install AutoTrader with the 'live' extra for the public Polymarket stream") from exc

    client = AsyncPublicClient()
    try:
        async with await client.subscribe(
            [CryptoPricesChainlinkTwapSpec(window_seconds=60, symbols=["btc/usd"])]
        ) as stream:
            async for event in stream:
                payload = event.payload
                timestamp_obj = payload.timestamp
                if hasattr(timestamp_obj, "timestamp"):
                    timestamp = float(timestamp_obj.timestamp())
                else:
                    timestamp = float(timestamp_obj)
                    if timestamp > 10_000_000_000:
                        timestamp /= 1000.0
                worker.on_twap(timestamp, float(payload.value))
    finally:
        await client.close()


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        root = yaml.safe_load(handle) or {}
    return dict(root.get("prediction_market_shadow", {}) or {})


async def main_async(config_path: str) -> int:
    config = load_config(config_path)
    if not bool(config.get("enabled", True)):
        log.info("prediction_market_shadow is disabled")
        return 0
    worker = PolymarketZScoreShadowWorker(config)
    status_path = Path(str(config.get("status_path", "/data/polymarket_zscore_status.json")))

    async def status_writer() -> None:
        while True:
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(worker.status(), separators=(",", ":"), sort_keys=True), "utf-8")
            await asyncio.sleep(max(5.0, float(config.get("status_interval_seconds", 15.0))))

    writer = asyncio.create_task(status_writer(), name="polymarket-zscore-status-writer")
    try:
        while True:
            try:
                await _run_stream(worker)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                worker.last_error = type(exc).__name__
                log.warning("Polymarket public stream reconnect after %s", type(exc).__name__)
                await asyncio.sleep(max(1.0, float(config.get("reconnect_seconds", 5.0))))
    finally:
        writer.cancel()
        try:
            await writer
        except asyncio.CancelledError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Polymarket BTC Z-score shadow worker")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(main_async(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
