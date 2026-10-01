"""Read-only live preflight checks for Bitvavo strategies."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any, Iterable


_ORDER_TYPE_BY_STRATEGY = {
    "MarketMaker": "limit",
    "SniperBot": "market",
}

_TERMINAL_ORDER_STATES = {
    "filled", "canceled", "cancelled", "rejected", "error", "expired", "shadow", "blocked",
}


def _order_type_for_strategy(name: str) -> str | None:
    if name.startswith("GridRunner"):
        return "limit"
    return _ORDER_TYPE_BY_STRATEGY.get(name)


def _planned_amount(
    config: dict[str, Any],
    price: Decimal,
    quote_to_eur: Decimal,
) -> Decimal:
    order_value = Decimal(str(config.get("order_value_eur", "0") or "0"))
    if order_value > 0 and price > 0 and quote_to_eur > 0:
        return order_value / quote_to_eur / price
    return Decimal(str(config.get("order_size", "0") or "0"))


def _round_amount_down(amount: Decimal, quantity_decimals: int) -> Decimal:
    quantum = Decimal(1).scaleb(-quantity_decimals)
    return amount.quantize(quantum, rounding=ROUND_DOWN)


def _managed_exchange_order(order: dict[str, Any], market: str, journal: Any) -> bool:
    """Return True only when an exchange-open order matches a durable bot order."""
    if journal is None or not hasattr(journal, "get"):
        return False
    client_id = str(order.get("clientOrderId") or "").strip()
    if not client_id:
        return False
    try:
        local = journal.get(client_id)
    except Exception:
        return False
    if not isinstance(local, dict):
        return False
    if str(local.get("market") or "").upper() != market.upper():
        return False
    if str(local.get("status") or "").lower() in _TERMINAL_ORDER_STATES:
        return False
    exchange_order_id = str(order.get("orderId") or "").strip()
    local_exchange_order_id = str(local.get("exchange_order_id") or "").strip()
    if exchange_order_id and local_exchange_order_id and exchange_order_id != local_exchange_order_id:
        return False
    exchange_side = str(order.get("side") or "").lower().strip()
    local_side = str(local.get("side") or "").lower().strip()
    if exchange_side and local_side and exchange_side != local_side:
        return False
    return True


def validate_bitvavo_live_strategies(
    strategies: Iterable[Any],
    adapter: Any,
) -> dict[str, Any]:
    """Validate live strategies and prove restart-resume ownership of open orders.

    The function is read-only. Existing exchange orders do not automatically
    block a restart resume when every open order can be matched to the durable
    local journal and every nonterminal journal order is still open at Bitvavo.
    Unknown/manual orders remain fail-closed.
    """
    strategy_list = list(strategies)
    eligible: list[tuple[Any, dict[str, Any], str, str, str | None]] = []
    active_markets: set[str] = set()

    for strategy in strategy_list:
        config = getattr(strategy, "_config", {}) or {}
        if not bool(getattr(strategy, "is_enabled", False)):
            continue
        if not bool(config.get("live_capable", False)):
            continue
        if str(config.get("exchange", "bitvavo")).lower() != "bitvavo":
            continue
        strategy_name = str(getattr(strategy, "name", type(strategy).__name__))
        market = str(config.get("symbol", "")).upper().strip()
        order_type = _order_type_for_strategy(strategy_name)
        eligible.append((strategy, config, strategy_name, market, order_type))
        if market:
            active_markets.add(market)

    journal = getattr(adapter, "journal", None)
    journal_inflight: list[dict[str, Any]] = []
    journal_check_error: str | None = None
    if journal is not None and hasattr(journal, "inflight"):
        try:
            journal_inflight = list(journal.inflight())
        except Exception as exc:
            journal_check_error = getattr(exc, "category", type(exc).__name__)

    markets_to_check = set(active_markets)
    for item in journal_inflight:
        market = str(item.get("market") or "").upper().strip()
        if market:
            markets_to_check.add(market)

    open_orders_by_market: dict[str, list[dict[str, Any]]] = {}
    open_order_check_errors: dict[str, str] = {}
    for market in sorted(markets_to_check):
        try:
            open_orders_by_market[market] = list(adapter.open_orders(market))
        except Exception as exc:
            open_order_check_errors[market] = getattr(exc, "category", type(exc).__name__)
            open_orders_by_market[market] = []

    managed_client_ids: set[str] = set()
    managed_by_market: dict[str, int] = {}
    unmanaged_by_market: dict[str, int] = {}
    total_open_orders = 0
    managed_open_order_count = 0
    unmanaged_open_order_count = 0

    for market, orders in open_orders_by_market.items():
        managed_here = 0
        unmanaged_here = 0
        for order in orders:
            total_open_orders += 1
            if _managed_exchange_order(order, market, journal):
                managed_here += 1
                managed_open_order_count += 1
                client_id = str(order.get("clientOrderId") or "").strip()
                if client_id:
                    managed_client_ids.add(client_id)
            else:
                unmanaged_here += 1
                unmanaged_open_order_count += 1
        managed_by_market[market] = managed_here
        unmanaged_by_market[market] = unmanaged_here

    unmatched_journal = []
    for item in journal_inflight:
        client_id = str(item.get("client_order_id") or "").strip()
        if not client_id or client_id not in managed_client_ids:
            unmatched_journal.append(item)

    exchange_open_orders_safe = (
        not open_order_check_errors
        and unmanaged_open_order_count == 0
    )
    journal_inflight_safe = (
        journal_check_error is None
        and len(unmatched_journal) == 0
    )
    resume_safe = exchange_open_orders_safe and journal_inflight_safe

    rows: list[dict[str, Any]] = []
    for _strategy, config, strategy_name, market, order_type in eligible:
        row: dict[str, Any] = {
            "strategy": strategy_name,
            "market": market,
            "order_type": order_type,
            "passed": False,
            "errors": [],
        }

        if not market:
            row["errors"].append("market_missing")
            rows.append(row)
            continue
        if not order_type:
            row["errors"].append("unsupported_strategy_order_type")
            rows.append(row)
            continue

        try:
            rules_rows = adapter.markets(market)
            if not rules_rows:
                row["errors"].append("market_not_found")
                rows.append(row)
                continue
            rules = rules_rows[0]
            status = str(rules.get("status") or "").lower()
            supported = {str(item) for item in (rules.get("orderTypes") or [])}
            quantity_decimals = int(rules.get("quantityDecimals", 18))
            min_base = Decimal(str(rules.get("minOrderInBaseAsset", "0") or "0"))
            min_quote = Decimal(str(rules.get("minOrderInQuoteAsset", "0") or "0"))
            tick_size = Decimal(str(rules.get("tickSize", "0") or "0"))
            price = Decimal(str(adapter.ticker_price(market)))
            quote = market.rsplit("-", 1)[1] if "-" in market else ""
            if quote == "EUR":
                quote_to_eur = Decimal("1")
            elif hasattr(adapter, "quote_to_eur"):
                quote_to_eur = Decimal(str(adapter.quote_to_eur(market)))
            else:
                quote_to_eur = Decimal("0")
            if quote_to_eur <= 0 or not quote_to_eur.is_finite():
                row["errors"].append("quote_to_eur_unavailable")
                rows.append(row)
                continue
            amount = _round_amount_down(
                _planned_amount(config, price, quote_to_eur),
                quantity_decimals,
            )
            notional_quote = amount * price
            notional_eur = notional_quote * quote_to_eur

            if status != "trading":
                row["errors"].append("market_not_trading")
            if order_type not in supported:
                row["errors"].append("order_type_not_supported")
            if amount <= 0:
                row["errors"].append("planned_amount_non_positive")
            if amount < min_base:
                row["errors"].append("below_min_base")
            if notional_quote < min_quote:
                row["errors"].append("below_min_quote")

            max_order_eur = Decimal(str(config.get("max_order_eur", "0") or "0"))
            allocation_eur = Decimal(str(config.get("allocation_eur", "0") or "0"))
            if max_order_eur > 0 and notional_eur > max_order_eur:
                row["errors"].append("above_strategy_max_order")
            if allocation_eur > 0 and notional_eur > allocation_eur:
                row["errors"].append("above_strategy_allocation")

            if market in open_order_check_errors:
                row["errors"].append("open_orders_check_failed")
            if unmanaged_by_market.get(market, 0) > 0:
                row["errors"].append("unmanaged_exchange_open_orders_present")

            open_count = len(open_orders_by_market.get(market, []))
            row.update({
                "status": status,
                "min_order_base": str(min_base),
                "min_order_quote": str(min_quote),
                "quantity_decimals": quantity_decimals,
                "tick_size": str(tick_size),
                "planned_amount": str(amount),
                "quote_to_eur": str(quote_to_eur),
                "planned_notional_quote": str(notional_quote),
                "planned_notional_eur": str(notional_eur.quantize(Decimal("0.0001"))),
                "open_order_count": open_count,
                "managed_open_order_count": managed_by_market.get(market, 0),
                "unmanaged_open_order_count": unmanaged_by_market.get(market, 0),
            })
            row["passed"] = not row["errors"]
        except Exception as exc:
            row["errors"].append(getattr(exc, "category", type(exc).__name__))
        rows.append(row)

    return {
        "passed": bool(rows) and all(row.get("passed") for row in rows) and resume_safe,
        "open_orders_clear": total_open_orders == 0,
        "exchange_open_orders_safe": exchange_open_orders_safe,
        "journal_inflight_safe": journal_inflight_safe,
        "resume_safe": resume_safe,
        "total_open_orders": total_open_orders,
        "managed_open_order_count": managed_open_order_count,
        "unmanaged_open_order_count": unmanaged_open_order_count,
        "journal_inflight_count": len(journal_inflight),
        "unmatched_journal_inflight_count": len(unmatched_journal),
        "journal_check_error": journal_check_error,
        "open_order_check_errors": open_order_check_errors,
        "strategies": rows,
    }
