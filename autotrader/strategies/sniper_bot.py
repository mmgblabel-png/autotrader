"""SniperBot – momentum entries with exchange-confirmed position tracking."""
from __future__ import annotations

import time

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
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

    def on_market_switch(self, old_market: str, new_market: str) -> None:
        super().on_market_switch(old_market, new_market)
        self._position = 0.0
        self._entry_price = 0.0
        self._prev_price = 0.0
        self._last_entry_ts = 0.0

    def _sync_live_inventory(self) -> None:
        cfg = self._config
        if not bool(cfg.get("_live_balance_snapshot_ready", False)):
            return
        inventory = max(0.0, float(cfg.get("_bot_base_inventory", 0.0)))
        entry = max(0.0, float(cfg.get("_bot_average_entry_price", 0.0)))
        self._position = inventory
        self._entry_price = entry if inventory > 0 else 0.0

    def tick(self) -> None:
        if not self._running or self._rm.is_killed(self.name):
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

        if self._om.open_orders(self.name):
            self._prev_price = current_price
            return
        if bool(cfg.get("_exchange_open_orders_snapshot_ready", False)) and int(cfg.get("_exchange_open_order_count", 0)) > 0:
            self._prev_price = current_price
            return

        if self._position <= 0:
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
            router_trigger = (
                signal_direction == "LONG"
                and signal_strength >= min_signal_strength
            )
            local_trigger = self._prev_price > 0 and move >= momentum_pct
            # In autonomous mode the router already aggregates multi-snapshot
            # momentum, order-book imbalance, liquidity, spread and slippage.
            # Keep the old one-tick momentum trigger only as a fallback.
            if (router_trigger or local_trigger) and now - self._last_entry_ts >= cooldown:
                required_edge = max(0.0, float(cfg.get("_required_entry_edge_pct", 0.0)))
                if required_edge > 0 and tp_target_value < required_edge:
                    log.info(
                        "SNIPE profit guard: entry paused; take-profit %.3f%% < required %.3f%%.",
                        tp_target_value,
                        required_edge,
                    )
                    self._prev_price = current_price
                    return
                notional = size * current_price
                router_slippage_pct = max(
                    0.0,
                    float(cfg.get("_autonomous_expected_slippage_bps", 0.0) or 0.0) / 100.0,
                )
                slippage_pct = max(abs(move) * 100 * 0.5, router_slippage_pct)
                available_quote = float(cfg.get("_available_quote", 0.0))
                if bool(cfg.get("_live_balance_snapshot_ready", False)) and available_quote < notional:
                    self._prev_price = current_price
                    return
                if not self._rm.check_order(self.name, notional, slippage_pct=slippage_pct):
                    self._prev_price = current_price
                    return
                order = Order(
                    exchange=exchange,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=size,
                    price=current_price,
                    strategy=self.name,
                )
                self._om.register(order)
                self._last_entry_ts = now
                log.info(
                    "SNIPE ENTER BUY %s %.8f @ %.4f (router=%s signal=%.1f move=%.3f%%)",
                    symbol,
                    size,
                    current_price,
                    router_trigger,
                    signal_strength,
                    move * 100,
                )

        elif self._position > 0 and self._entry_price > 0:
            pnl_pct = (current_price - self._entry_price) / self._entry_price
            min_profit_exit_price = max(0.0, float(cfg.get("_min_profit_exit_price", 0.0)))
            if pnl_pct >= tp_pct and (min_profit_exit_price <= 0 or current_price >= min_profit_exit_price):
                self._close_position(symbol, exchange, current_price, "TAKE-PROFIT")
            elif pnl_pct <= -sl_pct:
                self._close_position(symbol, exchange, current_price, "STOP-LOSS")

        self._prev_price = current_price

    def _close_position(self, symbol: str, exchange: str, price: float, reason: str) -> None:
        available_base = float(self._config.get("_available_base", self._position))
        size = min(self._position, available_base)
        if size <= 0:
            return
        notional = size * price
        if not self._rm.check_order(self.name, notional):
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
        log.info("SNIPE EXIT %s %s %.8f @ %.4f", reason, symbol, size, price)

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
            if self._position == 0:
                self._entry_price = 0.0
        self._config["_bot_base_inventory"] = self._position
        self._config["_bot_average_entry_price"] = self._entry_price
