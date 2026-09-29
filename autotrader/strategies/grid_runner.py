"""GridRunner – conservative inventory-aware spot grid."""
from __future__ import annotations

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
            price = max(current_price * (1 + entry_offset), entry_price * (1 + exit_markup))
            notional = sell_size * current_price
            if not self._rm.check_order(self.name, notional):
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
