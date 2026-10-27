"""Realtime Coinbase Advanced Trade order-flow engine.

Broad discovery remains REST based. This component subscribes only to the most
interesting fundable products and maintains an in-memory Level-2 book plus a
short rolling market-trade tape. It is market-data only: it never places orders.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

try:
    from coinbase.websocket import WSClient
except Exception:  # pragma: no cover - surfaced in status at runtime
    WSClient = None


@dataclass(frozen=True)
class CoinbaseRealtimeOrderflowConfig:
    enabled: bool = True
    max_products: int = 20
    depth_levels: int = 10
    trade_window_seconds: float = 60.0
    stale_after_seconds: float = 15.0
    max_trade_events_per_product: int = 4000

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "CoinbaseRealtimeOrderflowConfig":
        cfg = raw or {}
        return cls(
            enabled=bool(cfg.get("enabled", True)),
            max_products=max(1, min(50, int(cfg.get("max_products", 20)))),
            depth_levels=max(1, min(50, int(cfg.get("depth_levels", 10)))),
            trade_window_seconds=max(10.0, float(cfg.get("trade_window_seconds", 60.0))),
            stale_after_seconds=max(2.0, float(cfg.get("stale_after_seconds", 15.0))),
            max_trade_events_per_product=max(
                100, min(20_000, int(cfg.get("max_trade_events_per_product", 4000)))
            ),
        )


class CoinbaseRealtimeOrderflowEngine:
    """Thread-safe public market-data WebSocket state."""

    CHANNELS = ("level2", "market_trades", "ticker")

    def __init__(self, config: CoinbaseRealtimeOrderflowConfig | dict[str, Any] | None = None) -> None:
        self.config = (
            config
            if isinstance(config, CoinbaseRealtimeOrderflowConfig)
            else CoinbaseRealtimeOrderflowConfig.from_mapping(config)
        )
        self._lock = threading.RLock()
        self._client = None
        self._connected = False
        self._started = False
        self._subscribed: set[str] = set()
        self._books: dict[str, dict[str, dict[float, float]]] = defaultdict(
            lambda: {"bids": {}, "asks": {}}
        )
        self._trades: dict[str, deque[tuple[float, str, float]]] = defaultdict(
            lambda: deque(maxlen=self.config.max_trade_events_per_product)
        )
        self._tickers: dict[str, dict[str, float]] = {}
        self._last_product_update: dict[str, float] = {}
        self._last_message_at = 0.0
        self._messages = 0
        self._last_error: str | None = None

    @staticmethod
    def _float(value: object, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _book_side(value: object) -> str | None:
        side = str(value or "").upper()
        if side in {"BID", "BUY"}:
            return "bids"
        if side in {"ASK", "OFFER", "SELL"}:
            return "asks"
        return None

    @staticmethod
    def _trade_side(value: object) -> str:
        side = str(value or "").upper()
        return side if side in {"BUY", "SELL"} else "UNKNOWN"

    def _on_open(self) -> None:
        with self._lock:
            self._connected = True
            self._last_error = None

    def _on_close(self) -> None:
        with self._lock:
            self._connected = False

    def _on_message(self, raw: str) -> None:
        try:
            self.process_message(raw)
        except Exception as exc:
            with self._lock:
                self._last_error = type(exc).__name__

    def start(self) -> None:
        if not self.config.enabled or self._started:
            return
        if WSClient is None:
            with self._lock:
                self._last_error = "coinbase_advanced_py_missing"
            return
        client = WSClient(
            api_key=None,
            api_secret=None,
            on_message=self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
            timeout=5,
            max_size=4 * 1024 * 1024,
            retry=True,
        )
        client.open()
        # Heartbeats keep otherwise quiet subscriptions alive and give us a
        # connection liveness signal without private-account authentication.
        client.subscribe([], ["heartbeats"])
        self._client = client
        self._started = True

    def close(self) -> None:
        client = self._client
        self._client = None
        self._started = False
        if client is None:
            return
        try:
            client.close()
        except Exception:
            pass
        with self._lock:
            self._connected = False

    def set_products(self, product_ids: list[str] | tuple[str, ...]) -> None:
        desired_list: list[str] = []
        seen: set[str] = set()
        for raw in product_ids:
            product = str(raw or "").upper().strip()
            if not product or product in seen:
                continue
            seen.add(product)
            desired_list.append(product)
            if len(desired_list) >= self.config.max_products:
                break
        desired = set(desired_list)

        with self._lock:
            current = set(self._subscribed)
        add = sorted(desired - current)
        remove = sorted(current - desired)

        client = self._client
        if client is not None and self._started:
            try:
                if remove:
                    client.unsubscribe(remove, list(self.CHANNELS))
                if add:
                    client.subscribe(add, list(self.CHANNELS))
            except Exception as exc:
                with self._lock:
                    self._last_error = type(exc).__name__
                return

        with self._lock:
            self._subscribed = desired
            for product in remove:
                self._books.pop(product, None)
                self._trades.pop(product, None)
                self._tickers.pop(product, None)
                self._last_product_update.pop(product, None)

    def process_message(self, raw: str | dict[str, Any], *, received_at: float | None = None) -> None:
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
        now = float(time.time() if received_at is None else received_at)
        channel = str(payload.get("channel") or "")
        events = payload.get("events") or []

        with self._lock:
            self._last_message_at = now
            self._messages += 1
            self._last_error = None

            if channel == "l2_data":
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    product = str(event.get("product_id") or "").upper()
                    if not product:
                        continue
                    event_type = str(event.get("type") or "").lower()
                    if event_type == "snapshot":
                        self._books[product] = {"bids": {}, "asks": {}}
                    book = self._books[product]
                    for update in event.get("updates") or []:
                        if not isinstance(update, dict):
                            continue
                        side = self._book_side(update.get("side"))
                        price = self._float(update.get("price_level"))
                        quantity = self._float(update.get("new_quantity"))
                        if side is None or price <= 0:
                            continue
                        if quantity <= 0:
                            book[side].pop(price, None)
                        else:
                            book[side][price] = quantity
                    self._last_product_update[product] = now

            elif channel == "market_trades":
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    for trade in event.get("trades") or []:
                        if not isinstance(trade, dict):
                            continue
                        product = str(trade.get("product_id") or "").upper()
                        price = self._float(trade.get("price"))
                        size = self._float(trade.get("size"))
                        if not product or price <= 0 or size <= 0:
                            continue
                        self._trades[product].append(
                            (now, self._trade_side(trade.get("side")), price * size)
                        )
                        self._last_product_update[product] = now

            elif channel in {"ticker", "ticker_batch"}:
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    for ticker in event.get("tickers") or []:
                        if not isinstance(ticker, dict):
                            continue
                        product = str(ticker.get("product_id") or "").upper()
                        if not product:
                            continue
                        self._tickers[product] = {
                            "price": self._float(ticker.get("price")),
                            "best_bid": self._float(ticker.get("best_bid")),
                            "best_ask": self._float(ticker.get("best_ask")),
                            "best_bid_quantity": self._float(ticker.get("best_bid_quantity")),
                            "best_ask_quantity": self._float(ticker.get("best_ask_quantity")),
                        }
                        self._last_product_update[product] = now

    def snapshot(self, product_id: str, *, now: float | None = None) -> dict[str, Any]:
        product = str(product_id or "").upper()
        ts = float(time.time() if now is None else now)
        with self._lock:
            raw_book = self._books.get(product) or {"bids": {}, "asks": {}}
            bids = sorted(raw_book["bids"].items(), key=lambda row: row[0], reverse=True)[
                : self.config.depth_levels
            ]
            asks = sorted(raw_book["asks"].items(), key=lambda row: row[0])[
                : self.config.depth_levels
            ]
            ticker = dict(self._tickers.get(product) or {})
            trades = self._trades.get(product)
            tape = list(trades or [])
            last_update = float(self._last_product_update.get(product, 0.0) or 0.0)
            subscribed = product in self._subscribed

        cutoff = ts - self.config.trade_window_seconds
        tape = [row for row in tape if row[0] >= cutoff]
        best_bid = bids[0][0] if bids else self._float(ticker.get("best_bid"))
        best_ask = asks[0][0] if asks else self._float(ticker.get("best_ask"))
        bid_qty = bids[0][1] if bids else self._float(ticker.get("best_bid_quantity"))
        ask_qty = asks[0][1] if asks else self._float(ticker.get("best_ask_quantity"))
        mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
        spread_bps = (
            (best_ask - best_bid) / mid * 10_000.0
            if mid > 0 and best_ask >= best_bid
            else 0.0
        )

        bid_depth = sum(price * qty for price, qty in bids)
        ask_depth = sum(price * qty for price, qty in asks)
        depth_total = bid_depth + ask_depth
        book_imbalance = (bid_depth - ask_depth) / depth_total if depth_total > 0 else 0.0

        microprice = mid
        best_total = bid_qty + ask_qty
        if best_bid > 0 and best_ask > 0 and best_total > 0:
            microprice = (best_ask * bid_qty + best_bid * ask_qty) / best_total
        microprice_edge_bps = (
            (microprice - mid) / mid * 10_000.0 if mid > 0 else 0.0
        )

        buy_notional = sum(n for _, side, n in tape if side == "BUY")
        sell_notional = sum(n for _, side, n in tape if side == "SELL")
        flow_total = buy_notional + sell_notional
        trade_flow_imbalance = (
            (buy_notional - sell_notional) / flow_total if flow_total > 0 else 0.0
        )

        recent_cut = ts - min(10.0, self.config.trade_window_seconds / 2.0)
        recent_count = sum(1 for at, _, _ in tape if at >= recent_cut)
        prior_count = max(0, len(tape) - recent_count)
        recent_window = max(1.0, ts - recent_cut)
        prior_window = max(1.0, self.config.trade_window_seconds - recent_window)
        recent_rate = recent_count / recent_window
        prior_rate = prior_count / prior_window
        velocity_ratio = (
            recent_rate / prior_rate
            if prior_rate > 1e-9
            else (2.0 if recent_rate > 0 else 1.0)
        )

        age = max(0.0, ts - last_update) if last_update > 0 else None
        fresh = bool(age is not None and age <= self.config.stale_after_seconds)

        return {
            "product_id": product,
            "subscribed": subscribed,
            "fresh": fresh,
            "age_seconds": round(age, 3) if age is not None else None,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_bps": spread_bps,
            "bid_depth_quote": bid_depth,
            "ask_depth_quote": ask_depth,
            "book_imbalance": book_imbalance,
            "microprice": microprice,
            "microprice_edge_bps": microprice_edge_bps,
            "reported_buy_notional": buy_notional,
            "reported_sell_notional": sell_notional,
            "trade_flow_imbalance": trade_flow_imbalance,
            "trade_count": len(tape),
            "trade_velocity_ratio": velocity_ratio,
        }

    def status(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            age = max(0.0, now - self._last_message_at) if self._last_message_at else None
            return {
                "enabled": self.config.enabled,
                "started": self._started,
                "connected": self._connected,
                "subscribed_products": sorted(self._subscribed),
                "subscribed_count": len(self._subscribed),
                "messages": self._messages,
                "last_message_age_seconds": round(age, 3) if age is not None else None,
                "last_error": self._last_error,
                "channels": list(self.CHANNELS),
            }
