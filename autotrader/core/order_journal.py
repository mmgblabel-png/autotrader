"""Durable, append-aware order journal for execution reconciliation."""
from __future__ import annotations
import hashlib

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from decimal import Decimal
from typing import Any


class OrderJournal:
    TERMINAL = {"filled", "canceled", "cancelled", "rejected", "error", "expired", "shadow", "blocked"}

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
        CREATE TABLE IF NOT EXISTS execution_ledger (
          client_order_id TEXT PRIMARY KEY,
          notional_eur TEXT NOT NULL,
          accepted_at REAL NOT NULL,
          FOREIGN KEY(client_order_id) REFERENCES orders(client_order_id)
        );
        """)
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(orders)").fetchall()}
        if "strategy" not in columns:
            self._db.execute("ALTER TABLE orders ADD COLUMN strategy TEXT NOT NULL DEFAULT ''")
        if "quote_to_eur" not in columns:
            self._db.execute("ALTER TABLE orders ADD COLUMN quote_to_eur TEXT NOT NULL DEFAULT '1'")
        self._db.commit()
        self._repair_fully_filled_error_orders()

    def _repair_fully_filled_error_orders(self) -> int:
        """Repair legacy error rows only when durable fills prove full execution."""
        repaired = 0
        now = time.time()
        with self._lock:
            rows = self._db.execute(
                """
                SELECT o.client_order_id, o.amount,
                       COALESCE(SUM(CAST(NULLIF(f.amount,'') AS REAL)),0) AS filled_amount
                FROM orders AS o
                LEFT JOIN fills AS f ON f.client_order_id=o.client_order_id
                WHERE lower(o.status)='error'
                GROUP BY o.client_order_id
                """
            ).fetchall()
            for row in rows:
                try:
                    ordered = max(0.0, float(row["amount"] or 0.0))
                    filled = max(0.0, float(row["filled_amount"] or 0.0))
                except (TypeError, ValueError):
                    continue
                if ordered <= 0:
                    continue
                tolerance = max(1e-12, ordered * 1e-9)
                if filled + tolerance < ordered:
                    continue
                cursor = self._db.execute(
                    """
                    UPDATE orders
                    SET status='filled', last_error=NULL, updated_at=?
                    WHERE client_order_id=? AND lower(status)='error'
                    """,
                    (now, row["client_order_id"]),
                )
                if cursor.rowcount == 1:
                    self._event(
                        str(row["client_order_id"]),
                        "legacy_error_repaired_to_filled",
                        {"filled_amount": filled, "ordered_amount": ordered},
                    )
                    repaired += 1
            self._db.commit()
        return repaired

    def set_strategy(self, client_order_id: str, strategy: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE orders SET strategy=?, updated_at=? WHERE client_order_id=?",
                (strategy, time.time(), client_order_id),
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def record_intent(self, *, client_order_id: str, market: str, side: str, order_type: str, amount: str, price: str | None, quote_to_eur: str = "1") -> bool:
        now = time.time()
        with self._lock:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO orders(client_order_id,market,side,order_type,amount,price,status,created_at,updated_at,quote_to_eur) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (client_order_id, market, side, order_type, amount, price, "intent", now, now, str(quote_to_eur)),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                self._event(client_order_id, "intent", {})
                self._db.commit()
            return inserted

    def update(self, client_order_id: str, status: str, payload: dict[str, Any] | None = None, *, exchange_order_id: str | None = None, error: str | None = None) -> None:
        payload = payload or {}
        now = time.time()
        requested_status = str(status).lower()
        with self._lock:
            effective_status = requested_status
            effective_error = error
            if requested_status == "error":
                current = self._db.execute(
                    "SELECT status, amount FROM orders WHERE client_order_id=?",
                    (client_order_id,),
                ).fetchone()
                if current is not None:
                    current_status = str(current["status"] or "").lower()
                    if current_status in self.TERMINAL and current_status != "error":
                        effective_status = current_status
                        effective_error = None
                    else:
                        fill_row = self._db.execute(
                            """
                            SELECT COALESCE(SUM(CAST(NULLIF(amount,'') AS REAL)),0) AS filled
                            FROM fills WHERE client_order_id=?
                            """,
                            (client_order_id,),
                        ).fetchone()
                        try:
                            ordered = max(0.0, float(current["amount"] or 0.0))
                            filled = max(0.0, float((fill_row or {})["filled"] or 0.0))
                        except (TypeError, ValueError):
                            ordered = 0.0
                            filled = 0.0
                        if ordered > 0 and filled + max(1e-12, ordered * 1e-9) >= ordered:
                            effective_status = "filled"
                            effective_error = None

            preserve_terminal_payload = effective_status != requested_status
            self._db.execute(
                """
                UPDATE orders
                SET status=?,
                    exchange_order_id=COALESCE(?,exchange_order_id),
                    updated_at=?,
                    last_error=?,
                    raw_json=CASE WHEN ? THEN raw_json ELSE ? END
                WHERE client_order_id=?
                """,
                (
                    effective_status,
                    exchange_order_id,
                    now,
                    effective_error,
                    1 if preserve_terminal_payload else 0,
                    json.dumps(payload, default=str),
                    client_order_id,
                ),
            )
            if effective_status != requested_status:
                self._event(
                    client_order_id,
                    "reconcile_error_after_terminal",
                    {"preserved_status": effective_status, "requested_status": requested_status},
                )
            else:
                self._event(client_order_id, effective_status, payload)
            self._db.commit()

    def record_fill(self, client_order_id: str, fill: dict[str, Any]) -> None:
        fill_id = str(fill.get("fillId") or fill.get("id") or "")
        stable_payload = json.dumps(fill, sort_keys=True, separators=(",", ":"), default=str)
        fingerprint = hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()
        fill_key = f"{client_order_id}:{fill_id or fingerprint}"
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

    def record_execution_acceptance(self, client_order_id: str, notional_eur: str) -> bool:
        """Persist an accepted execution budget once, before the exchange POST."""
        with self._lock:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO execution_ledger(client_order_id,notional_eur,accepted_at) VALUES(?,?,?)",
                (client_order_id, str(notional_eur), time.time()),
            )
            self._db.commit()
            return cursor.rowcount == 1

    def daily_execution_exposure_utc(self, now: float | None = None) -> Decimal:
        """Return accepted EUR exposure since UTC midnight."""
        current = time.time() if now is None else float(now)
        utc = time.gmtime(current)
        midnight = current - (utc.tm_hour * 3600 + utc.tm_min * 60 + utc.tm_sec)
        with self._lock:
            rows = self._db.execute(
                """
                SELECT e.notional_eur
                FROM execution_ledger AS e
                JOIN orders AS o ON o.client_order_id=e.client_order_id
                WHERE e.accepted_at>=? AND lower(o.side)='buy'
                """,
                (midnight,),
            ).fetchall()
        total = Decimal("0")
        for row in rows:
            try:
                total += Decimal(str(row["notional_eur"]))
            except Exception:
                continue
        return max(total, Decimal("0"))

    def current_execution_exposure_eur(self) -> Decimal:
        """Return current bot-owned EUR capital at risk.

        Exposure is inventory cost from confirmed BUY fills plus the unfilled
        remainder of active BUY orders. Completed SELLs and canceled/rejected
        BUYs therefore release headroom instead of permanently consuming the
        daily capital-at-risk cap.
        """
        with self._lock:
            pairs = self._db.execute(
                """
                SELECT DISTINCT market, strategy
                FROM orders
                WHERE strategy<>'' AND lower(side) IN ('buy','sell')
                """
            ).fetchall()
            open_buys = self._db.execute(
                """
                SELECT o.client_order_id, o.amount, o.price,
                       COALESCE(SUM(CAST(NULLIF(f.amount,'') AS REAL)),0) AS filled_amount,
                       e.notional_eur
                FROM orders AS o
                LEFT JOIN fills AS f ON f.client_order_id=o.client_order_id
                LEFT JOIN execution_ledger AS e ON e.client_order_id=o.client_order_id
                WHERE lower(o.side)='buy'
                  AND o.status NOT IN ('filled','canceled','cancelled','rejected','error','expired','shadow','blocked')
                GROUP BY o.client_order_id
                """
            ).fetchall()

        total = Decimal("0")
        for pair in pairs:
            perf = self.strategy_performance(
                str(pair["market"]),
                str(pair["strategy"]),
                mark_price=Decimal("0"),
                estimated_exit_cost_pct=Decimal("0"),
            )
            total += max(Decimal("0"), Decimal(str(perf["inventory_cost_eur"])))

        for row in open_buys:
            try:
                amount = max(Decimal("0"), Decimal(str(row["amount"] or "0")))
                filled = max(Decimal("0"), Decimal(str(row["filled_amount"] or "0")))
                remaining = max(Decimal("0"), amount - filled)
                if remaining <= 0:
                    continue
                if row["price"] not in {None, ""}:
                    total += remaining * Decimal(str(row["price"]))
                elif row["notional_eur"] not in {None, ""} and amount > 0:
                    total += Decimal(str(row["notional_eur"])) * (remaining / amount)
            except Exception:
                continue
        return max(total, Decimal("0"))

    def backfill_execution_ledger(self) -> int:
        """Conservatively seed legacy accepted limit orders into the exposure ledger."""
        with self._lock:
            rows = self._db.execute(
                """
                SELECT client_order_id, amount, price, created_at
                FROM orders
                WHERE price IS NOT NULL
                  AND lower(side)='buy'
                  AND status NOT IN ('rejected','error','shadow','blocked')
                """
            ).fetchall()
            inserted = 0
            for row in rows:
                try:
                    notional = Decimal(str(row["amount"])) * Decimal(str(row["price"]))
                except Exception:
                    continue
                cursor = self._db.execute(
                    "INSERT OR IGNORE INTO execution_ledger(client_order_id,notional_eur,accepted_at) VALUES(?,?,?)",
                    (row["client_order_id"], str(notional), float(row["created_at"])),
                )
                inserted += cursor.rowcount
            self._db.commit()
        return inserted

    def all_strategy_fills(self) -> list[dict[str, Any]]:
        """Return durable fill history with strategy ownership for PnL rebuilds."""
        with self._lock:
            rows = self._db.execute(
                """
                SELECT f.fill_key, f.amount, f.price, f.fee, f.observed_at, f.raw_json,
                       o.market, o.side, o.strategy
                FROM fills AS f
                JOIN orders AS o ON o.client_order_id=f.client_order_id
                WHERE o.strategy<>''
                ORDER BY f.observed_at, f.fill_key
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def strategy_active_markets(
        self,
        strategy: str,
        *,
        min_inventory_quote_value: Decimal = Decimal("0"),
    ) -> list[dict[str, Any]]:
        """Return bot-owned markets that still need runtime management.

        A market is active when this strategy has a durable nonterminal order or
        positive fill-derived inventory. This is used after process restarts so
        dynamically routed positions are not forgotten when config defaults are
        reloaded.
        """
        with self._lock:
            rows = self._db.execute(
                """
                SELECT market,
                       SUM(CASE WHEN status NOT IN
                           ('filled','canceled','cancelled','rejected','error','expired','shadow','blocked')
                           THEN 1 ELSE 0 END) AS open_orders
                FROM orders
                WHERE strategy=?
                GROUP BY market
                """,
                (strategy,),
            ).fetchall()
        active: list[dict[str, Any]] = []
        for row in rows:
            market = str(row["market"] or "").upper()
            if not market:
                continue
            inventory = self.inventory_cost_basis(market, strategy)
            quantity = max(Decimal("0"), Decimal(str(inventory.get("quantity") or "0")))
            average_entry = max(
                Decimal("0"),
                Decimal(str(inventory.get("average_entry_price") or "0")),
            )
            open_orders = int(row["open_orders"] or 0)
            inventory_value = quantity * average_entry
            inventory_is_dust = (
                open_orders <= 0
                and quantity > 0
                and min_inventory_quote_value > 0
                and average_entry > 0
                and inventory_value < min_inventory_quote_value
            )
            if open_orders > 0 or (quantity > 0 and not inventory_is_dust):
                active.append({
                    "market": market,
                    "open_orders": open_orders,
                    "inventory_quantity": str(quantity),
                    "inventory_quote_value": str(inventory_value),
                    "average_entry_price": str(average_entry),
                })
        active.sort(
            key=lambda x: (
                int(x["open_orders"]) > 0,
                Decimal(str(x["inventory_quantity"])) > 0,
                Decimal(str(x["inventory_quantity"])),
            ),
            reverse=True,
        )
        return active

    def recent_order_activity(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return privacy-safe recent order history with aggregate fill details.

        Exchange/client order identifiers and raw payloads are deliberately omitted.
        """
        safe_limit = max(1, min(int(limit), 250))
        with self._lock:
            rows = self._db.execute(
                """
                SELECT
                    o.market,
                    o.side,
                    o.order_type,
                    o.amount,
                    o.price,
                    o.status,
                    o.strategy,
                    o.created_at,
                    o.updated_at,
                    o.last_error,
                    COUNT(f.fill_key) AS fill_count,
                    COALESCE(SUM(CAST(NULLIF(f.amount,'') AS REAL)), 0) AS filled_amount,
                    COALESCE(SUM(CAST(NULLIF(f.fee,'') AS REAL)), 0) AS fee_total,
                    MAX(f.observed_at) AS last_fill_at
                FROM orders AS o
                LEFT JOIN fills AS f ON f.client_order_id=o.client_order_id
                GROUP BY o.client_order_id
                ORDER BY o.created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def activity_summary_since(self, since: float) -> dict[str, Any]:
        """Return compact execution activity for a rolling dashboard window."""
        cutoff = float(since)
        with self._lock:
            order_rows = self._db.execute(
                """
                SELECT status, COUNT(*) AS n
                FROM orders
                WHERE created_at>=?
                GROUP BY status
                """,
                (cutoff,),
            ).fetchall()
            fill_rows = self._db.execute(
                """
                SELECT f.fee, f.price, f.raw_json, o.market
                FROM fills AS f
                JOIN orders AS o ON o.client_order_id=f.client_order_id
                WHERE f.observed_at>=?
                """,
                (cutoff,),
            ).fetchall()
            open_row = self._db.execute(
                """
                SELECT COUNT(*) AS n
                FROM orders
                WHERE status NOT IN ('filled','canceled','cancelled','rejected','error','expired','shadow','blocked')
                """
            ).fetchone()
        counts = {str(row["status"]): int(row["n"] or 0) for row in order_rows}
        error_count = sum(
            counts.get(key, 0) for key in ("rejected", "error", "blocked")
        )
        fees_eur = Decimal("0")
        unpriced_fee_count = 0
        for row in fill_rows:
            try:
                fee = abs(Decimal(str(row["fee"] or "0")))
                price = abs(Decimal(str(row["price"] or "0")))
                base, _, quote = str(row["market"] or "").upper().partition("-")
                payload = json.loads(row["raw_json"] or "{}")
                fee_currency = str(payload.get("feeCurrency") or quote).upper()
                if fee_currency == quote or not fee_currency:
                    fees_eur += fee
                elif fee_currency == base and price > 0:
                    fees_eur += fee * price
                elif fee > 0:
                    unpriced_fee_count += 1
            except Exception:
                unpriced_fee_count += 1
        return {
            "orders_created": sum(counts.values()),
            "status_counts": counts,
            "error_orders": error_count,
            "fills": len(fill_rows),
            "fees_eur": float(fees_eur),
            "unpriced_fee_count": unpriced_fee_count,
            "open_orders_now": int((open_row or {})["n"] or 0) if open_row else 0,
        }

    def inflight(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM orders WHERE status NOT IN ('filled','canceled','cancelled','rejected','error','expired','shadow','blocked') ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def reconcile_candidates(self) -> list[dict[str, Any]]:
        """Return active orders plus errored orders that reached Bitvavo."""
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM orders
                WHERE status NOT IN ('filled','canceled','cancelled','rejected','expired','shadow','blocked')
                   OR status='error'
                ORDER BY created_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def fills(self, client_order_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM fills WHERE client_order_id=? ORDER BY observed_at", (client_order_id,)).fetchall()
        return [dict(row) for row in rows]

    def net_base_inventory(self, market: str, strategy: str) -> Decimal:
        """Return base-asset inventory created by this strategy's recorded fills."""
        base = market.upper().split("-", 1)[0]
        with self._lock:
            rows = self._db.execute(
                """
                SELECT o.side, f.amount, f.fee, f.raw_json
                FROM fills AS f
                JOIN orders AS o ON o.client_order_id=f.client_order_id
                WHERE o.market=? AND o.strategy=?
                ORDER BY f.observed_at
                """,
                (market.upper(), strategy),
            ).fetchall()
        total = Decimal("0")
        for row in rows:
            amount = Decimal(str(row["amount"] or "0"))
            side = str(row["side"] or "").lower()
            total += amount if side == "buy" else -amount
            try:
                payload = json.loads(row["raw_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if str(payload.get("feeCurrency") or "").upper() == base:
                total -= abs(Decimal(str(row["fee"] or payload.get("fee") or "0")))
        return max(total, Decimal("0"))

    def inventory_cost_basis(self, market: str, strategy: str) -> dict[str, Decimal]:
        """Average-cost basis for currently bot-owned base inventory."""
        base, _, quote = market.upper().partition("-")
        with self._lock:
            rows = self._db.execute(
                """
                SELECT o.side, f.amount, f.price, f.fee, f.raw_json
                FROM fills AS f
                JOIN orders AS o ON o.client_order_id=f.client_order_id
                WHERE o.market=? AND o.strategy=?
                ORDER BY f.observed_at, f.fill_key
                """,
                (market.upper(), strategy),
            ).fetchall()
        quantity = Decimal("0")
        cost = Decimal("0")
        for row in rows:
            amount = Decimal(str(row["amount"] or "0"))
            price = Decimal(str(row["price"] or "0"))
            fee = abs(Decimal(str(row["fee"] or "0")))
            try:
                payload = json.loads(row["raw_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            fee_currency = str(payload.get("feeCurrency") or "").upper()
            side = str(row["side"] or "").lower()
            if side == "buy":
                received = amount - fee if fee_currency == base else amount
                added_cost = amount * price + (fee if fee_currency == quote else Decimal("0"))
                if received > 0:
                    quantity += received
                    cost += added_cost
            elif side == "sell" and quantity > 0:
                outgoing = amount + (fee if fee_currency == base else Decimal("0"))
                outgoing = min(outgoing, quantity)
                avg = cost / quantity if quantity > 0 else Decimal("0")
                quantity -= outgoing
                cost -= avg * outgoing
                if quantity <= Decimal("0.000000000000000001"):
                    quantity = Decimal("0")
                    cost = Decimal("0")
        average = cost / quantity if quantity > 0 else Decimal("0")
        return {"quantity": max(quantity, Decimal("0")), "average_entry_price": max(average, Decimal("0"))}

    def strategy_performance(
        self,
        market: str,
        strategy: str,
        *,
        mark_price: Decimal | None = None,
        estimated_exit_cost_pct: Decimal = Decimal("0"),
    ) -> dict[str, Decimal | int]:
        """Return durable fee-aware performance for one strategy/market.

        Accounting uses average cost and actual recorded fills. BUY quote fees
        are embedded in inventory cost, base fees reduce received inventory,
        SELL quote fees reduce proceeds, and base fees increase inventory
        consumed by the exit. Unrealized net PnL assumes the entire current
        inventory could be exited at mark_price after configured future exit
        friction.
        """
        base, _, quote = market.upper().partition("-")
        with self._lock:
            rows = self._db.execute(
                """
                SELECT o.side, f.amount, f.price, f.fee, f.raw_json
                FROM fills AS f
                JOIN orders AS o ON o.client_order_id=f.client_order_id
                WHERE o.market=? AND o.strategy=?
                ORDER BY f.observed_at, f.fill_key
                """,
                (market.upper(), strategy),
            ).fetchall()

        quantity = Decimal("0")
        inventory_cost = Decimal("0")
        realized_net = Decimal("0")
        fees_quote = Decimal("0")
        buy_cash_out = Decimal("0")
        sell_cash_in = Decimal("0")
        profitable_exits = 0
        losing_exits = 0
        unpriced_fee_count = 0

        for row in rows:
            amount = abs(Decimal(str(row["amount"] or "0")))
            price = abs(Decimal(str(row["price"] or "0")))
            fee = abs(Decimal(str(row["fee"] or "0")))
            if amount <= 0 or price <= 0:
                continue
            try:
                payload = json.loads(row["raw_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            fee_currency = str(payload.get("feeCurrency") or quote).upper()
            if fee_currency == base:
                fee_quote = fee * price
            elif fee_currency == quote or not fee_currency:
                fee_quote = fee
            else:
                fee_quote = Decimal("0")
                if fee > 0:
                    unpriced_fee_count += 1
            fees_quote += fee_quote

            side = str(row["side"] or "").lower()
            if side == "buy":
                received = amount - (fee if fee_currency == base else Decimal("0"))
                cash_cost = amount * price + (fee if fee_currency == quote else Decimal("0"))
                if received > 0:
                    quantity += received
                    inventory_cost += cash_cost
                    buy_cash_out += cash_cost
            elif side == "sell":
                base_fee = fee if fee_currency == base else Decimal("0")
                outgoing = min(quantity, amount + base_fee) if quantity > 0 else Decimal("0")
                proceeds = amount * price - (fee if fee_currency == quote else Decimal("0"))
                sell_cash_in += proceeds
                if outgoing <= 0 or quantity <= 0:
                    continue
                avg_cost = inventory_cost / quantity
                removed_cost = avg_cost * outgoing
                exit_pnl = proceeds - removed_cost
                realized_net += exit_pnl
                if exit_pnl > 0:
                    profitable_exits += 1
                elif exit_pnl < 0:
                    losing_exits += 1
                quantity -= outgoing
                inventory_cost -= removed_cost
                if quantity <= Decimal("0.000000000000000001"):
                    quantity = Decimal("0")
                    inventory_cost = Decimal("0")

        avg_entry = inventory_cost / quantity if quantity > 0 else Decimal("0")
        mark = max(Decimal("0"), Decimal(str(mark_price or "0")))
        exit_cost_ratio = max(Decimal("0"), Decimal(str(estimated_exit_cost_pct))) / Decimal("100")
        if exit_cost_ratio >= Decimal("1"):
            exit_cost_ratio = Decimal("0.999999")

        expected_exit_proceeds = Decimal("0")
        unrealized_net = Decimal("0")
        break_even_exit = Decimal("0")
        if quantity > 0 and mark > 0:
            expected_exit_proceeds = quantity * mark * (Decimal("1") - exit_cost_ratio)
            unrealized_net = expected_exit_proceeds - inventory_cost
        if quantity > 0:
            break_even_exit = avg_entry / (Decimal("1") - exit_cost_ratio)

        return {
            "quantity": max(quantity, Decimal("0")),
            "inventory_cost_eur": max(inventory_cost, Decimal("0")),
            "average_entry_price": max(avg_entry, Decimal("0")),
            "realized_net_pnl_eur": realized_net,
            "fees_quote_equivalent_eur": fees_quote,
            "buy_cash_out_eur": buy_cash_out,
            "sell_cash_in_eur": sell_cash_in,
            "mark_price": mark,
            "estimated_exit_proceeds_eur": expected_exit_proceeds,
            "unrealized_net_pnl_eur": unrealized_net,
            "economic_pnl_eur": realized_net + unrealized_net,
            "break_even_exit_price": break_even_exit,
            "profitable_exits": profitable_exits,
            "losing_exits": losing_exits,
            "unpriced_fee_count": unpriced_fee_count,
        }

    def latest_fill_time(self, market: str, strategy: str, side: str | None = None) -> float:
        """Return the latest locally observed fill time for a strategy/market."""
        params: list[Any] = [market.upper(), strategy]
        side_clause = ""
        if side:
            side_clause = " AND lower(o.side)=?"
            params.append(side.lower())
        with self._lock:
            row = self._db.execute(
                f"""
                SELECT MAX(f.observed_at) AS ts
                FROM fills AS f
                JOIN orders AS o ON o.client_order_id=f.client_order_id
                WHERE o.market=? AND o.strategy=?{side_clause}
                """,
                tuple(params),
            ).fetchone()
        return float((row or {})["ts"] or 0.0) if row else 0.0

    def strategy_market_state(self, market: str, strategy: str) -> dict[str, Any]:
        """Return redacted journal diagnostics for one strategy/market."""
        with self._lock:
            latest = self._db.execute(
                "SELECT side,status,amount FROM orders WHERE market=? AND strategy=? ORDER BY created_at DESC LIMIT 1",
                (market.upper(), strategy),
            ).fetchone()
            fill_count = self._db.execute(
                """
                SELECT COUNT(*) AS n
                FROM fills AS f
                JOIN orders AS o ON o.client_order_id=f.client_order_id
                WHERE o.market=? AND o.strategy=?
                """,
                (market.upper(), strategy),
            ).fetchone()["n"]
            nonterminal = self._db.execute(
                """
                SELECT COUNT(*) AS n FROM orders
                WHERE market=? AND strategy=?
                  AND status NOT IN ('filled','canceled','cancelled','rejected','error','expired','shadow','blocked')
                """,
                (market.upper(), strategy),
            ).fetchone()["n"]
        inventory = self.inventory_cost_basis(market, strategy)
        return {
            "latest_side": str(latest["side"]).lower() if latest else None,
            "latest_status": str(latest["status"]).lower() if latest else None,
            "latest_amount": str(latest["amount"]) if latest else None,
            "fill_count": int(fill_count or 0),
            "nonterminal_count": int(nonterminal or 0),
            "net_base_inventory": str(inventory["quantity"]),
            "average_entry_price": str(inventory["average_entry_price"]),
        }

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT status, COUNT(*) AS n FROM orders GROUP BY status").fetchall()
        return {row["status"]: row["n"] for row in rows}

    def __enter__(self) -> "OrderJournal":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
