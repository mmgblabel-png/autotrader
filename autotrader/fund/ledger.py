"""Tamper-evident SQLite event ledger for the fund track record."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
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

    def has_event_id(self, event_id: str) -> bool:
        """Return whether an immutable event id is already present."""
        key = str(event_id).strip()
        if not key:
            return False
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT 1 FROM fund_events WHERE event_id = ? LIMIT 1", (key,)).fetchone()
        return row is not None

    def latest_event(self, event_type: str) -> dict[str, object] | None:
        """Return the latest decoded event of one type without exposing internals."""
        key = str(event_type).strip()
        if not key:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT seq, event_id, timestamp, event_type, payload_json, event_hash
                FROM fund_events
                WHERE event_type = ?
                ORDER BY seq DESC
                LIMIT 1
                """,
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "seq": int(row["seq"]),
            "event_id": str(row["event_id"]),
            "timestamp": float(row["timestamp"]),
            "event_type": str(row["event_type"]),
            "payload": json.loads(str(row["payload_json"])),
            "event_hash": str(row["event_hash"]),
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

    def track_record_stats(self) -> dict[str, object]:
        """Return durable live-track-record age and fill count.

        The clock starts at the first recorded live fill, not at application
        boot, so infrastructure uptime can never masquerade as trading history.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    MIN(CASE WHEN event_type = 'fill' THEN timestamp END) AS first_fill_ts,
                    MAX(timestamp) AS last_ts,
                    SUM(CASE WHEN event_type = 'fill' THEN 1 ELSE 0 END) AS fill_count,
                    COUNT(*) AS event_count
                FROM fund_events
                """
            ).fetchone()
        if row is None or row["event_count"] in (None, 0):
            return {
                "first_timestamp": None,
                "last_timestamp": None,
                "days": 0.0,
                "fill_count": 0,
                "event_count": 0,
            }
        first_fill = row["first_fill_ts"]
        last_ts = float(row["last_ts"])
        return {
            "first_timestamp": None if first_fill is None else float(first_fill),
            "last_timestamp": last_ts,
            "days": (
                0.0
                if first_fill is None
                else max(0.0, (last_ts - float(first_fill)) / 86400.0)
            ),
            "fill_count": int(row["fill_count"] or 0),
            "event_count": int(row["event_count"] or 0),
        }

    def performance_stats(
        self,
        *,
        now: float | None = None,
        starting_equity_eur: float = 0.0,
    ) -> dict[str, object]:
        """Aggregate immutable fill accounting into dashboard/reporting metrics."""
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, payload_json
                FROM fund_events
                WHERE event_type = ?
                ORDER BY seq ASC
                """,
                ("fill",),
            ).fetchall()

        realized = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        turnover = 0.0
        positive = 0
        negative = 0
        zero = 0
        pnl_24h = 0.0
        pnl_7d = 0.0
        pnl_30d = 0.0
        cumulative_realized = 0.0
        equity_curve: list[dict[str, float]] = []
        starting_equity = max(0.0, float(starting_equity_eur))

        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
                pnl = float(payload.get("realized_net_pnl_delta_eur") or 0.0)
                notional = max(0.0, float(payload.get("notional_eur") or 0.0))
                ts = float(row["timestamp"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            realized += pnl
            cumulative_realized += pnl
            turnover += notional
            equity_curve.append(
                {
                    "timestamp": ts,
                    "equity_eur": round(
                        max(0.0, starting_equity + cumulative_realized),
                        6,
                    ),
                }
            )
            if pnl > 0:
                positive += 1
                gross_profit += pnl
            elif pnl < 0:
                negative += 1
                gross_loss += abs(pnl)
            else:
                zero += 1
            age = max(0.0, current - ts)
            if age <= 86400.0:
                pnl_24h += pnl
            if age <= 7 * 86400.0:
                pnl_7d += pnl
            if age <= 30 * 86400.0:
                pnl_30d += pnl

        decisive = positive + negative
        return {
            "fill_count": len(rows),
            "profitable_fill_count": positive,
            "loss_fill_count": negative,
            "flat_fill_count": zero,
            "positive_fill_rate_pct": round(
                (positive / decisive * 100.0) if decisive else 0.0,
                6,
            ),
            "realized_net_pnl_eur": round(realized, 6),
            "gross_profit_eur": round(gross_profit, 6),
            "gross_loss_eur": round(gross_loss, 6),
            "profit_factor": (
                None if gross_loss <= 1e-12 else round(gross_profit / gross_loss, 6)
            ),
            "turnover_eur": round(turnover, 6),
            "realized_net_pnl_24h_eur": round(pnl_24h, 6),
            "realized_net_pnl_7d_eur": round(pnl_7d, 6),
            "realized_net_pnl_30d_eur": round(pnl_30d, 6),
            "equity_curve_basis": "starting_equity_plus_recorded_realized_pnl",
            "equity_curve": equity_curve[-200:],
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
