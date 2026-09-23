import os

from autotrader.api.auth import issue_jwt, valid_credential
from autotrader.core.notifications import notify_paper_report


def test_api_key_and_jwt(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_KEY", "test-api-key")
    monkeypatch.setenv("PUBLIC_JWT_SECRET", "test-jwt-secret")
    assert valid_credential("test-api-key")
    assert not valid_credential("wrong")
    token = issue_jwt(ttl_seconds=60)
    assert valid_credential(token)


def test_notifications_are_disabled_by_default(monkeypatch):
    for key in (
        "PAPER_NOTIFY_TELEGRAM_ENABLED",
        "PAPER_NOTIFY_EMAIL_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "PAPER_NOTIFY_EMAIL_TO",
    ):
        monkeypatch.delenv(key, raising=False)
    result = notify_paper_report(
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "mode": "paper",
            "account": {"pnl_pct": 0, "drawdown_pct": 0},
            "pnl": {"eur": 0, "btc": 0},
            "balance": {"eur": 1000},
        }
    )
    assert result == {"telegram": False, "email": False}
