from fastapi.testclient import TestClient

from autotrader.api.bitvavo_setup import app
from autotrader.connectors.bitvavo import BitvavoError


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


def test_invalid_credentials_are_classified_without_echoing_secret(monkeypatch):
    class FakeAdapter:
        def __init__(self, **kwargs):
            pass

        def balance(self, symbol=None):
            raise BitvavoError("private request rejected", category="invalid_credentials", status=401)

    monkeypatch.setattr("autotrader.api.bitvavo_setup.BitvavoAdapter", FakeAdapter)
    secret = "secret-value"
    response = TestClient(app).post(
        "/api/validate",
        json={"api_key": "key-value", "api_secret": secret, "symbol": "EUR"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"
    assert secret not in response.text


def test_network_errors_are_safe_and_categorized(monkeypatch):
    class FakeAdapter:
        def __init__(self, **kwargs):
            pass

        def balance(self, symbol=None):
            raise BitvavoError("network failed", category="network_error")

    monkeypatch.setattr("autotrader.api.bitvavo_setup.BitvavoAdapter", FakeAdapter)
    response = TestClient(app).post(
        "/api/validate",
        json={"api_key": "key-value", "api_secret": "secret-value"},
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "network_error"
