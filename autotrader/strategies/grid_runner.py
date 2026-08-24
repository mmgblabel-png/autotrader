"""GridRunner – grid trading strategy for range-bound or trending assets."""

from __future__ import annotations

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.core.profit_engine import Trade
from autotrader.strategies.base import BaseStrategy

log = get_logger("GridRunner")


class GridRunner(BaseStrategy):
    """
    Places a ladder of limit orders above and below the current price.

    Config keys (under ``strategies.grid``):
        symbol          : trading pair, e.g. "SOL/USDT"
        exchange        : exchange name
        upper_price     : top of the grid
        lower_price     : bottom of the grid
        grid_levels     : number of grid lines
        order_size      : quantity per grid level
        max_daily_loss  : forwarded to RiskManager
    """

    name = "GridRunner"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._grid_prices: list[float] = []
        self._initialized = False

    def on_start(self) -> None:
        self._build_grid()

    def tick(self) -> None:
        if not self._running or self._rm.is_killed(self.name):
            return

        if not self._initialized:
            self._build_grid()

        cfg = self._config
        current_price: float = cfg.get("_current_price", 0.0)
        if current_price <= 0:
            return

        symbol: str = cfg.get("symbol", "SOL/USDT")
        exchange: str = cfg.get("exchange", "binance")
        size: float = cfg.get("order_size", 1.0)

        # For each grid level, place a buy below and a sell above current price
        for level_price in self._grid_prices:
            notional = size * level_price
            if not self._rm.check_order(self.name, notional):
                continue

            if level_price < current_price:
                order = Order(exchange=exchange, symbol=symbol, side=OrderSide.BUY,
                              order_type=OrderType.LIMIT, quantity=size, price=level_price,
                              strategy=self.name)
            else:
                order = Order(exchange=exchange, symbol=symbol, side=OrderSide.SELL,
                              order_type=OrderType.LIMIT, quantity=size, price=level_price,
                              strategy=self.name)

            self._om.register(order)
            log.debug("GRID %s %s %.2f qty=%.4f", order.side.value, symbol, level_price, size)

        # Record a simulated PnL update
        self._pe.update_unrealized_pnl(self.name, self._estimate_unrealized(current_price))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_grid(self) -> None:
        cfg = self._config
        upper: float = cfg.get("upper_price", 110.0)
        lower: float = cfg.get("lower_price", 90.0)
        levels: int = max(2, cfg.get("grid_levels", 10))

        step = (upper - lower) / (levels - 1)
        self._grid_prices = [round(lower + i * step, 4) for i in range(levels)]
        self._initialized = True
        log.info("Grid built: %d levels from %.2f to %.2f (step=%.4f)",
                 levels, lower, upper, step)

    def _estimate_unrealized(self, current_price: float) -> float:
        """Rough unrealized PnL based on open grid orders."""
        open_orders = self._om.open_orders(self.name)
        unrealized = 0.0
        for o in open_orders:
            if o.price and o.side == OrderSide.BUY:
                unrealized += o.quantity * (current_price - o.price)
        return unrealized
