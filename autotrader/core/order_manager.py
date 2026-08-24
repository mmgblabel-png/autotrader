"""Order management utilities shared by all strategies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Order:
    exchange: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    fee: float = 0.0
    strategy: str = ""

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.PENDING, OrderStatus.OPEN)


class OrderManager:
    """Tracks all orders across strategies."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def register(self, order: Order) -> Order:
        self._orders[order.order_id] = order
        return order

    def update(self, order_id: str, status: OrderStatus,
               filled_qty: float = 0.0, avg_price: float = 0.0, fee: float = 0.0) -> Optional[Order]:
        o = self._orders.get(order_id)
        if o:
            o.status = status
            o.filled_quantity = filled_qty
            o.avg_fill_price = avg_price
            o.fee = fee
        return o

    def get(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def open_orders(self, strategy: str = "") -> list[Order]:
        return [o for o in self._orders.values()
                if o.is_active and (not strategy or o.strategy == strategy)]

    def all_filled(self, strategy: str = "") -> list[Order]:
        return [o for o in self._orders.values()
                if o.is_filled and (not strategy or o.strategy == strategy)]
