"""Read-only live preflight checks for Bitvavo strategies."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any, Iterable


_ORDER_TYPE_BY_STRATEGY = {
    "MarketMaker": "limit",
    "GridRunner": "limit",
    "SniperBot": "market",
}


def _planned_amount(config: dict[str, Any], price: Decimal) -> Decimal:
    order_value = Decimal(str(config.get("order_value_eur", "0") or "0"))
    if order_value > 0 and price > 0:
        return order_value / price
    return Decimal(str(config.get("order_size", "0") or "0"))


def _round_amount_down(amount: Decimal, quantity_decimals: int) -> Decimal:
    quantum = Decimal(1).scaleb(-quantity_decimals)
    return amount.quantize(quantum, rounding=ROUND_DOWN)


def validate_bitvavo_live_strategies(
    strategies: Iterable[Any],
    adapter: Any,
) -> dict[str, Any]:
    """Validate configured live strategies against current Bitvavo market rules.

    This function only performs read-only market and open-order requests.
    """
    rows: list[dict[str, Any]] = []
    total_open_orders = 0

    for strategy in strategies:
        config = getattr(strategy, "_config", {}) or {}
        if not bool(getattr(strategy, "is_enabled", False)):
            continue
        if not bool(config.get("live_capable", False)):
            continue
        if str(config.get("exchange", "bitvavo")).lower() != "bitvavo":
            continue

        strategy_name = str(getattr(strategy, "name", type(strategy).__name__))
        market = str(config.get("symbol", "")).upper().strip()
        order_type = _ORDER_TYPE_BY_STRATEGY.get(strategy_name)

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
            amount = _round_amount_down(_planned_amount(config, price), quantity_decimals)
            notional = amount * price

            if status != "trading":
                row["errors"].append("market_not_trading")
            if order_type not in supported:
                row["errors"].append("order_type_not_supported")
            if amount <= 0:
                row["errors"].append("planned_amount_non_positive")
            if amount < min_base:
                row["errors"].append("below_min_base")
            if notional < min_quote:
                row["errors"].append("below_min_quote")

            max_order_eur = Decimal(str(config.get("max_order_eur", "0") or "0"))
            allocation_eur = Decimal(str(config.get("allocation_eur", "0") or "0"))
            if max_order_eur > 0 and notional > max_order_eur:
                row["errors"].append("above_strategy_max_order")
            if allocation_eur > 0 and notional > allocation_eur:
                row["errors"].append("above_strategy_allocation")

            open_count = len(adapter.open_orders(market))
            total_open_orders += open_count
            if open_count:
                row["errors"].append("exchange_open_orders_present")

            row.update({
                "status": status,
                "min_order_base": str(min_base),
                "min_order_quote": str(min_quote),
                "quantity_decimals": quantity_decimals,
                "tick_size": str(tick_size),
                "planned_amount": str(amount),
                "planned_notional_eur": str(notional.quantize(Decimal("0.0001"))),
                "open_order_count": open_count,
            })
            row["passed"] = not row["errors"]
        except Exception as exc:
            row["errors"].append(getattr(exc, "category", type(exc).__name__))
        rows.append(row)

    return {
        "passed": bool(rows) and all(row.get("passed") for row in rows),
        "open_orders_clear": total_open_orders == 0,
        "total_open_orders": total_open_orders,
        "strategies": rows,
    }
