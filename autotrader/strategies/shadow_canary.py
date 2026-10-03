from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.strategies.base import BaseStrategy

log = get_logger("ShadowCanary")


class ShadowCanaryStrategy(BaseStrategy):
    """One persistent live canary slot for a promoted shadow candidate.

    The slot is deliberately conservative:
    - only one candidate is locked at a time;
    - one open order maximum is enforced again by StrategyAllocator;
    - candidate selection is persisted on /data;
    - orders still pass normal allocation, fund-risk and execution-gateway gates.
    """

    name = "ShadowCanary"

    def __init__(self, order_manager, risk_manager, profit_engine, config: dict) -> None:
        super().__init__(order_manager, risk_manager, profit_engine, config)
        self._prices: list[float] = []
        self._state_path = Path(
            str(config.get("runtime_state_path", "/data/shadow_canary_runtime.json"))
        )
        self._load_candidate()

    def _load_candidate(self) -> None:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(payload, dict) or not bool(payload.get("locked", False)):
            return
        candidate = payload.get("candidate") or {}
        if not isinstance(candidate, dict):
            return
        for key, value in candidate.items():
            if key.startswith("_"):
                continue
            self._config[key] = value
        self._config["_canary_locked"] = True
        self._config["_canary_active"] = True
        self._config["_canary_selected_at"] = float(payload.get("selected_at", 0.0) or 0.0)

    def _persist_candidate(self) -> None:
        candidate_keys = {
            "candidate_name",
            "kind",
            "strategy_version",
            "symbol",
            "exchange",
            "order_value_eur",
            "lookback",
            "entry_z",
            "entry_rebound_pct",
            "max_downtrend_pct",
            "exit_z",
            "min_exit_net_pct",
            "take_profit_pct",
            "stop_loss_pct",
            "breakout_buffer_pct",
            "min_avg_move_pct",
            "min_vol_expansion_ratio",
            "max_entry_spike_pct",
            "trailing_exit_pct",
            "ema_fast",
            "ema_slow",
            "momentum_lookback",
            "momentum_pct",
        }
        payload = {
            "version": 1,
            "locked": bool(self._config.get("_canary_locked", False)),
            "selected_at": float(self._config.get("_canary_selected_at", 0.0) or 0.0),
            "candidate": {
                key: self._config[key]
                for key in candidate_keys
                if key in self._config
            },
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".shadow-canary-",
            suffix=".tmp",
            dir=str(self._state_path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._state_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    @property
    def candidate_name(self) -> str:
        return str(self._config.get("candidate_name") or "")

    @property
    def candidate_locked(self) -> bool:
        return bool(self._config.get("_canary_locked", False))

    def configure_candidate(
        self,
        name: str,
        candidate_cfg: dict[str, Any],
        evidence: dict[str, Any],
    ) -> bool:
        name = str(name or "").strip()
        if not name or not bool(evidence.get("canary_ready", False)):
            return False
        if self.candidate_locked:
            return self.candidate_name == name
        if self._om.open_orders(self.name):
            return False
        if max(0.0, float(self._config.get("_bot_base_inventory", 0.0) or 0.0)) > 0:
            return False

        symbol = str(candidate_cfg.get("symbol") or "").upper().strip()
        kind = str(candidate_cfg.get("kind") or "").lower().strip()
        if not symbol or kind not in {"mean_reversion", "volatility_breakout", "sniper_v2"}:
            return False

        previous = str(self._config.get("symbol") or "").upper()
        preserved = {
            key: self._config.get(key)
            for key in (
                "enabled",
                "live_capable",
                "allocation_eur",
                "max_order_eur",
                "max_open_orders",
                "exclusive_symbol",
                "max_daily_loss",
                "max_position_size",
                "max_slippage_pct",
                "max_consecutive_errors",
                "runtime_state_path",
            )
            if key in self._config
        }
        self._config.update(dict(candidate_cfg))
        self._config.update(preserved)
        self._config["candidate_name"] = name
        self._config["order_value_eur"] = min(
            max(5.0, float(self._config.get("canary_order_eur", 6.0) or 6.0)),
            max(5.0, float(self._config.get("max_order_eur", 6.0) or 6.0)),
        )
        self._config["_canary_locked"] = True
        self._config["_canary_active"] = True
        self._config["_canary_selected_at"] = time.time()
        self._config["_shadow_score_at_selection"] = float(evidence.get("score") or 0.0)
        self._config["_shadow_net_at_selection"] = float(
            evidence.get("realized_net_pnl_eur") or 0.0
        )
        self._prices = []
        if previous and previous != symbol:
            self.on_market_switch(previous, symbol)
        self._persist_candidate()
        log.info(
            "Canary locked: candidate=%s kind=%s market=%s shadow_score=%.1f shadow_net=%.4f",
            name,
            kind,
            symbol,
            float(evidence.get("score") or 0.0),
            float(evidence.get("realized_net_pnl_eur") or 0.0),
        )
        return True

    def _entry_signal(self, price: float) -> tuple[bool, str]:
        cfg = self._config
        kind = str(cfg.get("kind") or "").lower()
        if kind == "mean_reversion":
            lookback = max(12, int(cfg.get("lookback", 40)))
            if len(self._prices) < lookback:
                return False, "warming_up"
            window = self._prices[-lookback:]
            mean = statistics.fmean(window)
            stdev = statistics.pstdev(window)
            z = (price - mean) / stdev if stdev > 1e-12 else 0.0
            entry_z = -abs(float(cfg.get("entry_z", 2.0)))
            previous = self._prices[-2] if len(self._prices) >= 2 else price
            rebound = (price / previous - 1.0) * 100 if previous > 0 else 0.0
            rebound_pct = max(0.0, float(cfg.get("entry_rebound_pct", 0.08)))
            max_downtrend_pct = max(0.0, float(cfg.get("max_downtrend_pct", 1.20)))
            segment = max(4, min(8, lookback // 4))
            early_mean = statistics.fmean(window[:segment])
            late_mean = statistics.fmean(window[-segment:])
            trend_pct = (late_mean / early_mean - 1) * 100 if early_mean > 0 else 0.0
            allowed = (
                z <= entry_z
                and rebound >= rebound_pct
                and trend_pct >= -max_downtrend_pct
            )
            return allowed, f"mean_reversion_z_{z:.2f}_rebound_{rebound:.2f}"

        if kind == "volatility_breakout":
            lookback = max(10, int(cfg.get("lookback", 30)))
            if len(self._prices) <= lookback:
                return False, "warming_up"
            previous = self._prices[-lookback - 1 : -1]
            high = max(previous)
            buffer_pct = float(cfg.get("breakout_buffer_pct", 0.16))
            breakout = high * (1 + buffer_pct / 100)
            returns = [
                abs(previous[i] / previous[i - 1] - 1) * 100
                for i in range(1, len(previous))
                if previous[i - 1] > 0
            ]
            avg_move = statistics.fmean(returns) if returns else 0.0
            recent_move = statistics.fmean(returns[-5:]) if len(returns) >= 5 else avg_move
            expansion = recent_move / avg_move if avg_move > 1e-9 else 0.0
            breakout_move = (price / high - 1.0) * 100 if high > 0 else 0.0
            allowed = (
                price >= breakout
                and avg_move >= float(cfg.get("min_avg_move_pct", 0.03))
                and expansion >= float(cfg.get("min_vol_expansion_ratio", 0.0))
                and breakout_move <= float(cfg.get("max_entry_spike_pct", 1.25))
            )
            return allowed, f"vol_breakout_{avg_move:.3f}_x{expansion:.2f}"

        if kind == "sniper_v2":
            fast = max(3, int(cfg.get("ema_fast", 6)))
            slow = max(fast + 2, int(cfg.get("ema_slow", 18)))
            if len(self._prices) < slow + 1:
                return False, "warming_up"

            def ema(values: list[float], span: int) -> float:
                alpha = 2.0 / (span + 1.0)
                value = values[0]
                for item in values[1:]:
                    value = alpha * item + (1.0 - alpha) * value
                return value

            recent = self._prices[-max(slow * 2, slow + 3) :]
            fast_ema = ema(recent[-max(fast * 2, fast) :], fast)
            slow_ema = ema(recent, slow)
            lookback = max(2, int(cfg.get("momentum_lookback", 3)))
            ref = self._prices[-lookback - 1]
            momentum = (price / ref - 1.0) * 100 if ref > 0 else 0.0
            minimum = float(cfg.get("momentum_pct", 0.22))
            maximum = max(minimum, float(cfg.get("max_entry_spike_pct", 0.90)))
            return (
                fast_ema > slow_ema and minimum <= momentum <= maximum,
                f"sniper_momentum_{momentum:.2f}",
            )

        return False, "unsupported_kind"

    def _exit_signal(self, price: float, entry: float) -> tuple[bool, str]:
        cfg = self._config
        if entry <= 0:
            return False, "missing_entry"
        move = (price / entry - 1.0) * 100
        kind = str(cfg.get("kind") or "").lower()
        stop_loss = abs(float(cfg.get("stop_loss_pct", 1.0)))
        take_profit = abs(float(cfg.get("take_profit_pct", 1.0)))
        round_trip_cost = 2.0 * (
            float(cfg.get("estimated_fee_pct", 0.25))
            + float(cfg.get("estimated_slippage_pct", 0.05))
        )
        min_exit = max(
            round_trip_cost + 0.15,
            float(cfg.get("min_exit_net_pct", 0.75)),
        )
        if move >= take_profit:
            return True, "take_profit"
        if move <= -stop_loss:
            return True, "stop_loss"

        if kind == "mean_reversion":
            lookback = max(12, int(cfg.get("lookback", 40)))
            if len(self._prices) >= lookback:
                window = self._prices[-lookback:]
                mean = statistics.fmean(window)
                stdev = statistics.pstdev(window)
                z = (price - mean) / stdev if stdev > 1e-12 else 0.0
                if z >= float(cfg.get("exit_z", -0.05)) and move >= min_exit:
                    return True, f"mean_exit_{z:.2f}"
            return False, "hold"

        peak = max(float(cfg.get("_canary_peak_price", entry) or entry), price)
        cfg["_canary_peak_price"] = peak
        trail_move = (price / peak - 1.0) * 100 if peak > 0 else 0.0
        trailing = abs(float(cfg.get("trailing_exit_pct", 0.45)))
        if move >= min_exit and trail_move <= -trailing:
            return True, "trailing_profit_exit"
        return False, "hold"

    def tick(self) -> None:
        if not self._running or not bool(self._config.get("_canary_active", False)):
            return
        price = float(self._config.get("_current_price", 0.0) or 0.0)
        if price <= 0 or not math.isfinite(price):
            return

        self._prices.append(price)
        self._prices = self._prices[-240:]

        if not bool(self._config.get("_live_balance_snapshot_ready", False)):
            return
        if not bool(self._config.get("_exchange_open_orders_snapshot_ready", False)):
            return
        if self._om.open_orders(self.name):
            return
        if int(self._config.get("_exchange_open_order_count", 0) or 0) > 0:
            return

        symbol = str(self._config.get("symbol") or "").upper()
        exchange = str(self._config.get("exchange", "bitvavo")).lower()
        quote_to_eur = self.quote_to_eur_rate()
        if not symbol or quote_to_eur <= 0:
            return

        inventory = max(0.0, float(self._config.get("_bot_base_inventory", 0.0) or 0.0))
        entry = max(0.0, float(self._config.get("_bot_average_entry_price", 0.0) or 0.0))
        available_base = max(0.0, float(self._config.get("_available_base", 0.0) or 0.0))
        available_quote = max(0.0, float(self._config.get("_available_quote", 0.0) or 0.0))

        if inventory > 0:
            should_exit, reason = self._exit_signal(price, entry)
            if not should_exit:
                return
            sellable = min(inventory, available_base)
            minimum = self.minimum_tradable_base(price)
            if minimum > 0 and sellable + 1e-12 < minimum:
                return
            notional_eur = self.quote_notional_to_eur(sellable * price)
            if sellable <= 0 or not self._rm.check_order(
                self.name,
                notional_eur,
                symbol=symbol,
                risk_reducing=True,
            ):
                return
            self._om.register(
                Order(
                    exchange=exchange,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=sellable,
                    price=price,
                    strategy=self.name,
                    quote_to_eur=quote_to_eur,
                )
            )
            log.info(
                "CANARY SELL candidate=%s market=%s qty=%.8f @ %.8f reason=%s",
                self.candidate_name,
                symbol,
                sellable,
                price,
                reason,
            )
            return

        allowed, gate_reason = self.autonomous_entry_decision()
        if not allowed:
            return
        enter, reason = self._entry_signal(price)
        if not enter:
            return

        requested_eur = min(
            max(5.0, float(self._config.get("order_value_eur", 6.0) or 6.0)),
            self.quote_notional_to_eur(available_quote),
        )
        notional_eur = self.bounded_entry_notional(
            requested_eur,
            price=price,
            symbol=symbol,
        )
        if notional_eur <= 0:
            return
        qty = notional_eur / (price * quote_to_eur)
        minimum = self.minimum_tradable_base(price)
        if minimum > 0 and qty + 1e-12 < minimum:
            return
        if not self._rm.check_order(self.name, notional_eur, symbol=symbol):
            return
        self._om.register(
            Order(
                exchange=exchange,
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=qty,
                price=price,
                strategy=self.name,
                quote_to_eur=quote_to_eur,
            )
        )
        log.info(
            "CANARY BUY candidate=%s kind=%s market=%s eur=%.2f reason=%s",
            self.candidate_name,
            str(self._config.get("kind") or ""),
            symbol,
            notional_eur,
            reason,
        )

    def on_fill(self, order: Order, fill: dict) -> None:
        amount = max(0.0, float(fill.get("amount") or fill.get("filledAmount") or 0.0))
        price = max(0.0, float(fill.get("price") or fill.get("averagePrice") or order.price or 0.0))
        if amount <= 0 or price <= 0:
            return
        inventory = max(0.0, float(self._config.get("_bot_base_inventory", 0.0) or 0.0))
        entry = max(0.0, float(self._config.get("_bot_average_entry_price", 0.0) or 0.0))
        if order.side is OrderSide.BUY:
            total_cost = inventory * entry + amount * price
            inventory += amount
            entry = total_cost / inventory if inventory > 0 else 0.0
            self._config["_canary_peak_price"] = price
        else:
            inventory = max(0.0, inventory - amount)
            if inventory <= 1e-12:
                inventory = 0.0
                entry = 0.0
                self._config["_canary_peak_price"] = 0.0
        self._config["_bot_base_inventory"] = inventory
        self._config["_bot_average_entry_price"] = entry

    def on_order_failure(self, order: Order, category: str, reason: str) -> None:
        self._config["_failure_cooldown_until"] = time.time() + 30.0
        log.warning(
            "CANARY order failure candidate=%s category=%s reason=%s",
            self.candidate_name,
            category,
            reason,
        )
