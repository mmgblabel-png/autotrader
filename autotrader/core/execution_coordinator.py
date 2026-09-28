"""Execution coordinator: turns strategy intents into exchange orders only in live mode."""
from __future__ import annotations
import logging
from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError
from autotrader.core.order_manager import OrderManager, OrderStatus, OrderType
log=logging.getLogger(__name__)

class ExecutionCoordinator:
    def __init__(self, order_manager:OrderManager, adapter:BitvavoAdapter|None=None)->None:
        self.om=order_manager
        self.adapter=adapter or BitvavoAdapter()

    def submit_pending(self)->list[dict]:
        results=[]
        for order in list(self.om.open_orders()):
            if order.status is not OrderStatus.PENDING: continue
            try:
                if order.order_type is OrderType.LIMIT:
                    response=self.adapter.place_limit_order(order.symbol,order.side.value.lower(),__import__("decimal").Decimal(str(order.quantity)),__import__("decimal").Decimal(str(order.price)),order.order_id)
                else:
                    response=self.adapter.place_market_order(order.symbol,order.side.value.lower(),__import__("decimal").Decimal(str(order.quantity)),order.order_id)
                status=str(response.get("status","open")).lower()
                mapped=OrderStatus.FILLED if status=="filled" else OrderStatus.OPEN
                self.om.update(order.order_id,mapped,float(response.get("filledAmount") or response.get("amountFilled") or 0),float(response.get("price") or response.get("averagePrice") or order.price or 0),float(response.get("fee") or 0))
                results.append({"client_order_id":order.order_id,"status":status})
            except BitvavoError as exc:
                self.om.update(order.order_id,OrderStatus.FAILED)
                log.error("Bitvavo order %s failed: %s",order.order_id,exc)
                results.append({"client_order_id":order.order_id,"status":"failed","category":exc.category})
        return results

    def reconcile(self)->list[dict]:
        results=[]
        for record in self.adapter.reconcile_inflight():
            cid=str(record.get("clientOrderId") or record.get("client_order_id") or "")
            status=str(record.get("status","unknown")).lower()
            if cid and (order:=self.om.get(cid)):
                mapped={"filled":OrderStatus.FILLED,"canceled":OrderStatus.CANCELLED,"cancelled":OrderStatus.CANCELLED,"expired":OrderStatus.CANCELLED}.get(status,OrderStatus.OPEN)
                filled=float(record.get("filledAmount") or record.get("amountFilled") or 0)
                price=float(record.get("averagePrice") or record.get("price") or order.avg_fill_price or order.price or 0)
                self.om.update(cid,mapped,filled,price,float(record.get("fee") or 0))
            results.append(record)
        return results
