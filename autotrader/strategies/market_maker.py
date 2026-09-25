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
        max_order_eur   : maximum notional per quoted order
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
        mid_price: float = cfg.get("_mid_price", 30_000.0)   # injected by connector
        spread_pct: float = cfg.get("target_spread", 0.2) / 100
        size: float = cfg.get("order_size", 0.001)
        min_size: float = cfg.get("min_order_size", 0.0001)
        max_size: float = cfg.get("max_order_size", 1.0)
        max_order_eur: float = float(cfg.get("max_order_eur", 32.0))

        if mid_price <= 0 or max_order_eur <= 0:
            log.warning("Invalid price or max_order_eur; skipping tick.")
            return

        # Recompute quantity from the current price so every individual quote
        # remains inside the EUR notional cap, even when BTC moves sharply.
        # The ask is the worst-case quote for notional sizing; use it so both
        # bid and ask remain below the cap after spread is applied.
        quote_max_price = mid_price * (1 + spread_pct / 2)
        price_capped_size = max(0.0, (max_order_eur - 1e-9) / quote_max_price)
        if price_capped_size < min_size:
            log.warning(
                "Price %.2f makes the configured minimum size %.8f exceed "
                "the €%.2f order cap; skipping tick.",
                mid_price, min_size, max_order_eur,
            )
            return

        # Clamp size
        size = max(min_size, min(size, max_size, price_capped_size))

        bid_price = round(mid_price * (1 - spread_pct / 2), 2)
        ask_price = round(mid_price * (1 + spread_pct / 2), 2)
        notional = size * mid_price

        # Guard against floating-point rounding or future changes to the
        # sizing calculation. This is deliberately before any order object is
        # registered.
        if notional > max_order_eur + 1e-9:
            log.warning("Computed notional %.8f exceeds €%.2f; skipping tick.", notional, max_order_eur)
            return

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
        log.info("ASK  %s %.4f @ %.2f  (notional=%.2f)", symbol, size, ask_price, notional)

        # Simulate a fill for demonstration purposes
        self._simulate_fill(bid, ask, symbol, size, mid_price)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _simulate_fill(self, bid: Order, ask: Order,
                       symbol: str, size: float, mid: float) -> None:
        """In production this would be driven by exchange WebSocket events."""
        fee_rate = 0.001
        fee = size * mid * fee_rate

        self._pe.record_trade(Trade(strategy=self.name, symbol=symbol,
                                    side="BUY", quantity=size, price=bid.price or mid, fee=fee))
        self._pe.record_trade(Trade(strategy=self.name, symbol=symbol,
                                    side="SELL", quantity=size, price=ask.price or mid, fee=fee))

        spread_income = size * ((ask.price or mid) - (bid.price or mid))
        realized = spread_income - 2 * fee
        self._pe.record_realized_pnl(self.name, realized)

        if realized < 0:
            self._rm.record_loss(self.name, abs(realized))
