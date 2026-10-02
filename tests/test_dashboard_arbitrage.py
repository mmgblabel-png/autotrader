from autotrader.api.dashboard_html import dashboard_html


def test_dashboard_shows_coinbase_arbitrage_shadow_status():
    html = dashboard_html()
    assert "Coinbase Advanced" in html
    assert "Coinbase ↔ Bitvavo arbitrage" in html
    assert "section('coinbase_security')" in html
    assert "section('arbitrage')" in html
    assert "shadow actief" in html
    assert "live orders verzonden" in html
