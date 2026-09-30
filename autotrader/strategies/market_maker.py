"""MarketMaker strategy – passive spread-based liquidity provision."""

from __future__ import annotations

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.strategies.base import BaseStrategy

log = get_logger("MarketMaker")


class MarketMaker(BaseStrategy):
    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(value, high))

    def _update_adaptive_state(self, mid_price: float) -> tuple[float, float]:
        """Update per-tick EWMA volatility/momentum and return spread + momentum."""
        cfg = self._config
        base_spread = float(cfg.get("target_spread", 0.80)) / 100
        if not bool(cfg.get("adaptive_enabled", True)):
            cfg["_adaptive_spread_pct"] = base_spread * 100
            return base_spread, 0.0

        previous = float(cfg.get("_adaptive_prev_mid", 0.0))
        alpha = self._clamp(float(cfg.get("adaptive_ema_alpha", 0.18)), 0.01, 1.0)
        if previous > 0:
            ret = (mid_price - previous) / previous
            vol = alpha * abs(ret) + (1 - alpha) * float(cfg.get("_adaptive_vol_ema", 0.0))
            momentum = alpha * ret + (1 - alpha) * float(cfg.get("_adaptive_momentum_ema", 0.0))
            cfg["_adaptive_vol_ema"] = vol
            cfg["_adaptive_momentum_ema"] = momentum
            cfg["_adaptive_samples"] = int(cfg.get("_adaptive_samples", 0)) + 1
        else:
            vol = float(cfg.get("_adaptive_vol_ema", 0.0))
            momentum = float(cfg.get("_adaptive_momentum_ema", 0.0))
        cfg["_adaptive_prev_mid"] = mid_price

        fee_pct = float(cfg.get("estimated_fee_pct", 0.25)) / 100
        slippage_pct = float(cfg.get("estimated_slippage_pct", 0.05)) / 100
        cost_floor = 2 * (fee_pct + slippage_pct)
        min_spread = max(cost_floor, float(cfg.get("adaptive_min_spread_pct", 0.65)) / 100)
        max_spread = max(min_spread, float(cfg.get("adaptive_max_spread_pct", 1.50)) / 100)
        vol_spread = vol * float(cfg.get("adaptive_volatility_multiplier", 4.0))
        spread = self._clamp(max(base_spread, min_spread, vol_spread), min_spread, max_spread)
        cfg["_adaptive_spread_pct"] = spread * 100
        cfg["_adaptive_volatility_bps"] = vol * 10000
        cfg["_adaptive_momentum_bps"] = momentum * 10000
        return spread, momentum

    """
    Quotes a bid and an ask around the mid-price.

    Config keys (under ``strategies.market_maker``):
        symbol          : trading pair, e.g. "BTC/USDT"
        exchange        : exchange name
        order_size      : order quantity (base asset)
        target_spread   : desired spread in %, e.g. 0.2
        max_order_size  : upper bound on order quantity
        min_order_size  : lower bound on order quantity
        max_daily_loss  : forwarded to RiskManager
    """

    name = "MarketMaker"

    def tick(self) -> None:  # noqa: C901
        if not self._running:
            return

        if self._rm.is_killed(self.name):
            log.warning("Kill-switch active – skipping tick.")
            return

        cfg = self._config
        symbol: str = cfg.get("symbol", "BTC/USDT")
        exchange: str = cfg.get("exchange", "binance")
        mid_price: float = cfg.get("_mid_price", 30_000.0)
        if mid_price <= 0:
            return

        spread_pct, adaptive_momentum = self._update_adaptive_state(mid_price)
        size: float = cfg.get("order_size", 0.001)

        # Never quote more frequently than configured and never stack duplicate
        # active quotes. This reduces churn, fees and accidental order buildup.
        import time
        now = time.monotonic()
        last_quote = float(cfg.get("_last_quote_ts", 0.0))
        if now - last_quote < float(cfg.get("quote_refresh_seconds", 10)):
            return
        if self._om.open_orders(self.name):
            return
        if bool(cfg.get("_exchange_open_orders_snapshot_ready", False)) and int(cfg.get("_exchange_open_order_count", 0)) > 0:
            log.info("MM skipped: Bitvavo already has an open BTC-EUR order.")
            return

        # Clamp size
        size = max(cfg.get("min_order_size", 0.0001), min(size, cfg.get("max_order_size", 1.0)))

        # Require the quoted edge to cover an estimated round-trip cost.
        fee_pct = float(cfg.get("estimated_fee_pct", 0.25)) / 100
        slippage_pct = float(cfg.get("estimated_slippage_pct", 0.05)) / 100
        minimum_spread = 2 * (fee_pct + slippage_pct)
        if spread_pct <= minimum_spread:
            log.info("MM skipped: spread %.4f%% <= estimated costs %.4f%%",
                     spread_pct * 100, minimum_spread * 100)
            return

        bid_price = round(mid_price * (1 - spread_pct / 2), 2)
        ask_price = round(mid_price * (1 + spread_pct / 2), 2)
        entry_price = max(0.0, float(cfg.get("_bot_average_entry_price", 0.0)))
        exit_markup_value = float(cfg.get("cycle_exit_markup_pct", cfg.get("target_spread", 0.80)))
        exit_markup_pct = exit_markup_value / 100
        min_profit_exit_price = max(0.0, float(cfg.get("_min_profit_exit_price", 0.0)))
        if bool(cfg.get("inventory_cycle_mode", True)) and entry_price > 0:
            ask_price = max(
                ask_price,
                round(entry_price * (1 + exit_markup_pct), 2),
                min_profit_exit_price,
            )
        notional = size * mid_price

        # Risk gate
        if not self._rm.check_order(self.name, notional):
            return

        live_snapshot = bool(cfg.get("_live_balance_snapshot_ready", False))
        can_bid = True
        can_ask = True
        if live_snapshot:
            available_quote = float(cfg.get("_available_quote", 0.0))
            available_base = float(cfg.get("_available_base", 0.0))
            cycle_mode = bool(cfg.get("inventory_cycle_mode", True))
            bot_inventory = max(0.0, float(cfg.get("_bot_base_inventory", 0.0)))
            min_size = float(cfg.get("min_order_size", 0.0001))
            if cycle_mode:
                if bot_inventory >= min_size:
                    can_bid = False
                    can_ask = available_base >= min_size
                    size = min(size, bot_inventory, available_base)
                    log.info("MM inventory cycle: bot inventory %.8f, quoting SELL only.", bot_inventory)
                elif bot_inventory > 0:
                    can_bid = False
                    can_ask = False
                    log.info("MM inventory cycle paused: bot inventory %.8f is below minimum %.8f.", bot_inventory, min_size)
                else:
                    can_bid = available_quote >= (size * bid_price)
                    can_ask = False
                    if not bool(cfg.get("_autonomous_entry_allowed", True)):
                        can_bid = False
                        log.info(
                            "MM autonomous BUY paused: %s",
                            str(cfg.get("_autonomous_entry_reason") or "entry_not_selected"),
                        )
                    required_edge = max(0.0, float(cfg.get("_required_entry_edge_pct", 0.0)))
                    if required_edge > 0 and exit_markup_value < required_edge:
                        can_bid = False
                        log.info(
                            "MM profit guard: BUY paused; target exit edge %.3f%% < required %.3f%%.",
                            exit_markup_value,
                            required_edge,
                        )
                    cooldown = max(0.0, float(cfg.get("cycle_cooldown_seconds", 60)))
                    last_sell_fill = max(0.0, float(cfg.get("_last_bot_sell_fill_at", 0.0)))
                    import time as _time
                    in_cooldown = last_sell_fill > 0 and (_time.time() - last_sell_fill) < cooldown
                    samples = int(cfg.get("_adaptive_samples", 0))
                    guard = float(cfg.get("adaptive_downtrend_guard_pct", 0.12)) / 100
                    downtrend = (
                        bool(cfg.get("adaptive_enabled", True))
                        and samples >= int(cfg.get("adaptive_min_samples", 6))
                        and adaptive_momentum < -guard
                    )
                    if in_cooldown:
                        can_bid = False
                        log.info(
                            "MM cooldown: BUY paused for %.1fs after the last SELL fill.",
                            max(0.0, cooldown - (_time.time() - last_sell_fill)),
                        )
                    elif downtrend:
                        can_bid = False
                        log.info(
                            "MM adaptive guard: BUY paused; momentum %.2f bps < -%.2f bps.",
                            adaptive_momentum * 10000,
                            guard * 10000,
                        )
                    else:
                        log.info(
                            "MM inventory cycle: no bot inventory, quoting BUY only (adaptive spread %.3f%%).",
                            spread_pct * 100,
                        )
            else:
                can_bid = available_quote >= (size * bid_price)
                can_ask = available_base >= size
            if not can_bid and (not cycle_mode or bot_inventory <= 0):
                log.info("MM bid skipped: insufficient available quote balance.")
            if not can_ask and (not cycle_mode or bot_inventory >= min_size):
                log.info("MM ask skipped: insufficient available bot-owned base balance.")

        placed = False
        if can_bid:
            bid = Order(exchange=exchange, symbol=symbol, side=OrderSide.BUY,
                        order_type=OrderType.LIMIT, quantity=size, price=bid_price,
                        strategy=self.name)
            self._om.register(bid)
            placed = True
            log.info("BID  %s %.4f @ %.2f  (notional=%.2f)", symbol, size, bid_price, notional)

        if can_ask:
            ask = Order(exchange=exchange, symbol=symbol, side=OrderSide.SELL,
                        order_type=OrderType.LIMIT, quantity=size, price=ask_price,
                        strategy=self.name)
            self._om.register(ask)
            placed = True
            log.info("ASK  %s %.4f @ %.2f  (notional=%.2f)", symbol, size, ask_price, notional)

        if placed:
            cfg["_last_quote_ts"] = now

        # Fills must come from exchange/paper execution events; never self-generate PnL.\n