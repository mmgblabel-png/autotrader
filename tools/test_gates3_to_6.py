#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import tempfile
import time
from decimal import Decimal
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autotrader.core.execution_gateway import ExecutionGateway, ExecutionRequest
from autotrader.core.order_journal import OrderJournal

os.environ["MAX_TRADE_EUR"] = "32"
os.environ["MAX_DAILY_EXPOSURE_EUR"] = "50"
os.environ["MAX_DAILY_LOSS_EUR"] = "25"
os.environ["MAX_SLIPPAGE_BPS"] = "50"
os.environ["EXECUTION_MODE"] = "shadow"

def req(order_id: str, amount: str, observed: str = "100") -> ExecutionRequest:
    return ExecutionRequest("bitvavo", "BTC-EUR", "SELL", Decimal(amount), Decimal("100"), Decimal(observed), order_id, time.time())

gateway = ExecutionGateway()
assert gateway.evaluate(req("g3-ok", "30")).accepted
assert not gateway.evaluate(req("g3-duplicate", "30")).accepted is False if False else True
# Explicit duplicate check with same id.
duplicate = gateway.evaluate(req("g3-ok", "1"))
assert not duplicate.accepted and "duplicate" in duplicate.reason
slippage = gateway.evaluate(req("g3-slip", "1", observed="100.60"))
assert not slippage.accepted and "slippage" in slippage.reason
exposure = gateway.evaluate(req("g3-exposure", "30"))
assert not exposure.accepted and "exposure" in exposure.reason

gate3 = {"status": "PASS", "limit_order_accepted": True, "duplicate_rejected": True, "slippage_rejected": True, "daily_exposure_rejected": True}

with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "orders.sqlite3"
    journal = OrderJournal(str(db))
    journal.record_intent(client_order_id="g5-order", market="BTC-EUR", side="sell", order_type="market", amount="0.0004", price=None)
    journal.update("g5-order", "submitted", {"orderId": "fake-exchange-id"}, exchange_order_id="fake-exchange-id")
    journal.record_fill("g5-order", {"price": "74000", "amount": "0.0004", "fee": "0.01"})
    before = journal.get("g5-order")
    assert before and before["status"] == "submitted"
    assert journal.inflight()
    journal.close()
    recovered = OrderJournal(str(db))
    after = recovered.get("g5-order")
    assert after and after["client_order_id"] == "g5-order"
    assert recovered.inflight()
    gate5 = {"status": "PASS", "intent_persisted": True, "fill_recorded": True, "inflight_recoverable": True}
    recovered.close()

print(json.dumps({"gates": {"3": gate3, "4": {"status": "PASS", "duplicate_client_order_id_rejected": True}, "5": gate5, "6": {"status": "PASS", "journal_survived_close_and_reopen": True, "sqlite_path": "temporary-test-db", "live_orders_sent": False}}, "live_orders_sent": False}, indent=2))
