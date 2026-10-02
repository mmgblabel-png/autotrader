"""GridRunner – conservative inventory-aware spot grid."""
from __future__ import annotations

import time

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.strategies.base import BaseStrategy

log = get_logger("GridRunner")


class GridRunner(BaseStrategy):
    """A one-cycle-at-a-time live grid that never sells unowned inventory."""

    name = "GridRunner"

    def tick(self) -> None:
        if not self._running or self._rm.is_killed(self.name):
            return

        cfg = self._config
        cooldown_until = float(cfg.get("_failure_cooldown_until", 0.0))
        if cooldown_until > time.time():
            return
        current_price = float(cfg.get("_current_price", 0.0))
        if current_price <= 0:
            return
        if self._om.open_orders(self.name):
            return
        if bool(cfg.get("_exchange_open_orders_snapshot_ready", False)) and int(cfg.get("_exchange_open_order_count", 0)) > 0:
            return

        symbol = str(cfg.get("symbol", "SOL-EUR")).upper()
        exchange = str(cfg.get("exchange", "bitvavo")).lower()
        order_value = float(cfg.get("order_value_eur", 6.0))
        size = float(cfg.get("order_size", 0.0)) or (order_value / current_price)
        entry_offset = max(0.0001, float(cfg.get("entry_offset_pct", 0.6)) / 100)
        exit_markup = max(0.0001, float(cfg.get("exit_markup_pct", 0.8)) / 100)

        live_snapshot = bool(cfg.get("_live_balance_snapshot_ready", False))
        available_quote = float(cfg.get("_available_quote", 0.0))
        available_base = float(cfg.get("_available_base", 0.0))
        bot_inventory = max(0.0, float(cfg.get("_bot_base_inventory", 0.0)))
        entry_price = max(0.0, float(cfg.get("_bot_average_entry_price", 0.0)))

        if bot_inventory > 0:
            sell_size = min(size, bot_inventory, available_base if live_snapshot else bot_inventory)
            if sell_size <= 0:
                return
            min_profit_exit_price = max(0.0, float(cfg.get("_min_profit_exit_price", 0.0)))
            price = max(
                current_price * (1 + entry_offset),
                entry_price * (1 + exit_markup),
                min_profit_exit_price,
            )
            notional = sell_size * current_price
            if not self._rm.check_order(self.name, notional, risk_reducing=True):
                return
            self._om.register(Order(
                exchange=exchange,
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=sell_size,
                price=round(price, 8),
                strategy=self.name,
            ))
            log.info("GRID SELL %s %.8f @ %.8f", symbol, sell_size, price)
            return

        if not bool(cfg.get("_autonomous_entry_allowed", True)):
            log.info(
                "GRID autonomous entry paused: %s",
                str(cfg.get("_autonomous_entry_reason") or "entry_not_selected"),
            )
            return

        last_sell_fill = max(0.0, float(cfg.get("_last_bot_sell_fill_at", 0.0) or 0.0))
        cycle_cooldown = max(0.0, float(cfg.get("cycle_cooldown_seconds", 60.0) or 60.0))
        if last_sell_fill > 0 and time.time() - last_sell_fill < cycle_cooldown:
            log.info(
                "GRID cooldown: BUY paused for %.1fs after confirmed SELL fill.",
                max(0.0, cycle_cooldown - (time.time() - last_sell_fill)),
            )
            return

        required_edge = max(0.0, float(cfg.get("_required_entry_edge_pct", 0.0)))
        target_edge = exit_markup * 100
        if required_edge > 0 and target_edge < required_edge:
            log.info(
                "GRID profit guard: BUY paused; target edge %.3f%% < required %.3f%%.",
                target_edge,
                required_edge,
            )
            return
        buy_price = current_price * (1 - entry_offset)
        buy_size = order_value / buy_price if order_value > 0 else size
        notional = buy_size * buy_price
        if live_snapshot and available_quote < notional:
            return
        if not self._rm.check_order(self.name, notional):
            return
        self._om.register(Order(
            exchange=exchange,
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=buy_size,
            price=round(buy_price, 8),
            strategy=self.name,
        ))
        log.info("GRID BUY %s %.8f @ %.8f", symbol, buy_size, buy_price)

    def on_order_failure(self, order: Order, category: str, reason: str) -> None:
        if category == "allocation":
            cooldown = max(1.0, float(self._config.get("allocation_failure_cooldown_seconds", 5.0)))
        else:
            cooldown = max(5.0, float(self._config.get("failure_cooldown_seconds", 60.0)))
        if "daily exposure limit exceeded" in reason.lower():
            cooldown = max(cooldown, float(self._config.get("exposure_reject_cooldown_seconds", 300.0)))
        self._config["_failure_cooldown_until"] = time.time() + cooldown
        self._config["_last_failure_category"] = category
        log.warning(
            "GRID order failure: cooldown %.0fs category=%s",
            cooldown,
            category,
        )

    def on_fill(self, order: Order, fill: dict) -> None:
        amount = float(fill.get("amount") or 0)
        price = float(fill.get("price") or 0)
        if amount <= 0 or price <= 0:
            return
        inventory = max(0.0, float(self._config.get("_bot_base_inventory", 0.0)))
        entry = max(0.0, float(self._config.get("_bot_average_entry_price", 0.0)))
        if order.side is OrderSide.BUY:
            total_cost = inventory * entry + amount * price
            inventory += amount
            entry = total_cost / inventory
        else:
            inventory = max(0.0, inventory - amount)
            if inventory == 0:
                entry = 0.0
        self._config["_bot_base_inventory"] = inventory
        self._config["_bot_average_entry_price"] = entry
