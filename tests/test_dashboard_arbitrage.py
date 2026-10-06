from autotrader.api.dashboard_html import dashboard_html


def test_dashboard_shows_complete_bitvavo_control_room_only():
    html = dashboard_html()
    lower = html.lower()

    assert "AutoTrader · Bitvavo" in html
    assert "Bitvavo Live Trading" in html
    assert "Bitvavo Account & API" in html
    assert "Bitvavo Connectivity & Safety" in html
    assert "Bitvavo Opportunity Router" in html
    assert "Bitvavo Market Universe" in html
    assert "Alle Bitvavo Spot Markets" in html
    assert "Bitvavo Scanner Health" in html
    assert "Order Control Center" in html
    assert "Fee & Margin Reality" in html
    assert "Shadow Fast Lane" in html
    assert "section('bitvavo_security')" in html
    assert "section('bitvavo_live_state')" in html
    assert "section('opportunities')" in html
    assert "section('universe_summary')" in html
    assert "section('live_readiness')" in html

    assert "coinbase" not in lower
    assert "binance" not in lower
    assert "section('arbitrage')" not in html
