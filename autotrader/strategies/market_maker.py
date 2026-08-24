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
        mid_price: float = cfg.get("_mid_price", 30_000.0)   # injected by connector
        spread_pct: float = cfg.get("target_spread", 0.2) / 100
        size: float = cfg.get("order_size", 0.001)

        # Clamp size
        size = max(cfg.get("min_order_size", 0.0001), min(size, cfg.get("max_order_size", 1.0)))

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
