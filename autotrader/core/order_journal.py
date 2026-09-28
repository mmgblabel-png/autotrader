"""Durable local order journal used for exchange reconciliation.

The journal is deliberately small and SQLite-backed so open orders, exchange IDs,
statuses and fills survive process restarts. It stores no API credentials.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


class OrderJournal:
    """Persist order intents and exchange state in a local SQLite database."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.getenv("AUTOTRADER_JOURNAL_DB", "data/orders.sqlite3")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY,
                    exchange_order_id TEXT,
                    market TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    price TEXT,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at REAL NOT NULL DEFAULT (unixepoch()),
                    updated_at REAL NOT NULL DEFAULT (unixepoch())
                );
                CREATE INDEX IF NOT EXISTS idx_orders_exchange_id
                    ON orders(exchange_order_id);
                CREATE INDEX IF NOT EXISTS idx_orders_status
                    ON orders(status);
                CREATE TABLE IF NOT EXISTS fills (
                    client_order_id TEXT NOT NULL,
                    trade_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL DEFAULT (unixepoch()),
                    PRIMARY KEY(client_order_id, trade_id),
                    FOREIGN KEY(client_order_id) REFERENCES orders(client_order_id)
                );
                """
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value if value is not None else {}, separators=(",", ":"), default=str)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"] or "{}")
        return result

    def record_intent(
        self,
        *,
        client_order_id: str,
        market: str,
        side: str,
        order_type: str,
        amount: str,
        price: str | None,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO orders
                (client_order_id, market, side, order_type, amount, price, status)
                VALUES (?, ?, ?, ?, ?, ?, 'intent')
                """,
                (client_order_id, market, side, order_type, amount, price),
            )
            return cur.rowcount == 1

    def get(self, client_order_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            return self._row(conn.execute(
                "SELECT * FROM orders WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone())

    def update(
        self,
        client_order_id: str,
        status: str,
        payload: dict[str, Any] | None = None,
        *,
        exchange_order_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status = ?,
                    payload = ?,
                    exchange_order_id = COALESCE(?, exchange_order_id),
                    error = ?,
                    updated_at = unixepoch()
                WHERE client_order_id = ?
                """,
                (status, self._json(payload), exchange_order_id, error, client_order_id),
            )

    def record_fill(self, client_order_id: str, fill: dict[str, Any]) -> bool:
        trade_id = str(
            fill.get("tradeId")
            or fill.get("tradeID")
            or fill.get("id")
            or self._json(fill)
        )
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO fills(client_order_id, trade_id, payload)
                VALUES (?, ?, ?)
                """,
                (client_order_id, trade_id, self._json(fill)),
            )
            return cur.rowcount == 1

    def fills(self, client_order_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM fills WHERE client_order_id = ? ORDER BY created_at",
                (client_order_id,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def inflight(self) -> list[dict[str, Any]]:
        terminal = ("filled", "canceled", "cancelled", "expired", "rejected", "error", "shadow")
        placeholders = ",".join("?" for _ in terminal)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM orders WHERE status NOT IN ({placeholders}) ORDER BY created_at",
                terminal,
            ).fetchall()
        return [self._row(row) for row in rows if row is not None]

    def all_orders(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM orders ORDER BY created_at").fetchall()
        return [self._row(row) for row in rows if row is not None]


__all__ = ["OrderJournal"]
