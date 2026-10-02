"""Dashboard coverage for the Fund Core command center."""

from autotrader.api.dashboard_html import dashboard_html


def test_dashboard_exposes_fund_core_command_center():
    html = dashboard_html()

    assert "Hedge Fund Command Center" in html
    assert "Fund Core · €25.000 Protected Capital" in html
    assert 'id="fundnav"' in html
    assert 'id="fundprogressbar"' in html
    assert 'id="fundfloor"' in html
    assert 'id="fundriskcapital"' in html
    assert 'id="fundnavverified"' in html
    assert 'id="fundstage"' in html
    assert 'id="fundnext"' in html
    assert 'id="fundtrack"' in html
    assert 'id="fundroles"' in html
    assert 'id="fundledger"' in html
    assert "AI Hedge Fund Prototype" in html
    assert 'id="prototypeAgents"' in html
    assert 'id="prototypeCoverage"' in html
    assert 'id="prototypeFills"' in html
    assert 'id="prototypePnl"' in html
    assert 'id="prototypeCompliance"' in html
    assert 'id="prototypeInvestor"' in html
    assert 'id="prototypeAgentRows"' in html
    assert "function renderFund(d)" in html
    assert "section('fund')" in html
    assert "renderFund(fund.value)" in html


def test_dashboard_explains_target_does_not_raise_risk():
    html = dashboard_html()
    assert "het target verhoogt nooit automatisch het risico" in html
    assert "Nieuwe risicoverhogende orders geblokkeerd" in html
    assert "Live NAV is niet geverifieerd of te oud" in html
    assert "€50.000" in html
    assert "TRACK RECORD" in html
