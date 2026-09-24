from fastapi.testclient import TestClient

from autotrader.api.bitvavo_setup import app


def test_validation_api_discards_credentials_and_returns_shadow(monkeypatch):
    class FakeAdapter:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "key-value"
            assert kwargs["api_secret"] == "secret-value"

        def balance(self, symbol=None):
            assert symbol == "EUR"
            return [{"symbol": "EUR", "available": "100.00", "inOrder": "0"}]

    monkeypatch.setattr("autotrader.api.bitvavo_setup.BitvavoAdapter", FakeAdapter)
    client = TestClient(app)
    response = client.post("/api/validate", json={"api_key": "key-value", "api_secret": "secret-value", "symbol": "EUR"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "shadow"
    assert body["real_order_sent"] is False
    assert "secret-value" not in response.text
