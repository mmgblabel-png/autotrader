import csv
import json

from autotrader.core.paper_reporting import build_paper_report, export_paper_report


def test_build_paper_report(monkeypatch):
    monkeypatch.setenv('PAPER_STARTING_BALANCE_USD', '1000')
    monkeypatch.setenv('USD_EUR_RATE', '0.92')
    monkeypatch.setenv('BTC_USD_PRICE', '50000')
    report = build_paper_report({'total_pnl': 25.0, 'trade_count': 2})
    assert report['mode'] == 'paper'
    assert report['account']['pnl_pct'] == 2.5
    assert report['account']['drawdown_pct'] == 0.0
    assert report['pnl']['eur'] == 23.0
    assert report['pnl']['btc'] == 0.0005


def test_export_paper_report(tmp_path):
    report = build_paper_report({'total_pnl': -10.0})
    json_path, csv_path = export_paper_report(report, str(tmp_path))
    payload = json.loads(open(json_path, encoding='utf-8').read())
    assert payload['account']['pnl_pct'] == -1.0
    with open(csv_path, newline='', encoding='utf-8') as handle:
        row = next(csv.DictReader(handle))
    assert row['mode'] == 'paper'
    assert row['drawdown_pct'] == '1.0'
