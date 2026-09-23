"""Paper-only reporting helpers for the Railway API.

All values are explicitly simulated/accounting values. This module does not
create exchange credentials, wallets, signing, or live-order capabilities.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def build_paper_report(summary: dict, *, peak_equity_usd: float | None = None) -> dict:
    pnl_usd = float(summary.get("total_pnl", 0.0))
    starting = _float_env("PAPER_STARTING_BALANCE_USD", 1000.0)
    balance = starting + pnl_usd
    peak = max(starting, balance, float(peak_equity_usd or starting))
    drawdown = max(0.0, (peak - balance) / peak * 100.0) if peak else 0.0
    pnl_pct = pnl_usd / starting * 100.0 if starting else 0.0
    usd_eur = _float_env("USD_EUR_RATE", 0.92)
    btc_usd = _float_env("BTC_USD_PRICE", 0.0)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "paper",
        "account": {
            "starting_balance_usd": starting,
            "balance_usd": balance,
            "pnl_usd": pnl_usd,
            "pnl_pct": round(pnl_pct, 6),
            "drawdown_pct": round(drawdown, 6),
        },
        "pnl": {
            "usd": pnl_usd,
            "eur": pnl_usd * usd_eur,
            "btc": pnl_usd / btc_usd if btc_usd > 0 else None,
        },
        "balance": {
            "usd": balance,
            "eur": balance * usd_eur,
            "btc": balance / btc_usd if btc_usd > 0 else None,
        },
        "rates": {"usd_eur": usd_eur, "btc_usd": btc_usd or None},
        "summary": summary,
    }
    return report


def export_paper_report(report: dict, export_dir: str | None = None) -> tuple[str, str]:
    folder = Path(export_dir or os.getenv("PAPER_EXPORT_DIR", "exports"))
    folder.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).date().isoformat()
    json_path = folder / f"paper-pnl-{date}.json"
    csv_path = folder / f"paper-pnl-{date}.csv"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    row = {
        "date": date,
        "mode": "paper",
        "pnl_usd": report["pnl"]["usd"],
        "pnl_eur": report["pnl"]["eur"],
        "pnl_btc": report["pnl"]["btc"],
        "pnl_pct": report["account"]["pnl_pct"],
        "drawdown_pct": report["account"]["drawdown_pct"],
        "balance_usd": report["balance"]["usd"],
        "balance_eur": report["balance"]["eur"],
        "balance_btc": report["balance"]["btc"],
        "usd_eur_rate": report["rates"]["usd_eur"],
        "btc_usd": report["rates"]["btc_usd"],
    }
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return str(json_path), str(csv_path)
