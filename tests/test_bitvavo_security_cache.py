import time

from autotrader.api import server


def test_bitvavo_security_probe_is_cached(monkeypatch):
    calls = {"n": 0}

    def fake_validate(adapter):
        calls["n"] += 1
        return {"passed": True, "authenticated_probe": True, "errors": []}

    monkeypatch.setattr(server, "validate_bitvavo_security", fake_validate)
    monkeypatch.setattr(server, "get_agent", lambda: type("Agent", (), {"_bitvavo": object()})())
    monkeypatch.setenv("BITVAVO_SECURITY_CACHE_SECONDS", "60")
    server.app.state.bitvavo_security_cache = None
    server.app.state.bitvavo_security_cache_at = 0.0

    first = server._cached_bitvavo_security()
    second = server._cached_bitvavo_security()

    assert first["passed"] is True
    assert second["passed"] is True
    assert calls["n"] == 1


def test_bitvavo_security_probe_refreshes_after_ttl(monkeypatch):
    calls = {"n": 0}

    def fake_validate(adapter):
        calls["n"] += 1
        return {"passed": calls["n"] > 1, "authenticated_probe": calls["n"] > 1, "errors": []}

    monkeypatch.setattr(server, "validate_bitvavo_security", fake_validate)
    monkeypatch.setattr(server, "get_agent", lambda: type("Agent", (), {"_bitvavo": object()})())
    monkeypatch.setenv("BITVAVO_SECURITY_CACHE_SECONDS", "15")
    server.app.state.bitvavo_security_cache = {"passed": False, "authenticated_probe": False, "errors": ["rate_limited"]}
    server.app.state.bitvavo_security_cache_at = time.monotonic() - 16

    report = server._cached_bitvavo_security()

    assert report["passed"] is False
    assert calls["n"] == 1


def test_running_bitvavo_markets_are_unique_and_filtered():
    class Strategy:
        def __init__(self, running, exchange, symbol):
            self.is_running = running
            self._config = {"exchange": exchange, "symbol": symbol}

    agent = type(
        "Agent",
        (),
        {
            "_strategies": {
                "a": Strategy(True, "bitvavo", "BTC-EUR"),
                "b": Strategy(True, "bitvavo", "SOL-EUR"),
                "c": Strategy(True, "bitvavo", "BTC-EUR"),
                "d": Strategy(False, "bitvavo", "XRP-EUR"),
                "e": Strategy(True, "coinbase", "ETH-EUR"),
            }
        },
    )()

    assert server._running_bitvavo_markets(agent) == ["BTC-EUR", "SOL-EUR"]
