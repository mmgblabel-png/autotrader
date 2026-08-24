"""SniperBot – captures rapid price moves with strict risk limits."""

from __future__ import annotations

from autotrader.core.logger import get_logger
from autotrader.core.order_manager import Order, OrderSide, OrderType
from autotrader.core.profit_engine import Trade
from autotrader.strategies.base import BaseStrategy

log = get_logger("SniperBot")


class SniperBot(BaseStrategy):
    """
    Enters a position when a momentum signal fires; exits at take-profit or stop-loss.

    Config keys (under ``strategies.sniper``):
        symbol            : trading pair, e.g. "BTC/USDT"
        exchange          : exchange name
        order_size        : order quantity (base asset)
        momentum_pct      : minimum % move to trigger entry
        take_profit_pct   : target profit in %
        stop_loss_pct     : maximum loss in %
        max_slippage_pct  : forwarded to RiskManager
        max_daily_loss    : forwarded to RiskManager
    """

    name = "SniperBot"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._position: float = 0.0
        self._entry_price: float = 0.0
        self._prev_price: float = 0.0

    def tick(self) -> None:
        if not self._running or self._rm.is_killed(self.name):
            return

        cfg = self._config
        current_price: float = cfg.get("_current_price", 0.0)
        if current_price <= 0:
            return

        symbol: str = cfg.get("symbol", "BTC/USDT")
        exchange: str = cfg.get("exchange", "binance")
        size: float = cfg.get("order_size", 0.001)
        momentum_pct: float = cfg.get("momentum_pct", 0.5) / 100
        tp_pct: float = cfg.get("take_profit_pct", 1.0) / 100
        sl_pct: float = cfg.get("stop_loss_pct", 0.3) / 100

        if self._position == 0 and self._prev_price > 0:
            move = (current_price - self._prev_price) / self._prev_price
            if abs(move) >= momentum_pct:
                side = OrderSide.BUY if move > 0 else OrderSide.SELL
                notional = size * current_price
                # Estimate slippage vs momentum
                slippage = abs(move) * 0.1
                if not self._rm.check_order(self.name, notional, slippage_pct=slippage * 100):
                    self._prev_price = current_price
                    return

                order = Order(exchange=exchange, symbol=symbol, side=side,
                              order_type=OrderType.MARKET, quantity=size, strategy=self.name)
                self._om.register(order)
                self._position = size if side == OrderSide.BUY else -size
                self._entry_price = current_price
                log.info("SNIPE ENTER %s %s %.4f @ %.2f (move=%.3f%%)",
                         side.value, symbol, size, current_price, move * 100)

        elif self._position != 0:
            entry = self._entry_price
            move_from_entry = (current_price - entry) / entry
            direction = 1 if self._position > 0 else -1
            pnl_pct = move_from_entry * direction

            if pnl_pct >= tp_pct:
                self._close_position(symbol, exchange, current_price, "TAKE-PROFIT")
            elif pnl_pct <= -sl_pct:
                self._close_position(symbol, exchange, current_price, "STOP-LOSS")

        self._prev_price = current_price

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _close_position(self, symbol: str, exchange: str,
                        price: float, reason: str) -> None:
        side = OrderSide.SELL if self._position > 0 else OrderSide.BUY
        size = abs(self._position)
        fee_rate = 0.001
        fee = size * price * fee_rate

        order = Order(exchange=exchange, symbol=symbol, side=side,
                      order_type=OrderType.MARKET, quantity=size, strategy=self.name)
        self._om.register(order)

        pnl = size * (price - self._entry_price) * (1 if self._position > 0 else -1) - fee
        self._pe.record_trade(Trade(strategy=self.name, symbol=symbol,
                                    side=side.value, quantity=size, price=price, fee=fee))
        self._pe.record_realized_pnl(self.name, pnl)

        if pnl < 0:
            self._rm.record_loss(self.name, abs(pnl))

        log.info("SNIPE EXIT (%s) %s %.4f @ %.2f  pnl=%.4f", reason, symbol, size, price, pnl)

        self._position = 0.0
        self._entry_price = 0.0
