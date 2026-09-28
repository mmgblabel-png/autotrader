"""MarketMaker strategy – passive spread-based liquidity provision."""

from __future__ import annotations

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.core.profit_engine import Trade
from autotrader.strategies.base import BaseStrategy

log = get_logger("MarketMaker")


class MarketMaker(BaseStrategy):
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

        spread_pct = cfg.get("target_spread", 0.2) / 100
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
        notional = size * mid_price

        # Risk gate
        if not self._rm.check_order(self.name, notional):
            return

        # Place bid
        bid = Order(exchange=exchange, symbol=symbol, side=OrderSide.BUY,
                    order_type=OrderType.LIMIT, quantity=size, price=bid_price,
                    strategy=self.name)
        self._om.register(bid)
        log.info("BID  %s %.4f @ %.2f  (notional=%.2f)", symbol, size, bid_price, notional)

        # Place ask
        ask = Order(exchange=exchange, symbol=symbol, side=OrderSide.SELL,
                    order_type=OrderType.LIMIT, quantity=size, price=ask_price,
                    strategy=self.name)
        self._om.register(ask)
        cfg["_last_quote_ts"] = now
        log.info("ASK  %s %.4f @ %.2f  (notional=%.2f)", symbol, size, ask_price, notional)

        # Fills must come from exchange/paper execution events; never self-generate PnL.\n