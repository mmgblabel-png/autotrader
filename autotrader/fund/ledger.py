"""Tamper-evident SQLite event ledger for the fund track record."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import statistics
import threading
import time
from datetime import datetime, timezone
from typing import Any, Mapping


_GENESIS_HASH = "0" * 64


class FundLedger:
    """Append-only hash-chained event ledger with idempotency support."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fund_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fund_events_type ON fund_events(event_type, seq)"
            )

    @staticmethod
    def _canonical_payload(payload: Mapping[str, Any]) -> str:
        return json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @staticmethod
    def _hash_record(
        *,
        event_id: str | None,
        timestamp: float,
        event_type: str,
        payload_json: str,
        prev_hash: str,
    ) -> str:
        envelope = json.dumps(
            {
                "event_id": event_id,
                "timestamp": float(timestamp),
                "event_type": event_type,
                "payload_json": payload_json,
                "prev_hash": prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(envelope.encode("utf-8")).hexdigest()

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        event_id: str | None = None,
        timestamp: float | None = None,
    ) -> dict[str, object]:
        event_type = str(event_type).strip()
        if not event_type:
            raise ValueError("event_type is required")
        event_id = str(event_id).strip() if event_id else None
        ts = float(timestamp if timestamp is not None else time.time())
        if ts <= 0:
            raise ValueError("timestamp must be positive")
        payload_json = self._canonical_payload(payload)

        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if event_id:
                existing = conn.execute(
                    "SELECT seq, event_hash FROM fund_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    return {
                        "seq": int(existing["seq"]),
                        "event_hash": str(existing["event_hash"]),
                        "duplicate": True,
                    }

            previous = conn.execute(
                "SELECT event_hash FROM fund_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_hash = str(previous["event_hash"]) if previous else _GENESIS_HASH
            event_hash = self._hash_record(
                event_id=event_id,
                timestamp=ts,
                event_type=event_type,
                payload_json=payload_json,
                prev_hash=prev_hash,
            )
            cursor = conn.execute(
                """
                INSERT INTO fund_events
                    (event_id, timestamp, event_type, payload_json, prev_hash, event_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, ts, event_type, payload_json, prev_hash, event_hash),
            )
            conn.commit()
            return {
                "seq": int(cursor.lastrowid),
                "event_hash": event_hash,
                "duplicate": False,
            }

    def verify(self) -> dict[str, object]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT seq, event_id, timestamp, event_type, payload_json, prev_hash, event_hash
                FROM fund_events
                ORDER BY seq ASC
                """
            ).fetchall()

        expected_prev = _GENESIS_HASH
        for row in rows:
            if row["prev_hash"] != expected_prev:
                return {
                    "valid": False,
                    "count": len(rows),
                    "broken_seq": int(row["seq"]),
                    "reason": "previous hash mismatch",
                }
            expected_hash = self._hash_record(
                event_id=row["event_id"],
                timestamp=float(row["timestamp"]),
                event_type=str(row["event_type"]),
                payload_json=str(row["payload_json"]),
                prev_hash=str(row["prev_hash"]),
            )
            if expected_hash != row["event_hash"]:
                return {
                    "valid": False,
                    "count": len(rows),
                    "broken_seq": int(row["seq"]),
                    "reason": "event hash mismatch",
                }
            expected_prev = str(row["event_hash"])

        return {
            "valid": True,
            "count": len(rows),
            "head_hash": expected_prev,
        }

    def has_event_type(self, event_type: str) -> bool:
        """Return whether at least one event of the requested type exists."""
        key = str(event_type).strip()
        if not key:
            return False
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM fund_events WHERE event_type = ? LIMIT 1",
                (key,),
            ).fetchone()
        return row is not None

    def max_verified_nav_eur(self) -> float:
        """Return the highest durable NAV backed by verified provenance.

        New high-water events are always verified. Legacy nav_snapshot rows are
        included only when they explicitly carry verified=true, so an old local
        PnL estimate can never become the live drawdown anchor after restart.
        """
        maximum = 0.0
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_type, payload_json
                FROM fund_events
                WHERE event_type IN (?, ?)
                ORDER BY seq ASC
                """,
                ("nav_high_water", "nav_snapshot"),
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
                event_type = str(row["event_type"])
                if event_type == "nav_snapshot" and payload.get("verified") is not True:
                    continue
                value = float(payload.get("nav_eur") or 0.0)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if value > maximum:
                maximum = value
        return maximum

    def max_nav_eur(self) -> float:
        """Return the highest durable NAV snapshot, ignoring malformed payloads."""
        maximum = 0.0
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM fund_events WHERE event_type = ? ORDER BY seq ASC",
                ("nav_snapshot",),
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
                value = float(payload.get("nav_eur") or 0.0)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if value > maximum:
                maximum = value
        return maximum

    def track_record_metrics(self) -> dict[str, object]:
        """Return durable live-only track-record metrics.

        Only verified live NAV checkpoints and live fill events are included.
        Legacy events without explicit execution_mode/live provenance are
        intentionally excluded from investor-grade statistics.
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, event_type, payload_json
                FROM fund_events
                WHERE event_type IN (?, ?)
                ORDER BY seq ASC
                """,
                ("nav_checkpoint", "fill"),
            ).fetchall()

        daily_nav: dict[str, tuple[float, float]] = {}
        exit_pnls: list[float] = []
        live_fill_count = 0
        first_verified_at: float | None = None
        last_verified_at: float | None = None

        for row in rows:
            ts = float(row["timestamp"])
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
            event_type = str(row["event_type"])

            if event_type == "nav_checkpoint":
                if (
                    payload.get("verified") is not True
                    or str(payload.get("execution_mode") or "").lower() != "live"
                ):
                    continue
                try:
                    nav = float(payload.get("nav_eur") or 0.0)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(nav) or nav <= 0:
                    continue
                day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                existing = daily_nav.get(day)
                if existing is None or ts >= existing[0]:
                    daily_nav[day] = (ts, nav)
                first_verified_at = ts if first_verified_at is None else min(first_verified_at, ts)
                last_verified_at = ts if last_verified_at is None else max(last_verified_at, ts)
                continue

            if str(payload.get("execution_mode") or "").lower() != "live":
                continue
            live_fill_count += 1
            if str(payload.get("side") or "").upper() != "SELL":
                continue
            try:
                pnl = float(payload.get("realized_net_pnl_delta_eur") or 0.0)
            except (TypeError, ValueError):
                continue
            if math.isfinite(pnl):
                exit_pnls.append(pnl)

        ordered_daily = [
            daily_nav[key][1]
            for key in sorted(daily_nav)
        ]
        returns: list[float] = []
        for previous, current in zip(ordered_daily, ordered_daily[1:]):
            if previous > 0:
                returns.append(current / previous - 1.0)

        max_drawdown_pct = 0.0
        peak = 0.0
        for nav in ordered_daily:
            peak = max(peak, nav)
            if peak > 0:
                max_drawdown_pct = max(
                    max_drawdown_pct,
                    (peak - nav) / peak * 100.0,
                )

        sharpe_ratio: float | None = None
        sortino_ratio: float | None = None
        if len(returns) >= 2:
            mean_return = statistics.fmean(returns)
            stdev = statistics.stdev(returns)
            if stdev > 0:
                sharpe_ratio = mean_return / stdev * math.sqrt(365.0)
            downside = [min(0.0, value) for value in returns]
            downside_dev = math.sqrt(
                sum(value * value for value in downside) / len(downside)
            )
            if downside_dev > 0:
                sortino_ratio = mean_return / downside_dev * math.sqrt(365.0)

        gross_profit = sum(value for value in exit_pnls if value > 0)
        gross_loss = abs(sum(value for value in exit_pnls if value < 0))
        if gross_loss > 0:
            profit_factor: float | None = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = 999.0
        else:
            profit_factor = None

        wins = sum(1 for value in exit_pnls if value > 0)
        losses = sum(1 for value in exit_pnls if value < 0)
        completed_exits = wins + losses
        elapsed_days = 0
        if first_verified_at is not None and last_verified_at is not None:
            elapsed_days = int(
                max(0.0, last_verified_at - first_verified_at) // 86400
            ) + 1

        return {
            "first_verified_at": first_verified_at,
            "last_verified_at": last_verified_at,
            "elapsed_days": elapsed_days,
            "observation_days": len(ordered_daily),
            "daily_return_observations": len(returns),
            "live_fill_count": live_fill_count,
            "completed_exits": completed_exits,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": (
                round(wins / completed_exits * 100.0, 6)
                if completed_exits
                else 0.0
            ),
            "net_realized_pnl_eur": round(sum(exit_pnls), 6),
            "gross_profit_eur": round(gross_profit, 6),
            "gross_loss_eur": round(gross_loss, 6),
            "profit_factor": (
                None if profit_factor is None else round(profit_factor, 6)
            ),
            "sharpe_ratio": (
                None if sharpe_ratio is None else round(sharpe_ratio, 6)
            ),
            "sortino_ratio": (
                None if sortino_ratio is None else round(sortino_ratio, 6)
            ),
            "max_drawdown_pct": round(max_drawdown_pct, 6),
        }

    def tail(self, limit: int = 25) -> list[dict[str, object]]:
        safe_limit = max(1, min(500, int(limit)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT seq, event_id, timestamp, event_type, payload_json, prev_hash, event_hash
                FROM fund_events
                ORDER BY seq DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in reversed(rows):
            result.append(
                {
                    "seq": int(row["seq"]),
                    "event_id": row["event_id"],
                    "timestamp": float(row["timestamp"]),
                    "event_type": str(row["event_type"]),
                    "payload": json.loads(str(row["payload_json"])),
                    "prev_hash": str(row["prev_hash"]),
                    "event_hash": str(row["event_hash"]),
                }
            )
        return result
