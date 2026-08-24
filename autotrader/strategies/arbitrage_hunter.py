"""ArbitrageHunter – detects and exploits price discrepancies across exchanges."""

from __future__ import annotations

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.core.profit_engine import Trade
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
        # Exchange prices are injected via config["_prices"] = {"binance": 1900.0, "kraken": 1905.0}
        prices: dict[str, float] = cfg.get("_prices", {})

        if len(prices) < 2:
            log.debug("Not enough price feeds (%d) – skipping.", len(prices))
            return

        sorted_prices = sorted(prices.items(), key=lambda x: x[1])
        buy_exchange, buy_price = sorted_prices[0]
        sell_exchange, sell_price = sorted_prices[-1]

        spread_pct = (sell_price - buy_price) / buy_price
        if spread_pct < min_profit:
            log.debug("Spread %.4f%% below threshold %.4f%% – no trade.", spread_pct * 100, min_profit * 100)
            return

        notional = size * buy_price
        if not self._rm.check_order(self.name, notional):
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

        fee_rate = 0.001
        fee = size * buy_price * fee_rate + size * sell_price * fee_rate
        gross = size * (sell_price - buy_price)
        net = gross - fee

        self._pe.record_trade(Trade(strategy=self.name, symbol=symbol,
                                    side="BUY", quantity=size, price=buy_price, fee=fee / 2))
        self._pe.record_trade(Trade(strategy=self.name, symbol=symbol,
                                    side="SELL", quantity=size, price=sell_price, fee=fee / 2))
        self._pe.record_realized_pnl(self.name, net)

        if net < 0:
            self._rm.record_loss(self.name, abs(net))

        log.info("ARB result: gross=%.4f fee=%.4f net=%.4f", gross, fee, net)
