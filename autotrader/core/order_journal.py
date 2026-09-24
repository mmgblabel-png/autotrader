"""Durable, append-aware order journal for execution reconciliation."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class OrderJournal:
    TERMINAL = {"filled", "canceled", "cancelled", "rejected", "error", "expired"}

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("ORDER_JOURNAL_PATH", "data/orders.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
          client_order_id TEXT PRIMARY KEY, market TEXT NOT NULL, side TEXT NOT NULL,
          order_type TEXT NOT NULL, amount TEXT NOT NULL, price TEXT, status TEXT NOT NULL,
          exchange_order_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
          last_error TEXT, raw_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS fills (
          fill_key TEXT PRIMARY KEY, client_order_id TEXT NOT NULL,
          exchange_fill_id TEXT, amount TEXT, price TEXT, fee TEXT,
          observed_at REAL NOT NULL, raw_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(client_order_id) REFERENCES orders(client_order_id)
        );
        CREATE TABLE IF NOT EXISTS order_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, client_order_id TEXT NOT NULL,
          status TEXT NOT NULL, observed_at REAL NOT NULL, raw_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(client_order_id) REFERENCES orders(client_order_id)
        );
        """)
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def record_intent(self, *, client_order_id: str, market: str, side: str, order_type: str, amount: str, price: str | None) -> bool:
        now = time.time()
        with self._lock:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO orders(client_order_id,market,side,order_type,amount,price,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (client_order_id, market, side, order_type, amount, price, "intent", now, now),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                self._event(client_order_id, "intent", {})
                self._db.commit()
            return inserted

    def update(self, client_order_id: str, status: str, payload: dict[str, Any] | None = None, *, exchange_order_id: str | None = None, error: str | None = None) -> None:
        payload = payload or {}
        now = time.time()
        with self._lock:
            self._db.execute(
                "UPDATE orders SET status=?, exchange_order_id=COALESCE(?,exchange_order_id), updated_at=?, last_error=?, raw_json=? WHERE client_order_id=?",
                (status, exchange_order_id, now, error, json.dumps(payload, default=str), client_order_id),
            )
            self._event(client_order_id, status, payload)
            self._db.commit()

    def record_fill(self, client_order_id: str, fill: dict[str, Any]) -> None:
        fill_id = str(fill.get("fillId") or fill.get("id") or "")
        fill_key = f"{client_order_id}:{fill_id or hash(json.dumps(fill, sort_keys=True, default=str))}"
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO fills(fill_key,client_order_id,exchange_fill_id,amount,price,fee,observed_at,raw_json) VALUES(?,?,?,?,?,?,?,?)",
                (fill_key, client_order_id, fill_id or None, str(fill.get("amount") or fill.get("filledAmount") or ""), str(fill.get("price") or ""), str(fill.get("fee") or ""), time.time(), json.dumps(fill, default=str)),
            )
            self._db.commit()

    def _event(self, client_order_id: str, status: str, payload: dict[str, Any]) -> None:
        self._db.execute("INSERT INTO order_events(client_order_id,status,observed_at,raw_json) VALUES(?,?,?,?)", (client_order_id, status, time.time(), json.dumps(payload, default=str)))

    def get(self, client_order_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
        return dict(row) if row else None

    def inflight(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM orders WHERE status NOT IN ('filled','canceled','cancelled','rejected','error','expired') ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def fills(self, client_order_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM fills WHERE client_order_id=? ORDER BY observed_at", (client_order_id,)).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT status, COUNT(*) AS n FROM orders GROUP BY status").fetchall()
        return {row["status"]: row["n"] for row in rows}

    def __enter__(self) -> "OrderJournal":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
