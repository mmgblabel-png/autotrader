from types import SimpleNamespace

from autotrader.api import server


class _FakeClient:
    def __init__(self):
        self.calls = []

    def preview_spot_market_order(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "preview_id": "preview-1",
            "commission_total": "0.006",
            "est_average_filled_price": "76000",
        }


class _FakeExecutor:
    def __init__(self):
        self.client = _FakeClient()
        self.config = SimpleNamespace(
            product_id="BTC-EUR",
            portfolio_id="agent-portfolio",
            min_order_eur=1.0,
            max_order_eur=5.0,
            allow_existing_btc_seed=False,
        )

    def readiness(self, *, armed, shadow_status):
        assert armed is True
        return {
            "ready_for_new_entry": False,
            "failed_gates": ["shadow_promotion_ready"],
            "balances": {"EUR": 6.0, "BTC": 0.0},
            "best_bid": 76000.0,
            "best_ask": 76010.0,
        }


class _FakeShadow:
    def status(self):
        return {"promotion_ready": False}


class _FakeArmStore:
    def status(self):
        return {"armed": False}


def test_coinbase_readiness_uses_buy_preview_for_cash_only_portfolio(monkeypatch):
    executor = _FakeExecutor()
    monkeypatch.setattr(server.app.state, "coinbase_autonomous_executor", executor, raising=False)
    monkeypatch.setattr(server.app.state, "coinbase_autonomous_enabled", True, raising=False)
    monkeypatch.setattr(server.app.state, "coinbase_zscore_shadow", _FakeShadow(), raising=False)
    monkeypatch.setattr(server.app.state, "coinbase_live_armed", False, raising=False)
    monkeypatch.setattr(server.app.state, "coinbase_live_arm_store", _FakeArmStore(), raising=False)

    payload = server.coinbase_live_readiness()

    assert payload["trade_permission_preview"]["passed"] is True
    assert payload["trade_permission_preview"]["side"] == "BUY"
    assert payload["ready_to_arm"] is True
    assert executor.client.calls == [{
        "product_id": "BTC-EUR",
        "side": "BUY",
        "quote_size": "2.00",
        "portfolio_id": "agent-portfolio",
    }]
