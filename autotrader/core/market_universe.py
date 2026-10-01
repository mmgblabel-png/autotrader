"""Read-only full-market discovery across Bitvavo and Coinbase Advanced.

Inventories all active spot pairs, including crypto/crypto pairs. It never
places orders. Quote currencies are converted to EUR through the live Bitvavo
market graph when possible so non-EUR markets can be compared sanely.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Any


FIAT_QUOTES = {"EUR", "USD", "GBP", "CHF", "CAD", "AUD", "JPY", "SGD"}
STABLE_QUOTES = {"USDC", "USDT", "EURC", "DAI", "PYUSD", "USDS"}


def quote_kind(asset: str) -> str:
    asset = str(asset or "").upper()
    if asset in FIAT_QUOTES:
        return "fiat"
    if asset in STABLE_QUOTES:
        return "stablecoin"
    return "crypto"


class MultiExchangeMarketUniverse:
    """Inventory and compare the complete Bitvavo/Coinbase spot universe."""

    def __init__(self, bitvavo, coinbase, config: dict[str, Any] | None = None) -> None:
        self.bitvavo = bitvavo
        self.coinbase = coinbase
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.coinbase_book_batch_size = max(
            1, min(100, int(self.config.get("coinbase_book_batch_size", 30)))
        )
        self.max_bridge_hops = max(1, min(4, int(self.config.get("max_bridge_hops", 3))))
        self.min_top_depth_eur = max(
            1.0, float(self.config.get("min_top_depth_eur", 25.0))
        )
        self.max_spread_bps = max(
            1.0, float(self.config.get("max_spread_bps", 50.0))
        )
        self._coinbase_cursor = 0
        self._coinbase_book_cache: dict[str, dict[str, float]] = {}
        self._bitvavo_rows: list[dict[str, Any]] = []
        self._coinbase_rows: list[dict[str, Any]] = []
        self._overlap: list[dict[str, Any]] = []
        self._summary: dict[str, Any] = {
            "enabled": self.enabled,
            "read_only": True,
            "live_orders_sent": False,
        }
        self.updated_at = 0.0
        self.error: str | None = None
        self.venue_errors: dict[str, str] = {}

    @staticmethod
    def _pair(market: str, base: str = "", quote: str = "") -> tuple[str, str]:
        base = str(base or "").upper().strip()
        quote = str(quote or "").upper().strip()
        if base and quote:
            return base, quote
        market = str(market or "").upper().strip()
        if "-" not in market:
            return "", ""
        first, second = market.rsplit("-", 1)
        return first, second

    @staticmethod
    def _market_graph(books: dict[str, dict[str, Any]]) -> dict[str, list[tuple[str, float]]]:
        graph: dict[str, list[tuple[str, float]]] = {}
        for market, book in books.items():
            if "-" not in market:
                continue
            base, quote = market.rsplit("-", 1)
            try:
                bid = float(book["bid"])
                ask = float(book["ask"])
            except (KeyError, TypeError, ValueError):
                continue
            mid = (bid + ask) / 2.0
            if mid <= 0 or not math.isfinite(mid):
                continue
            graph.setdefault(base, []).append((quote, mid))
            graph.setdefault(quote, []).append((base, 1.0 / mid))
        return graph

    @staticmethod
    def _bridge_rate(
        asset: str,
        graph: dict[str, list[tuple[str, float]]],
        max_hops: int,
    ) -> float | None:
        asset = str(asset or "").upper().strip()
        if not asset:
            return None
        if asset == "EUR":
            return 1.0
        queue: deque[tuple[str, float, int]] = deque([(asset, 1.0, 0)])
        visited = {asset}
        while queue:
            node, rate, hops = queue.popleft()
            if hops >= max_hops:
                continue
            for target, edge in graph.get(node, []):
                if target in visited:
                    continue
                next_rate = rate * edge
                if target == "EUR":
                    return next_rate
                visited.add(target)
                queue.append((target, next_rate, hops + 1))
        return None

    def _score(
        self,
        *,
        spread_bps: float | None,
        top_depth_eur: float | None,
        volume_24h_eur: float | None,
    ) -> float:
        spread_score = 0.0
        if spread_bps is not None:
            spread_score = max(
                0.0, min(100.0, 100.0 * (1.0 - spread_bps / self.max_spread_bps))
            )
        depth_score = 0.0
        if top_depth_eur is not None:
            depth_score = max(
                0.0, min(100.0, top_depth_eur / self.min_top_depth_eur * 100.0)
            )
        volume_score = 0.0
        if volume_24h_eur is not None and volume_24h_eur > 0:
            volume_score = max(
                0.0, min(100.0, math.log10(1.0 + volume_24h_eur) * 14.0)
            )
        return round(0.45 * spread_score + 0.35 * depth_score + 0.20 * volume_score, 2)

    def _read_bitvavo(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, list[tuple[str, float]]]]:
        market_rows = self.bitvavo.markets()
        books = self.bitvavo.ticker_books()
        graph = self._market_graph(books)
        rows: list[dict[str, Any]] = []

        for raw in market_rows:
            if not isinstance(raw, dict):
                continue
            market = str(raw.get("market") or "").upper().strip()
            base, quote = self._pair(
                market,
                str(raw.get("base") or ""),
                str(raw.get("quote") or ""),
            )
            if not market or not base or not quote:
                continue

            status = str(raw.get("status") or "").lower()
            book = books.get(market)
            mid = spread_bps = depth_quote = None
            if isinstance(book, dict):
                try:
                    bid = float(book["bid"])
                    ask = float(book["ask"])
                    bid_size = float(book["bid_size"])
                    ask_size = float(book["ask_size"])
                    mid = (bid + ask) / 2.0
                    spread_bps = (ask - bid) / mid * 10000.0 if mid > 0 else None
                    depth_quote = min(bid * bid_size, ask * ask_size)
                except (KeyError, TypeError, ValueError):
                    pass

            quote_to_eur = self._bridge_rate(quote, graph, self.max_bridge_hops)
            depth_eur = (
                depth_quote * quote_to_eur
                if depth_quote is not None and quote_to_eur is not None
                else None
            )
            row = {
                "venue": "bitvavo",
                "market": market,
                "base": base,
                "quote": quote,
                "quote_kind": quote_kind(quote),
                "pair_type": "crypto_crypto" if quote_kind(quote) != "fiat" else "crypto_fiat",
                "status": status,
                "tradable": status == "trading",
                "mid_quote": round(mid, 12) if mid is not None else None,
                "quote_to_eur": round(quote_to_eur, 12) if quote_to_eur is not None else None,
                "mid_eur": (
                    round(mid * quote_to_eur, 8)
                    if mid is not None and quote_to_eur is not None
                    else None
                ),
                "spread_bps": round(spread_bps, 4) if spread_bps is not None else None,
                "top_depth_quote": round(depth_quote, 8) if depth_quote is not None else None,
                "top_depth_eur": round(depth_eur, 2) if depth_eur is not None else None,
                "min_order_base": raw.get("minOrderInBaseAsset"),
                "min_order_quote": raw.get("minOrderInQuoteAsset"),
                "order_types": list(raw.get("orderTypes") or []),
                "live_execution_supported_now": quote_to_eur is not None and quote_to_eur > 0,
                "execution_note": (
                    "quote-aware EUR accounting available"
                    if quote_to_eur is not None and quote_to_eur > 0
                    else "blocked until an EUR bridge is available"
                ),
            }
            row["market_quality_score"] = self._score(
                spread_bps=row["spread_bps"],
                top_depth_eur=row["top_depth_eur"],
                volume_24h_eur=None,
            )
            rows.append(row)
        return rows, graph

    def _sample_coinbase_books(self, products: list[dict[str, object]]) -> None:
        tradable = [x for x in products if bool(x.get("tradable"))]
        if not tradable:
            return

        start = self._coinbase_cursor % len(tradable)
        batch = [
            tradable[(start + offset) % len(tradable)]
            for offset in range(min(self.coinbase_book_batch_size, len(tradable)))
        ]
        self._coinbase_cursor = (start + len(batch)) % len(tradable)

        for product in batch:
            product_id = str(product.get("product_id") or "")
            if not product_id:
                continue
            try:
                book = self.coinbase.top_of_book(product_id)
                self._coinbase_book_cache[product_id] = {
                    "bid": float(book.bid_price),
                    "ask": float(book.ask_price),
                    "bid_size": float(book.bid_size),
                    "ask_size": float(book.ask_size),
                    "observed_at": time.time(),
                }
            except Exception:
                # One unavailable product must not abort the catalogue refresh.
                continue

    def _read_coinbase(
        self,
        graph: dict[str, list[tuple[str, float]]],
    ) -> list[dict[str, Any]]:
        products = self.coinbase.list_spot_products()
        self._sample_coinbase_books(products)
        rows: list[dict[str, Any]] = []

        for product in products:
            market = str(product.get("product_id") or "").upper().strip()
            base, quote = self._pair(
                market,
                str(product.get("base") or ""),
                str(product.get("quote") or ""),
            )
            if not market or not base or not quote:
                continue

            cached = self._coinbase_book_cache.get(market)
            mid = spread_bps = depth_quote = None
            if cached:
                bid = float(cached["bid"])
                ask = float(cached["ask"])
                mid = (bid + ask) / 2.0
                spread_bps = (ask - bid) / mid * 10000.0 if mid > 0 else None
                depth_quote = min(
                    bid * float(cached["bid_size"]),
                    ask * float(cached["ask_size"]),
                )

            quote_to_eur = self._bridge_rate(quote, graph, self.max_bridge_hops)
            try:
                price = float(product.get("price") or 0.0)
                volume = float(product.get("volume_24h") or 0.0)
                volume_quote = price * volume if price > 0 and volume > 0 else None
            except (TypeError, ValueError):
                volume_quote = None

            volume_eur = (
                volume_quote * quote_to_eur
                if volume_quote is not None and quote_to_eur is not None
                else None
            )
            depth_eur = (
                depth_quote * quote_to_eur
                if depth_quote is not None and quote_to_eur is not None
                else None
            )
            row = {
                "venue": "coinbase",
                "market": market,
                "base": base,
                "quote": quote,
                "quote_kind": quote_kind(quote),
                "pair_type": "crypto_crypto" if quote_kind(quote) != "fiat" else "crypto_fiat",
                "status": "trading" if bool(product.get("tradable")) else "unavailable",
                "tradable": bool(product.get("tradable")),
                "mid_quote": round(mid, 12) if mid is not None else None,
                "quote_to_eur": round(quote_to_eur, 12) if quote_to_eur is not None else None,
                "mid_eur": (
                    round(mid * quote_to_eur, 8)
                    if mid is not None and quote_to_eur is not None
                    else None
                ),
                "spread_bps": round(spread_bps, 4) if spread_bps is not None else None,
                "top_depth_quote": round(depth_quote, 8) if depth_quote is not None else None,
                "top_depth_eur": round(depth_eur, 2) if depth_eur is not None else None,
                "volume_24h_eur": round(volume_eur, 2) if volume_eur is not None else None,
                "price_change_24h_pct": product.get("price_change_24h_pct"),
                "book_sampled": bool(cached),
                "book_age_seconds": (
                    round(time.time() - float(cached["observed_at"]), 2)
                    if cached
                    else None
                ),
                "live_execution_supported_now": False,
                "execution_note": "Coinbase universe is research/arbitrage-shadow only",
            }
            row["market_quality_score"] = self._score(
                spread_bps=row["spread_bps"],
                top_depth_eur=row["top_depth_eur"],
                volume_24h_eur=row["volume_24h_eur"],
            )
            rows.append(row)
        return rows

    @staticmethod
    def _build_overlap(
        bitvavo_rows: list[dict[str, Any]],
        coinbase_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        bv = {x["market"]: x for x in bitvavo_rows if x.get("tradable")}
        cb = {x["market"]: x for x in coinbase_rows if x.get("tradable")}
        rows: list[dict[str, Any]] = []
        for market in sorted(set(bv) & set(cb)):
            left = bv[market]
            right = cb[market]
            rows.append({
                "market": market,
                "base": left["base"],
                "quote": left["quote"],
                "pair_type": left["pair_type"],
                "bitvavo_quality_score": left.get("market_quality_score"),
                "coinbase_quality_score": right.get("market_quality_score"),
                "bitvavo_book": left.get("spread_bps") is not None,
                "coinbase_book": right.get("spread_bps") is not None,
            })
        return rows

    def refresh(self) -> None:
        if not self.enabled:
            return

        venue_errors: dict[str, str] = {}
        bitvavo_rows: list[dict[str, Any]] = []
        coinbase_rows: list[dict[str, Any]] = []
        graph: dict[str, list[tuple[str, float]]] = {}

        try:
            bitvavo_rows, graph = self._read_bitvavo()
        except Exception as exc:
            venue_errors["bitvavo"] = f"{type(exc).__name__}: {str(exc)[:160]}"

        try:
            coinbase_rows = self._read_coinbase(graph)
        except Exception as exc:
            venue_errors["coinbase"] = f"{type(exc).__name__}: {str(exc)[:160]}"

        self._bitvavo_rows = bitvavo_rows
        self._coinbase_rows = coinbase_rows
        self._overlap = self._build_overlap(bitvavo_rows, coinbase_rows)
        self.updated_at = time.time()
        self.venue_errors = venue_errors
        self.error = "; ".join(f"{k}={v}" for k, v in venue_errors.items()) or None
        self._summary = self._build_summary()

    def _build_summary(self) -> dict[str, Any]:
        bv = self._bitvavo_rows
        cb = self._coinbase_rows

        def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
            return {
                "all": len(rows),
                "tradable": sum(1 for x in rows if x.get("tradable")),
                "crypto_fiat": sum(1 for x in rows if x.get("pair_type") == "crypto_fiat"),
                "crypto_crypto": sum(1 for x in rows if x.get("pair_type") == "crypto_crypto"),
                "eur_quote": sum(1 for x in rows if x.get("quote") == "EUR"),
                "stablecoin_quote": sum(1 for x in rows if x.get("quote_kind") == "stablecoin"),
                "book_sampled": sum(1 for x in rows if x.get("spread_bps") is not None),
            }

        candidates = sorted(
            [x for x in bv + cb if x.get("tradable")],
            key=lambda x: float(x.get("market_quality_score") or 0.0),
            reverse=True,
        )[:25]
        return {
            "enabled": self.enabled,
            "read_only": True,
            "live_orders_sent": False,
            "updated_at": self.updated_at,
            "error": self.error,
            "venue_errors": dict(self.venue_errors),
            "bitvavo": counts(bv),
            "coinbase": counts(cb),
            "exact_cross_venue_overlap": len(self._overlap),
            "overlap_crypto_crypto": sum(
                1 for x in self._overlap if x.get("pair_type") == "crypto_crypto"
            ),
            "top_quality_candidates": candidates,
            "note": (
                "All spot pairs are inventoried, including crypto/crypto. "
                "Non-EUR pairs are valued to EUR through live bridge markets when possible. "
                "Market quality is discovery data, not an automatic trade signal."
            ),
        }

    def status(self) -> dict[str, Any]:
        return dict(self._summary)

    def markets(
        self,
        *,
        venue: str | None = None,
        pair_type: str | None = None,
        quote: str | None = None,
        tradable_only: bool = False,
        offset: int = 0,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows = self._bitvavo_rows + self._coinbase_rows
        if venue:
            rows = [x for x in rows if x.get("venue") == venue]
        if pair_type:
            rows = [x for x in rows if x.get("pair_type") == pair_type]
        if quote:
            rows = [x for x in rows if x.get("quote") == quote.upper()]
        if tradable_only:
            rows = [x for x in rows if x.get("tradable")]
        rows = sorted(
            rows,
            key=lambda x: (
                float(x.get("market_quality_score") or 0.0),
                str(x.get("market") or ""),
            ),
            reverse=True,
        )
        total = len(rows)
        offset = max(0, int(offset))
        limit = max(1, min(5000, int(limit)))
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "rows": rows[offset: offset + limit],
            "updated_at": self.updated_at,
            "error": self.error,
            "venue_errors": dict(self.venue_errors),
            "read_only": True,
            "live_orders_sent": False,
        }

    def overlaps(self, *, limit: int = 5000) -> dict[str, Any]:
        return {
            "total": len(self._overlap),
            "rows": self._overlap[: max(1, min(5000, int(limit)))],
            "updated_at": self.updated_at,
            "error": self.error,
            "venue_errors": dict(self.venue_errors),
            "read_only": True,
            "live_orders_sent": False,
        }
