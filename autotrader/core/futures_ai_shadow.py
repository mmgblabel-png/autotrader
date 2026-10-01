"""Persistent futures + AI shadow research engine.

The engine consumes only public perpetual market data. It can simulate both
long and short positions, account for configured trading friction and
approximate funding, and score candidates using the existing deterministic
online-logistic shadow model plus futures-specific funding/basis features.

It intentionally has no execution adapter and cannot place real orders.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from autotrader.ml.shadow import signal_from_recent, walk_forward


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class FuturesMarketState:
    history: list[dict[str, float]] = field(default_factory=list)
    position_side: str = "flat"
    entry_price: float = 0.0
    position_notional_usd: float = 0.0
    position_opened_at: float = 0.0
    funding_pnl_usd: float = 0.0
    last_funding_at: float = 0.0
    completed_trades: int = 0
    wins: int = 0
    losses: int = 0
    realized_net_pnl_usd: float = 0.0
    peak_equity_usd: float = 0.0
    max_drawdown_usd: float = 0.0
    last_mark_price: float = 0.0
    last_oracle_price: float = 0.0
    last_funding_rate: float = 0.0
    last_open_interest: float = 0.0
    last_signal: str = "HOLD"
    probability_up: float = 0.5
    confidence: float = 0.0
    model_accuracy_pct: float = 0.0
    source: str = ""
    updated_at: float = 0.0


class FuturesAIShadowEngine:
    """Futures research loop with hard no-live guarantees."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.path = Path(str(self.config.get("path", "/data/futures_ai_shadow.json")))
        self.markets = [
            str(x).upper().strip()
            for x in (self.config.get("markets") or ["BTC", "ETH", "SOL", "XRP"])
            if str(x).strip()
        ]
        self.min_history = max(6, int(self.config.get("min_history", 24)))
        self.history_size = max(self.min_history + 4, int(self.config.get("history_size", 240)))
        self.capital_per_market = max(1.0, float(self.config.get("shadow_capital_usd_per_market", 12.5)))
        self.stake_usd = max(1.0, float(self.config.get("stake_usd", 4.0)))
        self.leverage = _clamp(float(self.config.get("leverage", 1.0)), 1.0, 1.0)
        self.max_position_notional_usd = max(
            1.0, float(self.config.get("max_position_notional_usd", 5.0))
        )
        self.long_threshold = _clamp(float(self.config.get("long_probability_threshold", 0.66)), 0.51, 0.95)
        self.short_threshold = _clamp(float(self.config.get("short_probability_threshold", 0.34)), 0.05, 0.49)
        self.min_confidence = _clamp(float(self.config.get("min_confidence", 0.30)), 0.0, 1.0)
        self.take_profit_pct = max(0.05, float(self.config.get("take_profit_pct", 1.0)))
        self.stop_loss_pct = max(0.05, float(self.config.get("stop_loss_pct", 0.60)))
        self.fee_pct_each_leg = max(0.0, float(self.config.get("fee_pct_each_leg", 0.05)))
        self.slippage_pct_each_leg = max(0.0, float(self.config.get("slippage_pct_each_leg", 0.03)))
        self.promotion_min_completed_trades = max(
            1, int(self.config.get("promotion_min_completed_trades", 30))
        )
        self.promotion_min_winrate_pct = float(self.config.get("promotion_min_winrate_pct", 55.0))
        self.promotion_min_net_pnl_usd = float(self.config.get("promotion_min_net_pnl_usd", 1.0))
        self.promotion_max_drawdown_pct = float(self.config.get("promotion_max_drawdown_pct", 6.0))
        self.promotion_min_model_accuracy_pct = float(
            self.config.get("promotion_min_model_accuracy_pct", 52.0)
        )
        self._states: dict[str, FuturesMarketState] = {}
        self._load()

    def _state(self, coin: str) -> FuturesMarketState:
        coin = coin.upper()
        state = self._states.setdefault(coin, FuturesMarketState())
        if state.peak_equity_usd <= 0:
            state.peak_equity_usd = self.capital_per_market
        return state

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return
        if not isinstance(raw, dict):
            return
        allowed = set(FuturesMarketState.__dataclass_fields__)
        for coin, payload in (raw.get("markets") or {}).items():
            if not isinstance(payload, dict):
                continue
            kwargs = {k: v for k, v in payload.items() if k in allowed}
            try:
                self._states[str(coin).upper()] = FuturesMarketState(**kwargs)
            except (TypeError, ValueError):
                continue

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "markets": {coin: asdict(state) for coin, state in self._states.items()},
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except OSError:
            pass

    @staticmethod
    def _momentum_pct(history: list[dict[str, float]], lookback: int) -> float:
        if len(history) <= lookback:
            return 0.0
        old = float(history[-1 - lookback].get("close") or 0.0)
        new = float(history[-1].get("close") or 0.0)
        if old <= 0 or new <= 0:
            return 0.0
        return (new / old - 1.0) * 100.0

    @staticmethod
    def _oi_change_pct(history: list[dict[str, float]], lookback: int = 5) -> float:
        if len(history) <= lookback:
            return 0.0
        old = float(history[-1 - lookback].get("open_interest") or 0.0)
        new = float(history[-1].get("open_interest") or 0.0)
        if old <= 0 or new <= 0:
            return 0.0
        return (new / old - 1.0) * 100.0

    def _ensemble(self, state: FuturesMarketState) -> tuple[float, float, str, float]:
        history = state.history
        if len(history) < self.min_history:
            return 0.5, 0.0, "HOLD", 0.0

        ml_signal = signal_from_recent(history)
        probability = float(ml_signal.probability_up)
        momentum = self._momentum_pct(history, min(5, len(history) - 1))
        oi_change = self._oi_change_pct(history, min(5, len(history) - 1))
        mark = state.last_mark_price
        oracle = state.last_oracle_price or mark
        basis_pct = ((mark / oracle) - 1.0) * 100.0 if mark > 0 and oracle > 0 else 0.0
        funding_bps = state.last_funding_rate * 10000.0

        # Futures-specific overlay: momentum/OI confirmation pushes with trend,
        # while rich positive funding and positive basis penalize crowded longs
        # (negative values do the symmetric thing for shorts).
        momentum_adjust = _clamp(momentum * 0.015, -0.08, 0.08)
        funding_adjust = _clamp(funding_bps * 0.003, -0.06, 0.06)
        basis_adjust = _clamp(basis_pct * 0.04, -0.06, 0.06)
        oi_adjust = 0.0
        if abs(momentum) > 1e-9 and oi_change > 0:
            oi_adjust = math.copysign(min(0.04, oi_change * 0.002), momentum)

        probability = _clamp(
            probability + momentum_adjust + oi_adjust - funding_adjust - basis_adjust,
            0.01,
            0.99,
        )
        confidence = abs(probability - 0.5) * 2.0
        action = (
            "LONG" if probability >= self.long_threshold
            else "SHORT" if probability <= self.short_threshold
            else "HOLD"
        )
        minimum_train = max(8, min(50, len(history) // 2))
        validation = walk_forward(history, minimum_train=minimum_train)
        accuracy = float(validation.get("accuracy_pct") or 0.0)
        return probability, confidence, action, accuracy

    def _apply_funding(self, state: FuturesMarketState, timestamp: float) -> None:
        if state.position_side == "flat" or state.position_notional_usd <= 0:
            state.last_funding_at = timestamp
            return
        if state.last_funding_at <= 0:
            state.last_funding_at = timestamp
            return
        elapsed_hours = _clamp((timestamp - state.last_funding_at) / 3600.0, 0.0, 1.5)
        if elapsed_hours <= 0:
            return
        payment = state.position_notional_usd * state.last_funding_rate * elapsed_hours
        if state.position_side == "long":
            state.funding_pnl_usd -= payment
        elif state.position_side == "short":
            state.funding_pnl_usd += payment
        state.last_funding_at = timestamp

    def _price_return_pct(self, state: FuturesMarketState, mark: float) -> float:
        if state.entry_price <= 0 or state.position_side == "flat":
            return 0.0
        raw = (mark / state.entry_price - 1.0) * 100.0
        return raw if state.position_side == "long" else -raw

    def _unrealized(self, state: FuturesMarketState, mark: float) -> float:
        return (
            state.position_notional_usd * self._price_return_pct(state, mark) / 100.0
            + state.funding_pnl_usd
        )

    def _update_drawdown(self, state: FuturesMarketState, mark: float) -> None:
        equity = self.capital_per_market + state.realized_net_pnl_usd
        if state.position_side != "flat":
            equity += self._unrealized(state, mark)
        state.peak_equity_usd = max(state.peak_equity_usd, equity, self.capital_per_market)
        state.max_drawdown_usd = max(state.max_drawdown_usd, state.peak_equity_usd - equity)

    def _enter(self, state: FuturesMarketState, side: str, mark: float, timestamp: float) -> None:
        state.position_side = side
        state.entry_price = mark
        state.position_notional_usd = min(
            self.max_position_notional_usd,
            self.stake_usd * self.leverage,
        )
        state.position_opened_at = timestamp
        state.funding_pnl_usd = 0.0
        state.last_funding_at = timestamp

    def _close(self, state: FuturesMarketState, mark: float) -> float:
        price_pnl = state.position_notional_usd * self._price_return_pct(state, mark) / 100.0
        friction_pct = 2.0 * (self.fee_pct_each_leg + self.slippage_pct_each_leg)
        friction = state.position_notional_usd * friction_pct / 100.0
        net = price_pnl + state.funding_pnl_usd - friction
        state.realized_net_pnl_usd += net
        state.completed_trades += 1
        if net > 0:
            state.wins += 1
        elif net < 0:
            state.losses += 1
        state.position_side = "flat"
        state.entry_price = 0.0
        state.position_notional_usd = 0.0
        state.position_opened_at = 0.0
        state.funding_pnl_usd = 0.0
        state.last_funding_at = 0.0
        return net

    def update(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        coin = str(snapshot.get("coin") or "").upper().strip()
        mark = float(snapshot.get("mark_price") or 0.0)
        if not self.enabled or not coin or mark <= 0:
            return {"updated": False}
        state = self._state(coin)
        timestamp = float(snapshot.get("timestamp") or time.time())
        state.last_mark_price = mark
        state.last_oracle_price = float(snapshot.get("oracle_price") or mark)
        state.last_funding_rate = float(snapshot.get("funding_rate") or 0.0)
        state.last_open_interest = float(snapshot.get("open_interest") or 0.0)
        state.source = str(snapshot.get("source") or "public_perpetual")
        state.updated_at = timestamp
        state.history.append({
            "close": mark,
            "volume": float(snapshot.get("day_notional_volume_usd") or 0.0),
            "funding": state.last_funding_rate,
            "open_interest": state.last_open_interest,
            "oracle": state.last_oracle_price,
            "timestamp": timestamp,
        })
        state.history = state.history[-self.history_size :]

        self._apply_funding(state, timestamp)
        probability, confidence, action, accuracy = self._ensemble(state)
        state.probability_up = probability
        state.confidence = confidence
        state.last_signal = action
        state.model_accuracy_pct = accuracy

        closed = False
        if state.position_side != "flat":
            return_pct = self._price_return_pct(state, mark)
            opposite = (
                (state.position_side == "long" and action == "SHORT")
                or (state.position_side == "short" and action == "LONG")
            )
            if return_pct >= self.take_profit_pct or return_pct <= -self.stop_loss_pct or opposite:
                self._close(state, mark)
                closed = True

        if (
            not closed
            and state.position_side == "flat"
            and confidence >= self.min_confidence
            and action in {"LONG", "SHORT"}
        ):
            self._enter(state, action.lower(), mark, timestamp)

        self._update_drawdown(state, mark)
        self._save()
        return {
            "updated": True,
            "coin": coin,
            "signal": state.last_signal,
            "probability_up": round(state.probability_up, 6),
            "confidence": round(state.confidence, 6),
            "position_side": state.position_side,
            "live_orders_sent": False,
        }

    def status(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for coin in self.markets:
            state = self._state(coin)
            trades = state.completed_trades
            winrate = state.wins / trades * 100.0 if trades else 0.0
            max_dd_pct = (
                state.max_drawdown_usd / max(self.capital_per_market, state.peak_equity_usd, 1.0) * 100.0
            )
            mark = state.last_mark_price
            oracle = state.last_oracle_price or mark
            basis_pct = ((mark / oracle) - 1.0) * 100.0 if mark > 0 and oracle > 0 else 0.0
            promotable = (
                trades >= self.promotion_min_completed_trades
                and winrate >= self.promotion_min_winrate_pct
                and state.realized_net_pnl_usd >= self.promotion_min_net_pnl_usd
                and max_dd_pct <= self.promotion_max_drawdown_pct
                and state.model_accuracy_pct >= self.promotion_min_model_accuracy_pct
            )
            drop_ready = (
                trades >= self.promotion_min_completed_trades
                and (
                    state.realized_net_pnl_usd < 0.0
                    or winrate < max(0.0, self.promotion_min_winrate_pct - 10.0)
                    or max_dd_pct > self.promotion_max_drawdown_pct
                    or (
                        state.model_accuracy_pct > 0
                        and state.model_accuracy_pct < self.promotion_min_model_accuracy_pct - 5.0
                    )
                )
            )
            review = "PROMOTE_REVIEW" if promotable else ("DROP" if drop_ready else "KEEP")
            rows.append({
                "coin": coin,
                "symbol": f"{coin}-USD-PERP",
                "source": state.source,
                "mark_price": round(mark, 8),
                "oracle_price": round(oracle, 8),
                "basis_pct": round(basis_pct, 4),
                "funding_rate": round(state.last_funding_rate, 10),
                "funding_bps": round(state.last_funding_rate * 10000.0, 4),
                "open_interest": round(state.last_open_interest, 4),
                "samples": len(state.history),
                "probability_up": round(state.probability_up, 6),
                "confidence": round(state.confidence, 6),
                "model_accuracy_pct": round(state.model_accuracy_pct, 2),
                "signal": state.last_signal,
                "position_side": state.position_side,
                "entry_price": round(state.entry_price, 8),
                "position_notional_usd": round(state.position_notional_usd, 4),
                "unrealized_pnl_usd": round(self._unrealized(state, mark), 4)
                    if state.position_side != "flat" and mark > 0 else 0.0,
                "completed_trades": trades,
                "wins": state.wins,
                "losses": state.losses,
                "winrate_pct": round(winrate, 2),
                "realized_net_pnl_usd": round(state.realized_net_pnl_usd, 4),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "review_status": review,
                "updated_at": state.updated_at,
            })

        return {
            "enabled": self.enabled,
            "mode": "futures_ai_shadow",
            "live_capable": False,
            "live_orders_sent": False,
            "can_short": True,
            "configured_leverage": self.leverage,
            "max_live_leverage": 0.0,
            "markets": rows,
            "promotion_rules": {
                "min_completed_trades": self.promotion_min_completed_trades,
                "min_winrate_pct": self.promotion_min_winrate_pct,
                "min_net_pnl_usd": self.promotion_min_net_pnl_usd,
                "max_drawdown_pct": self.promotion_max_drawdown_pct,
                "min_model_accuracy_pct": self.promotion_min_model_accuracy_pct,
                "meaning": "PROMOTE_REVIEW means research review only; never automatic live futures.",
            },
            "research_sources": [
                {"repo": "hummingbot/hummingbot", "role": "perpetual connector and market-making patterns"},
                {"repo": "freqtrade/freqtrade", "role": "futures, shorting and liquidation-risk semantics; concepts only"},
                {"repo": "nautechsystems/nautilus_trader", "role": "event-driven research/live architecture patterns"},
                {"repo": "AI4Finance-Foundation/FinRL-Trading", "role": "AI-native modular research pipeline patterns"},
            ],
            "model": "online-logistic + momentum + open-interest + funding/basis overlay",
            "note": "Public data only. No API keys, signing, futures account or order execution code.",
        }


__all__ = ["FuturesAIShadowEngine", "FuturesMarketState"]
