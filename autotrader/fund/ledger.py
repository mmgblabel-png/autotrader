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
