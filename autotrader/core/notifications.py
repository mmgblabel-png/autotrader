"""Opt-in notifications for paper PnL reports.

Nothing is sent unless the relevant *_ENABLED flag and all required secrets
are present. Failures are logged and never turn a successful paper export into
a false trading signal.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger("autotrader.notifications")


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _message(report: dict) -> str:
    account = report["account"]
    pnl = report["pnl"]
    return (
        "AutoTrader paper PnL\n"
        f"UTC: {report['generated_at']}\n"
        f"Mode: {report['mode']}\n"
        f"PnL: €{pnl['eur']:.2f} | {pnl['btc'] if pnl['btc'] is not None else 'n/a'} BTC\n"
        f"PnL%: {account['pnl_pct']:.4f}%\n"
        f"Drawdown: {account['drawdown_pct']:.4f}%\n"
        f"Balance: €{report['balance']['eur']:.2f}"
    )


def send_telegram(report: dict) -> bool:
    if not _enabled("PAPER_NOTIFY_TELEGRAM_ENABLED"):
        return False
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.error("Telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urlencode({"chat_id": chat_id, "text": _message(report)}).encode()
    try:
        request = Request(url, data=body, method="POST")
        with urlopen(request, timeout=8) as response:
            return 200 <= response.status < 300
    except OSError as exc:
        log.error("Telegram notification failed: %s", exc)
        return False


def send_email(report: dict) -> bool:
    if not _enabled("PAPER_NOTIFY_EMAIL_ENABLED"):
        return False
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", username).strip()
    recipient = os.getenv("PAPER_NOTIFY_EMAIL_TO", "").strip()
    if not all((host, username, password, sender, recipient)):
        log.error("Email enabled but SMTP/email variables are incomplete")
        return False
    message = EmailMessage()
    message["Subject"] = "AutoTrader paper PnL report"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(_message(report))
    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(message)
        return True
    except OSError as exc:
        log.error("Email notification failed: %s", exc)
        return False


def notify_paper_report(report: dict) -> dict[str, bool]:
    """Attempt enabled channels and return their success status."""
    return {"telegram": send_telegram(report), "email": send_email(report)}
