"""GridRunner – conservative inventory-aware spot grid."""
from __future__ import annotations

import time

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.core.spot_protection import (
    evaluate_spot_protection,
    mark_protection_order_failed,
    mark_protection_order_pending,
    mark_protection_sell_fill,
    reset_protection_state,
)
from autotrader.strategies.base import BaseStrategy

log = get_logger("GridRunner")


class GridRunner(BaseStrategy):
    """A one-cycle-at-a-time live grid that never sells unowned inventory."""

    name = "GridRunner"

    def tick(self) -> None:
        if not self._running:
            return

        cfg = self._config
        entry_killed = self._rm.is_killed(self.name)
        cooldown_until = float(cfg.get("_failure_cooldown_until", 0.0))
        execution_cancel_cooldown_until = float(
            cfg.get("_execution_cancel_cooldown_until", 0.0)
        )
        current_price = float(cfg.get("_current_price", 0.0))
        if current_price <= 0:
            return

        symbol = str(cfg.get("symbol", "SOL-EUR")).upper()
        exchange = str(cfg.get("exchange", "bitvavo")).lower()
        order_value = float(cfg.get("order_value_eur", 6.0))
        quote_to_eur = self.quote_to_eur_rate()
        if order_value > 0 and quote_to_eur <= 0:
            return
        size = float(cfg.get("order_size", 0.0)) or (
            order_value / (current_price * quote_to_eur)
        )
        entry_offset = max(0.0001, float(cfg.get("entry_offset_pct", 0.6)) / 100)
        exit_markup = max(0.0001, float(cfg.get("exit_markup_pct", 0.8)) / 100)

        live_snapshot = bool(cfg.get("_live_balance_snapshot_ready", False))
        available_quote = float(cfg.get("_available_quote", 0.0))
        available_base = float(cfg.get("_available_base", 0.0))
        bot_inventory = max(0.0, float(cfg.get("_bot_base_inventory", 0.0)))
        entry_price = max(0.0, float(cfg.get("_bot_average_entry_price", 0.0)))
        local_open = bool(self._om.open_orders(self.name))
        exchange_open = (
            bool(cfg.get("_exchange_open_orders_snapshot_ready", False))
            and int(cfg.get("_exchange_open_order_count", 0)) > 0
        )

        if bot_inventory > 0:
            protection = evaluate_spot_protection(
                cfg,
                entry_price=entry_price,
                current_price=current_price,
                quantity=bot_inventory,
            )
            if protection.exit_required:
                if local_open or exchange_open:
                    log.warning(
                        "GRID protective exit waiting for open order cancel: %s reason=%s pnl=%.3f%%",
                        symbol,
                        protection.reason,
                        protection.pnl_pct,
                    )
                    return
                protected_size = bot_inventory * protection.fraction
                protected_size = min(
                    bot_inventory,
                    protected_size,
                    available_base if live_snapshot else bot_inventory,
                )
                minimum_sell = self.minimum_tradable_base(current_price)
                if protection.action == "PARTIAL_EXIT":
                    remaining = max(0.0, bot_inventory - protected_size)
                    if (
                        protected_size < minimum_sell
                        or (remaining > 0 and remaining < minimum_sell)
                    ):
                        protected_size = min(
                            bot_inventory,
                            available_base if live_snapshot else bot_inventory,
                        )
                if protected_size > 0 and (
                    minimum_sell <= 0 or protected_size >= minimum_sell
                ):
                    notional = self.quote_notional_to_eur(protected_size * current_price)
                    if self._rm.check_order(
                        self.name,
                        notional,
                        symbol=symbol,
                        risk_reducing=True,
                    ):
                        order = Order(
                            exchange=exchange,
                            symbol=symbol,
                            side=OrderSide.SELL,
                            order_type=OrderType.MARKET,
                            quantity=protected_size,
                            price=current_price,
                            time_in_force="IOC",
                            post_only=False,
                            strategy=self.name,
                        quote_to_eur=quote_to_eur,
                        )
                        self._om.register(order)
                        mark_protection_order_pending(cfg, protection)
                        log.warning(
                            "GRID PROTECT %s %s %.8f @ %.8f pnl=%.3f%% peak_dd=%.3f%%",
                            protection.reason,
                            symbol,
                            protected_size,
                            current_price,
                            protection.pnl_pct,
                            protection.drawdown_from_peak_pct,
                        )
                    return

        if local_open or exchange_open:
            return

        if bot_inventory > 0:
            sellable_inventory = min(
                bot_inventory,
                available_base if live_snapshot else bot_inventory,
            )
            minimum_sell = self.minimum_tradable_base(current_price)
            sell_size = min(size, sellable_inventory)
            if (
                minimum_sell > 0
                and sellable_inventory >= minimum_sell
                and 0 < sell_size < minimum_sell
            ):
                # Exits are risk-reducing. Raise a too-small configured slice to
                # the venue minimum rather than incorrectly labelling the whole
                # bot inventory as dust.
                sell_size = minimum_sell
            if sell_size > 0 and (minimum_sell <= 0 or sell_size >= minimum_sell):
                self.clear_dust_inventory()
                min_profit_exit_price = max(0.0, float(cfg.get("_min_profit_exit_price", 0.0)))
                price = max(
                    current_price * (1 + entry_offset),
                    entry_price * (1 + exit_markup),
                    min_profit_exit_price,
                )
                notional = self.quote_notional_to_eur(sell_size * current_price)
                if not self._rm.check_order(self.name, notional, symbol=symbol, risk_reducing=True):
                    return
                self._om.register(Order(
                    exchange=exchange,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=sell_size,
                    price=round(price, 8),
                    strategy=self.name,
                    quote_to_eur=quote_to_eur,
                ))
                log.info("GRID SELL %s %.8f @ %.8f", symbol, sell_size, price)
                return
            self.mark_dust_inventory(sellable_inventory, current_price)
            log.info(
                "[%s] GRID inventory not currently sellable: %s sellable %.8f from bot inventory %.8f; minimum %.8f.",
                self.name,
                symbol,
                sellable_inventory,
                bot_inventory,
                minimum_sell,
            )
            return
        else:
            self.clear_dust_inventory()
            # Protection state belongs to the previous owned position/market.
            # Once inventory is verified flat and there is no local/exchange
            # order (guarded above), a stale protective latch must never cancel
            # the next market's fresh BUY.
            if (
                cfg.get("_protective_exit_requested", False)
                or cfg.get("_protection_pending_action")
                or float(cfg.get("_protection_entry_price", 0.0) or 0.0) > 0
            ):
                reset_protection_state(cfg)

        if entry_killed:
            cfg["_autonomous_entry_allowed"] = False
            cfg["_autonomous_entry_reason"] = "risk_kill_switch"
            return

        if max(cooldown_until, execution_cancel_cooldown_until) > time.time():
            return

        entry_allowed, entry_reason = self.autonomous_entry_decision()
        if not entry_allowed:
            log.info(
                "[%s] GRID autonomous entry paused: %s market=%s",
                self.name,
                entry_reason,
                symbol,
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
        requested_notional = (
            order_value
            if order_value > 0
            else self.quote_notional_to_eur(size * buy_price)
        )
        if live_snapshot:
            requested_notional = min(
                requested_notional,
                self.quote_notional_to_eur(available_quote),
            )
        notional = self.bounded_entry_notional(
            requested_notional,
            price=buy_price,
            symbol=symbol,
        )
        if notional <= 0:
            log.info(
                "GRID BUY skipped: no tradable risk/quote headroom for %s (requested %.2f EUR, quote %.2f EUR).",
                symbol,
                order_value,
                self.quote_notional_to_eur(available_quote) if live_snapshot else -1.0,
            )
            return
        buy_size = notional / (buy_price * quote_to_eur)
        if not self._rm.check_order(self.name, notional, symbol=symbol):
            return
        if notional + 1e-9 < order_value:
            log.info(
                "GRID BUY resized: %s %.2f -> %.2f EUR to fit quote/risk headroom.",
                symbol,
                order_value,
                notional,
            )
        self._om.register(Order(
            exchange=exchange,
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=buy_size,
            price=round(buy_price, 8),
            strategy=self.name,
            quote_to_eur=quote_to_eur,
        ))
        log.info("GRID BUY %s %.8f @ %.8f", symbol, buy_size, buy_price)

    def on_order_failure(self, order: Order, category: str, reason: str) -> None:
        if self._config.get("_protection_pending_action"):
            mark_protection_order_failed(self._config)
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
            mark_protection_sell_fill(
                self._config,
                remaining_quantity=inventory,
            )
            if inventory == 0:
                entry = 0.0
        self._config["_bot_base_inventory"] = inventory
        self._config["_bot_average_entry_price"] = entry
