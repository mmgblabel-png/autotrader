from pathlib import Path

from autotrader.connectors.bitvavo import BitvavoAdapter
from autotrader.core.bitvavo_security import validate_bitvavo_security
from autotrader.core.order_journal import OrderJournal


def test_journal_persists_order_and_fill(tmp_path: Path):
    path = tmp_path / "orders.sqlite3"
    journal = OrderJournal(str(path))
    journal.record_intent(client_order_id="cid-1", market="BTC-EUR", side="buy", order_type="limit", amount="0.0002", price="50000")
    journal.update("cid-1", "submitted", {"orderId": "oid-1"}, exchange_order_id="oid-1")
    journal.record_fill("cid-1", {"fillId": "fill-1", "amount": "0.0001", "price": "50000", "fee": "0.01"})
    journal.close()
    reopened = OrderJournal(str(path))
    assert reopened.get("cid-1")["status"] == "submitted"
    assert reopened.inflight()[0]["exchange_order_id"] == "oid-1"
    assert len(reopened.fills("cid-1")) == 1
    reopened.close()


def test_reconcile_fetches_status_and_is_repeatable(tmp_path: Path, monkeypatch):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    adapter = BitvavoAdapter(journal=journal)
    journal.record_intent(client_order_id="cid-2", market="BTC-EUR", side="buy", order_type="market", amount="0.0002", price=None)
    journal.update("cid-2", "submitted", {"orderId": "oid-2"}, exchange_order_id="oid-2")
    monkeypatch.setattr(adapter, "get_order", lambda market, **kwargs: {"orderId": "oid-2", "status": "filled", "fills": [{"fillId": "f-2", "amount": "0.0002", "price": "50000"}]})
    adapter.reconcile_order("cid-2", "BTC-EUR")
    adapter.reconcile_order("cid-2", "BTC-EUR")
    assert journal.get("cid-2")["status"] == "filled"
    assert len(journal.fills("cid-2")) == 1
    journal.close()


def test_duplicate_intent_does_not_overwrite_status(tmp_path: Path):
    journal = OrderJournal(str(tmp_path / "orders.sqlite3"))
    assert journal.record_intent(client_order_id="cid-duplicate", market="BTC-EUR", side="buy", order_type="market", amount="0.0001", price=None)
    journal.update("cid-duplicate", "submitted", {"orderId": "oid"}, exchange_order_id="oid")
    assert not journal.record_intent(client_order_id="cid-duplicate", market="BTC-EUR", side="buy", order_type="market", amount="0.0001", price=None)
    assert journal.get("cid-duplicate")["status"] == "submitted"
    journal.close()


def test_security_check_fails_closed_without_operator_confirmations(monkeypatch):
    monkeypatch.delenv("BITVAVO_API_KEY", raising=False)
    monkeypatch.delenv("BITVAVO_API_SECRET", raising=False)
    monkeypatch.delenv("BITVAVO_WITHDRAWALS_DISABLED", raising=False)
    monkeypatch.delenv("BITVAVO_IP_WHITELIST_CONFIRMED", raising=False)
    adapter = BitvavoAdapter(journal=OrderJournal(":memory:"))
    report = validate_bitvavo_security(adapter)
    assert report["passed"] is False
    assert report["credentials_present"] is False
    adapter.journal.close()
