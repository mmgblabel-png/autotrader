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
        tp_pct = float(cfg.get("take_profit_pct", 1.0)) / 100
        sl_pct = float(cfg.get("stop_loss_pct", 0.3)) / 100
        cooldown = max(0.0, float(cfg.get("cooldown_seconds", 60)))
        now = time.monotonic()

        if self._om.open_orders(self.name):
            self._prev_price = current_price
            return
        if bool(cfg.get("_exchange_open_orders_snapshot_ready", False)) and int(cfg.get("_exchange_open_order_count", 0)) > 0:
            self._prev_price = current_price
            return

        if self._position <= 0 and self._prev_price > 0:
            move = (current_price - self._prev_price) / self._prev_price
            # Spot mode is intentionally long-only: negative momentum never
            # opens an uncovered short.
            if move >= momentum_pct and now - self._last_entry_ts >= cooldown:
                notional = size * current_price
                slippage_pct = abs(move) * 100 * 0.5
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
                log.info("SNIPE ENTER BUY %s %.8f @ %.4f (move=%.3f%%)", symbol, size, current_price, move * 100)

        elif self._position > 0 and self._entry_price > 0:
            pnl_pct = (current_price - self._entry_price) / self._entry_price
            if pnl_pct >= tp_pct:
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
