"""ArbitrageHunter – detects and exploits price discrepancies across exchanges."""

from __future__ import annotations

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.strategies.base import BaseStrategy

log = get_logger("ArbitrageHunter")


class ArbitrageHunter(BaseStrategy):
    """
    Simple cross-exchange arbitrage.

    Watches the same symbol on 2–3 exchanges; when the spread exceeds
    ``min_profit_pct``, it fires simultaneous buy (cheap leg) and sell
    (expensive leg) orders.

    Config keys (under ``strategies.arbitrage``):
        symbol          : trading pair, e.g. "ETH/USDT"
        exchanges       : list of exchange names
        order_size      : order quantity (base asset)
        min_profit_pct  : minimum net profit in % to trigger trade
        max_order_size  : upper bound on order quantity
        max_daily_loss  : forwarded to RiskManager
    """

    name = "ArbitrageHunter"

    def tick(self) -> None:
        if not self._running or self._rm.is_killed(self.name):
            return

        cfg = self._config
        symbol: str = cfg.get("symbol", "ETH/USDT")
        size: float = cfg.get("order_size", 0.01)
        min_profit: float = cfg.get("min_profit_pct", 0.15) / 100
        fee_pct = cfg.get("estimated_fee_pct", 0.25) / 100
        slippage_pct = cfg.get("estimated_slippage_pct", 0.10) / 100
        min_edge = cfg.get("min_edge_after_costs_pct", 0.10) / 100
        # Exchange prices are injected via config["_prices"] = {"binance": 1900.0, "kraken": 1905.0}
        prices: dict[str, float] = cfg.get("_prices", {})

        if len(prices) < 2:
            log.debug("Not enough price feeds (%d) – skipping.", len(prices))
            return

        sorted_prices = sorted(prices.items(), key=lambda x: x[1])
        buy_exchange, buy_price = sorted_prices[0]
        sell_exchange, sell_price = sorted_prices[-1]

        spread_pct = (sell_price - buy_price) / buy_price
        required_edge = min_profit + (2 * fee_pct) + (2 * slippage_pct) + min_edge
        if spread_pct < required_edge:
            log.debug("Spread %.4f%% below threshold %.4f%% – no trade.", spread_pct * 100, min_profit * 100)
            return

        notional = size * buy_price
        if not self._rm.check_order(self.name, notional, symbol=symbol):
            return

        # Buy on cheap exchange
        buy_order = Order(exchange=buy_exchange, symbol=symbol, side=OrderSide.BUY,
                          order_type=OrderType.MARKET, quantity=size, strategy=self.name)
        self._om.register(buy_order)
        log.info("ARB BUY  %s %.4f @ %.2f on %s", symbol, size, buy_price, buy_exchange)

        # Sell on expensive exchange
        sell_order = Order(exchange=sell_exchange, symbol=symbol, side=OrderSide.SELL,
                           order_type=OrderType.MARKET, quantity=size, strategy=self.name)
        self._om.register(sell_order)
        log.info("ARB SELL %s %.4f @ %.2f on %s", symbol, size, sell_price, sell_exchange)

        # PnL is deliberately not synthesized here. It must be produced from
        # actual/paper fill events after both legs have executed.
        log.info("ARB signal emitted; awaiting execution/fill events.")
