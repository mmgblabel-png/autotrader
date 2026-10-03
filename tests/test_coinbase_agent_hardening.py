from decimal import Decimal

import pytest

from autotrader.connectors.coinbase_advanced import CoinbaseAdvancedMarketData, CoinbaseTopOfBook, CoinbaseTradingError
from autotrader.core.coinbase_autonomous_executor import CoinbaseAutonomousConfig, CoinbaseAutonomousExecutor


class HardeningFakeCoinbase:
    def __init__(self):
        self.eur = 0.0
        self.btc = 0.00030103
        self.bid = 75350.0
        self.ask = 75360.0
        self.created = []
        self.orders = {}
        self.last_portfolio_id = None
        self.raise_after_accept_once = False

    def authenticated_accounts_probe(self, portfolio_id=None):
        self.last_portfolio_id = portfolio_id
        return {"authenticated": True, "format_compatible": True, "status": 200, "error_category": None}

    def account_balances(self, portfolio_id=None):
        self.last_portfolio_id = portfolio_id
        rows = []
        if self.eur > 0:
            rows.append({"currency": "EUR", "available": str(self.eur), "hold": "0", "total": str(self.eur)})
        if self.btc > 0:
            rows.append({"currency": "BTC", "available": str(self.btc), "hold": "0", "total": str(self.btc)})
        return {"authenticated": True, "assets": rows}

    def top_of_book(self, product_id):
        return CoinbaseTopOfBook(product_id=product_id, bid_price=Decimal(str(self.bid)), bid_size=Decimal("1"), ask_price=Decimal(str(self.ask)), ask_size=Decimal("1"))

    def preview_spot_market_order(self, *, product_id, side, quote_size=None, base_size=None, portfolio_id=None, **kwargs):
        self.last_portfolio_id = portfolio_id
        reference = self.ask if side == "BUY" else self.bid
        notional = float(quote_size) if quote_size else float(base_size) * reference
        return {"preview_id": "preview-hardening", "commission_total": str(notional * 0.005), "est_average_filled_price": str(reference)}

    def create_spot_market_order(self, *, client_order_id, product_id, side, quote_size=None, base_size=None, portfolio_id=None, preview_id=None, **kwargs):
        self.last_portfolio_id = portfolio_id
        order_id = f"order-{len(self.created) + 1}"
        row = {"order_id": order_id, "client_order_id": client_order_id, "product_id": product_id, "side": side, "quote_size": quote_size, "base_size": base_size, "portfolio_id": portfolio_id, "preview_id": preview_id}
        self.created.append(row)
        if side == "SELL":
            size, price = float(base_size), self.bid
        else:
            price = self.ask
            size = float(quote_size) / price
        self.orders[order_id] = {"order_id": order_id, "client_order_id": client_order_id, "status": "FILLED", "filled_size": str(size), "average_filled_price": str(price), "total_fees": str(size * price * 0.005), "settled": True}
        if self.raise_after_accept_once:
            self.raise_after_accept_once = False
            raise CoinbaseTradingError("simulated uncertain outcome", category="network_error")
        return {"success": True, "success_response": {"order_id": order_id}}

    def find_order_by_client_id(self, client_order_id, *, product_id=None, portfolio_id=None):
        self.last_portfolio_id = portfolio_id
        return next((dict(row) for row in self.orders.values() if row.get("client_order_id") == client_order_id), None)

    def get_order(self, order_id):
        return dict(self.orders[order_id])


def _live(monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("LIVE_EXECUTION_APPROVED", "true")
    monkeypatch.setenv("COINBASE_EXECUTION_ADAPTER_INSTALLED", "true")
    monkeypatch.setenv("COINBASE_LIVE_TRADING", "true")
    monkeypatch.setenv("EMERGENCY_STOP", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDERS")


def test_portfolio_scope_reaches_balance_preview_and_order(tmp_path, monkeypatch):
    _live(monkeypatch)
    fake = HardeningFakeCoinbase()
    executor = CoinbaseAutonomousExecutor(CoinbaseAutonomousConfig(state_path=str(tmp_path / "state.json"), require_shadow_promotion=False, portfolio_id="agent-portfolio", allow_existing_btc_seed=True, max_order_eur=2.0), client=fake)
    status = executor.tick(armed=True, shadow_status={"promotion_ready": True, "last_signal": {"decisions": []}})
    assert status["portfolio_id"] == "agent-portfolio"
    assert status["portfolio_isolated"] is True
    assert fake.last_portfolio_id == "agent-portfolio"
    assert fake.created[0]["portfolio_id"] == "agent-portfolio"


def test_uncertain_submit_is_reconciled_without_second_order(tmp_path, monkeypatch):
    _live(monkeypatch)
    fake = HardeningFakeCoinbase()
    fake.raise_after_accept_once = True
    executor = CoinbaseAutonomousExecutor(CoinbaseAutonomousConfig(state_path=str(tmp_path / "state.json"), require_shadow_promotion=False, require_isolated_portfolio=False, allow_existing_btc_seed=True, max_order_eur=2.0), client=fake)
    with pytest.raises(CoinbaseTradingError, match="uncertain"):
        executor.tick(armed=True, shadow_status={"promotion_ready": True, "last_signal": {"decisions": []}})
    assert len(fake.created) == 1
    assert executor.state.submission_intent is not None
    client_id = executor.state.submission_intent.client_order_id
    status = executor.tick(armed=True, shadow_status={"promotion_ready": True, "last_signal": {"decisions": []}})
    assert len(fake.created) == 1
    assert executor.state.submission_intent is None
    assert status["live_orders_sent"] == 1
    assert fake.created[0]["client_order_id"] == client_id


def test_spot_buy_payload_supports_exchange_native_attached_exits():
    payload = CoinbaseAdvancedMarketData._spot_market_payload(product_id="btc/eur", side="BUY", quote_size="2.00", portfolio_id="agent-portfolio", attached_take_profit_price="77000", attached_stop_loss_price="74000")
    assert payload["product_id"] == "BTC-EUR"
    assert payload["retail_portfolio_id"] == "agent-portfolio"
    assert payload["attached_order_configuration"]["trigger_bracket_gtc"] == {"limit_price": "77000", "stop_trigger_price": "74000"}


def test_spot_sell_parent_rejects_attached_exit_configuration():
    with pytest.raises(ValueError, match="SPOT BUY"):
        CoinbaseAdvancedMarketData._spot_market_payload(product_id="BTC-EUR", side="SELL", base_size="0.00002", attached_stop_loss_price="74000")


def test_account_balance_query_can_be_portfolio_scoped(monkeypatch):
    client = CoinbaseAdvancedMarketData()
    observed = {}
    def fake_get(path, params=None):
        observed["path"], observed["params"] = path, params
        return {"accounts": [{"currency": "BTC", "active": True, "available_balance": {"value": "0.001"}, "hold": {"value": "0"}}]}
    monkeypatch.setattr(client, "_auth_get", fake_get)
    result = client.account_balances("portfolio-1")
    assert observed["params"]["retail_portfolio_id"] == "portfolio-1"
    assert result["portfolio_scoped"] is True
    assert result["portfolio_id"] == "portfolio-1"
