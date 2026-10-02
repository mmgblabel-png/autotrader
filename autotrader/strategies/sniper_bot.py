"""SniperBot – momentum entries with exchange-confirmed position tracking."""
from __future__ import annotations

import time

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.core.spot_protection import (
    evaluate_spot_protection,
    mark_protection_order_failed,
    mark_protection_order_pending,
    mark_protection_sell_fill,
)
from autotrader.strategies.base import BaseStrategy

log = get_logger("SniperBot")


class SniperBot(BaseStrategy):
    """Long-only spot momentum bot with confirmed-fill position state."""

    name = "SniperBot"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._position = 0.0
        self._entry_price = 0.0
        self._prev_price = 0.0
        self._last_entry_ts = 0.0
        self._last_entry_attempt_ts = 0.0

    def on_market_switch(self, old_market: str, new_market: str) -> None:
        super().on_market_switch(old_market, new_market)
        self._position = 0.0
        self._entry_price = 0.0
        self._prev_price = 0.0
        self._last_entry_ts = 0.0
        self._last_entry_attempt_ts = 0.0

    def _sync_live_inventory(self) -> None:
        cfg = self._config
        if not bool(cfg.get("_live_balance_snapshot_ready", False)):
            return
        inventory = max(0.0, float(cfg.get("_bot_base_inventory", 0.0)))
        entry = max(0.0, float(cfg.get("_bot_average_entry_price", 0.0)))
        self._position = inventory
        self._entry_price = entry if inventory > 0 else 0.0

    def tick(self) -> None:
        if not self._running:
            return

        cfg = self._config
        self._sync_live_inventory()
        current_price = float(cfg.get("_current_price", 0.0))
        if current_price <= 0:
            return

        symbol = str(cfg.get("symbol", "XRP-EUR")).upper()
        exchange = str(cfg.get("exchange", "bitvavo")).lower()
        size = float(cfg.get("order_size", 1.0))
        order_value = float(cfg.get("order_value_eur", 0.0))
        if order_value > 0:
            size = order_value / current_price

        momentum_pct = float(cfg.get("momentum_pct", 0.5)) / 100
        tp_target_value = float(cfg.get("take_profit_pct", 1.0))
        tp_pct = tp_target_value / 100
        sl_pct = float(cfg.get("stop_loss_pct", 0.3)) / 100
        cooldown = max(0.0, float(cfg.get("cooldown_seconds", 60)))
        now = time.monotonic()
        entry_killed = self._rm.is_killed(self.name)

        local_open = bool(self._om.open_orders(self.name))
        exchange_open = (
            bool(cfg.get("_exchange_open_orders_snapshot_ready", False))
            and int(cfg.get("_exchange_open_order_count", 0)) > 0
        )

        if self._position <= 0:
            if local_open or exchange_open:
                self._prev_price = current_price
                return
            if entry_killed:
                cfg["_autonomous_entry_allowed"] = False
                cfg["_autonomous_entry_reason"] = "risk_kill_switch"
                self._prev_price = current_price
                return
            autonomous_allowed = bool(cfg.get("_autonomous_entry_allowed", True))
            if not autonomous_allowed:
                self._prev_price = current_price
                return

            move = (
                (current_price - self._prev_price) / self._prev_price
                if self._prev_price > 0 else 0.0
            )
            signal_strength = float(cfg.get("_autonomous_signal_strength", 0.0) or 0.0)
            min_signal_strength = float(cfg.get("_autonomous_min_signal_strength", 62.0) or 62.0)
            signal_direction = str(cfg.get("_autonomous_signal_direction", "WAIT")).upper()
            router_momentum_pct = float(cfg.get("_autonomous_momentum_pct", 0.0) or 0.0)
            min_router_momentum_pct = max(
                0.0,
                float(cfg.get("autonomous_min_momentum_pct", 0.12) or 0.12),
            )
            max_router_momentum_pct = max(
                min_router_momentum_pct,
                float(cfg.get("autonomous_max_momentum_pct", 0.80) or 0.80),
            )
            router_momentum_ok = (
                router_momentum_pct >= min_router_momentum_pct
                and router_momentum_pct <= max_router_momentum_pct
            )
            router_trigger = (
                signal_direction == "LONG"
                and signal_strength >= min_signal_strength
                and router_momentum_ok
            )
            local_trigger = self._prev_price > 0 and move >= momentum_pct
            # In autonomous mode a generic router score is not enough for a
            # momentum strategy. Require sustained router momentum as well.
            has_router_signal = "_autonomous_signal_direction" in cfg
            entry_trigger = router_trigger if has_router_signal else local_trigger
            attempt_cooldown = max(
                1.0,
                float(cfg.get("entry_attempt_cooldown_seconds", 30.0) or 30.0),
            )
            exit_cooldown_ready = now - self._last_entry_ts >= cooldown
            attempt_ready = now - self._last_entry_attempt_ts >= attempt_cooldown
            if entry_trigger and exit_cooldown_ready and attempt_ready:
                required_edge = max(0.0, float(cfg.get("_required_entry_edge_pct", 0.0)))
                if required_edge > 0 and tp_target_value < required_edge:
                    log.info(
                        "SNIPE profit guard: entry paused; take-profit %.3f%% < required %.3f%%.",
                        tp_target_value,
                        required_edge,
                    )
                    self._prev_price = current_price
                    return
                entry_slippage_cap_pct = max(
                    0.01,
                    float(
                        cfg.get(
                            "entry_max_slippage_pct",
                            cfg.get("max_slippage_pct", 0.12),
                        ) or 0.12
                    ),
                )
                entry_cap_price = current_price * (1.0 + entry_slippage_cap_pct / 100.0)
                if order_value > 0:
                    size = order_value / entry_cap_price
                notional = size * entry_cap_price
                router_slippage_pct = max(
                    0.0,
                    float(cfg.get("_autonomous_expected_slippage_bps", 0.0) or 0.0) / 100.0,
                )
                slippage_pct = max(
                    abs(move) * 100 * 0.5,
                    router_slippage_pct,
                )
                available_quote = float(cfg.get("_available_quote", 0.0))
                if bool(cfg.get("_live_balance_snapshot_ready", False)) and available_quote < notional:
                    self._prev_price = current_price
                    return
                if not self._rm.check_order(self.name, notional, slippage_pct=slippage_pct, symbol=symbol):
                    self._prev_price = current_price
                    return
                order = Order(
                    exchange=exchange,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=size,
                    price=entry_cap_price,
                    time_in_force="IOC",
                    post_only=False,
                    strategy=self.name,
                )
                self._om.register(order)
                self._last_entry_attempt_ts = now
                log.info(
                    "SNIPE ENTER IOC %s %.8f cap=%.4f observed=%.4f "
                    "(signal=%.1f router_momentum=%.3f%% slippage_cap=%.3f%%)",
                    symbol,
                    size,
                    entry_cap_price,
                    current_price,
                    signal_strength,
                    router_momentum_pct,
                    entry_slippage_cap_pct,
                )

        elif self._position > 0 and self._entry_price > 0:
            protection = evaluate_spot_protection(
                cfg,
                entry_price=self._entry_price,
                current_price=current_price,
                quantity=self._position,
            )
            if protection.exit_required and (local_open or exchange_open):
                self._prev_price = current_price
                return
            if not protection.exit_required and (local_open or exchange_open):
                self._prev_price = current_price
                return
            if protection.exit_required:
                fraction = protection.fraction
                self._close_position(
                    symbol,
                    exchange,
                    current_price,
                    protection.reason.upper(),
                    fraction=fraction,
                    protection=protection,
                )
            else:
                pnl_pct = (current_price - self._entry_price) / self._entry_price
                min_profit_exit_price = max(0.0, float(cfg.get("_min_profit_exit_price", 0.0)))
                if pnl_pct >= tp_pct and (min_profit_exit_price <= 0 or current_price >= min_profit_exit_price):
                    self._close_position(symbol, exchange, current_price, "TAKE-PROFIT")
                elif pnl_pct <= -sl_pct:
                    self._close_position(symbol, exchange, current_price, "STOP-LOSS")

        self._prev_price = current_price

    def _close_position(
        self,
        symbol: str,
        exchange: str,
        price: float,
        reason: str,
        *,
        fraction: float = 1.0,
        protection=None,
    ) -> None:
        available_base = float(self._config.get("_available_base", self._position))
        requested = self._position * max(0.0, min(1.0, float(fraction)))
        size = min(requested, self._position, available_base)
        if size <= 0:
            return
        minimum_sell = self.minimum_tradable_base(price)
        if protection is not None and getattr(protection, "action", "") == "PARTIAL_EXIT":
            remaining = max(0.0, self._position - size)
            if size < minimum_sell or (remaining > 0 and remaining < minimum_sell):
                size = min(self._position, available_base)
        if minimum_sell > 0 and size < minimum_sell:
            self.mark_dust_inventory(size, price)
            log.info(
                "SNIPE dust ignored: %s inventory %.8f below tradable minimum %.8f.",
                symbol,
                size,
                minimum_sell,
            )
            return
        self.clear_dust_inventory()
        notional = size * price
        if not self._rm.check_order(self.name, notional, symbol=symbol, risk_reducing=True):
            return
        order = Order(
            exchange=exchange,
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=size,
            price=price,
            strategy=self.name,
        )
        self._om.register(order)
        if protection is not None:
            mark_protection_order_pending(self._config, protection)
        log.info("SNIPE EXIT %s %s %.8f @ %.4f", reason, symbol, size, price)

    def on_order_failure(self, order: Order, category: str, reason: str) -> None:
        if self._config.get("_protection_pending_action"):
            mark_protection_order_failed(self._config)

    def on_fill(self, order: Order, fill: dict) -> None:
        amount = float(fill.get("amount") or 0)
        price = float(fill.get("price") or 0)
        if amount <= 0 or price <= 0:
            return
        if order.side is OrderSide.BUY:
            previous_cost = self._position * self._entry_price
            self._position += amount
            self._entry_price = (previous_cost + amount * price) / self._position
        else:
            self._position = max(0.0, self._position - amount)
            mark_protection_sell_fill(
                self._config,
                remaining_quantity=self._position,
            )
            if self._position == 0:
                self._entry_price = 0.0
                # Enforce the configured cooldown from the confirmed exit fill,
                # preventing immediate buy-back churn.
                self._last_entry_ts = time.monotonic()
        self._config["_bot_base_inventory"] = self._position
        self._config["_bot_average_entry_price"] = self._entry_price
