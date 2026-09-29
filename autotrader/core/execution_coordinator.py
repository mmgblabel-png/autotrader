"""Execution coordinator: turns strategy intents into exchange orders only in live mode."""
from __future__ import annotations
import logging
from decimal import Decimal
from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError
from autotrader.core.order_manager import Order, OrderManager, OrderSide, OrderStatus, OrderType
from autotrader.core.profit_engine import ProfitEngine, Trade
from autotrader.core.strategy_allocator import StrategyAllocator

log = logging.getLogger(__name__)


class ExecutionCoordinator:
    def __init__(self, order_manager: OrderManager, adapter: BitvavoAdapter | None = None, *, is_armed=None, profit_engine: ProfitEngine | None = None, risk_manager=None, allocator: StrategyAllocator | None = None, fill_handler=None) -> None:
        self.om = order_manager
        self.adapter = adapter or BitvavoAdapter()
        self.is_armed = is_armed or (lambda: False)
        self.profit_engine = profit_engine
        self.risk_manager = risk_manager
        self.allocator = allocator
        self.fill_handler = fill_handler
        self._recorded_fill_keys: set[str] = set()

    @staticmethod
    def _mapped_status(status: str) -> OrderStatus:
        value = status.lower()
        if value == "filled":
            return OrderStatus.FILLED
        if value in {"canceled", "cancelled", "expired"}:
            return OrderStatus.CANCELLED
        if value in {"rejected", "error"}:
            return OrderStatus.FAILED
        return OrderStatus.OPEN

    @staticmethod
    def _fill_price(payload: dict, fallback: float = 0.0) -> float:
        fills = [f for f in (payload.get("fills") or []) if isinstance(f, dict)]
        total_qty = sum(float(f.get("amount") or 0) for f in fills)
        if total_qty > 0:
            total_quote = sum(float(f.get("amount") or 0) * float(f.get("price") or 0) for f in fills)
            return total_quote / total_qty
        return float(payload.get("averagePrice") or payload.get("price") or fallback or 0)

    def _record_fills(self, order: Order, payload: dict) -> None:
        for fill in payload.get("fills") or []:
            if not isinstance(fill, dict):
                continue
            fill_id = str(fill.get("id") or fill.get("fillId") or "")
            key = f"{order.order_id}:{fill_id or repr(sorted(fill.items()))}"
            if key in self._recorded_fill_keys:
                continue
            quantity = float(fill.get("amount") or 0)
            price = float(fill.get("price") or 0)
            if quantity <= 0 or price <= 0:
                continue
            raw_ts = float(fill.get("timestamp") or 0)
            timestamp = raw_ts / 1000.0 if raw_ts > 10_000_000_000 else (raw_ts or __import__("time").time())
            if self.profit_engine is not None:
                realized = self.profit_engine.record_trade(
                    Trade(
                        strategy=order.strategy or "MarketMaker",
                        symbol=order.symbol,
                        side=order.side.value,
                        quantity=quantity,
                        price=price,
                        fee=float(fill.get("fee") or 0),
                        fee_currency=str(fill.get("feeCurrency") or ""),
                        fill_key=key,
                        timestamp=timestamp,
                    )
                )
                if realized < 0:
                    loss = -realized
                    if self.risk_manager is not None:
                        self.risk_manager.record_loss(order.strategy or "MarketMaker", loss)
                    gateway = getattr(self.adapter, "gateway", None)
                    if order.symbol.upper().endswith("-EUR") and gateway is not None:
                        gateway.record_loss(Decimal(str(loss)))
            if self.fill_handler is not None:
                self.fill_handler(order, fill)
            self._recorded_fill_keys.add(key)

    def _restore_order(self, client_order_id: str) -> Order | None:
        record = self.adapter.journal.get(client_order_id)
        if not record:
            return None
        try:
            side = OrderSide.BUY if str(record.get("side", "")).upper() == "BUY" else OrderSide.SELL
            order_type = OrderType.LIMIT if str(record.get("order_type", "")).lower() == "limit" else OrderType.MARKET
            order = Order(
                exchange="bitvavo",
                symbol=str(record["market"]),
                side=side,
                order_type=order_type,
                quantity=float(record["amount"]),
                price=float(record["price"]) if record.get("price") not in {None, ""} else None,
                order_id=client_order_id,
                status=OrderStatus.OPEN,
                strategy=str(record.get("strategy") or "MarketMaker"),
            )
            return self.om.register(order)
        except (KeyError, TypeError, ValueError):
            return None

    def submit_pending(self) -> list[dict]:
        if not self.is_armed():
            return []
        results = []
        for order in list(self.om.open_orders()):
            if order.status is not OrderStatus.PENDING:
                continue
            try:
                if order.exchange.strip().lower() != "bitvavo":
                    self.om.update(order.order_id, OrderStatus.FAILED)
                    log.error("Order %s blocked: no live adapter for exchange %s", order.order_id, order.exchange)
                    results.append({"client_order_id": order.order_id, "status": "failed", "category": "unsupported_exchange"})
                    continue

                observed_price = Decimal(str(order.price)) if order.price is not None else self.adapter.ticker_price(order.symbol)
                if self.allocator is not None:
                    allocation = self.allocator.evaluate(
                        order,
                        self.om.open_orders(),
                        observed_price=observed_price,
                    )
                    if not allocation.accepted:
                        self.om.update(order.order_id, OrderStatus.FAILED)
                        log.warning("Order %s blocked by allocation guard: %s", order.order_id, allocation.reason)
                        results.append({"client_order_id": order.order_id, "status": "failed", "category": "allocation", "reason": allocation.reason})
                        continue

                if order.order_type is OrderType.LIMIT:
                    response = self.adapter.place_limit_order(
                        order.symbol,
                        order.side.value.lower(),
                        __import__("decimal").Decimal(str(order.quantity)),
                        __import__("decimal").Decimal(str(order.price)),
                        order.order_id,
                    )
                else:
                    response = self.adapter.place_market_order(
                        order.symbol,
                        order.side.value.lower(),
                        __import__("decimal").Decimal(str(order.quantity)),
                        order.order_id,
                    )
                self.adapter.journal.set_strategy(order.order_id, order.strategy)
                status = str(response.get("status", "new"))
                mapped = self._mapped_status(status)
                filled = float(response.get("filledAmount") or response.get("amountFilled") or 0)
                avg_price = self._fill_price(response, order.price or 0)
                fee = float(response.get("feePaid") or response.get("fee") or 0)
                self.om.update(order.order_id, mapped, filled, avg_price, fee)
                self._record_fills(order, response)
                results.append({"client_order_id": order.order_id, "status": status.lower()})
            except BitvavoError as exc:
                self.om.update(order.order_id, OrderStatus.FAILED)
                log.error("Bitvavo order %s failed: %s", order.order_id, exc)
                results.append({"client_order_id": order.order_id, "status": "failed", "category": exc.category})
        return results

    def reconcile(self) -> list[dict]:
        results = []
        for record in self.adapter.reconcile_inflight():
            cid = str(record.get("clientOrderId") or record.get("client_order_id") or "")
            status = str(record.get("status", "unknown"))
            order = self.om.get(cid) if cid else None
            if cid and order is None:
                order = self._restore_order(cid)
            if cid and order is not None:
                mapped = self._mapped_status(status)
                filled = float(record.get("filledAmount") or record.get("amountFilled") or 0)
                price = self._fill_price(record, order.avg_fill_price or order.price or 0)
                fee = float(record.get("feePaid") or record.get("fee") or 0)
                self.om.update(cid, mapped, filled, price, fee)
                self._record_fills(order, record)
            results.append(record)
        return results
