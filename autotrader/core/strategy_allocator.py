"""Shared portfolio allocation guard for concurrent strategies.

This module does not send exchange requests.  It only decides whether a
strategy intent may proceed to the execution adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from autotrader.core.order_manager import Order


@dataclass(frozen=True)
class AllocationDecision:
    accepted: bool
    reason: str = "accepted"


@dataclass(frozen=True)
class StrategyAllocation:
    allocation_eur: Decimal
    max_order_eur: Decimal
    max_open_orders: int
    symbols: frozenset[str]
    exclusive_symbol: bool = True
    live_capable: bool = False


class StrategyAllocator:
    """Fail-closed budget and conflict guard shared by all strategies."""

    _NAME_MAP = {
        "market_maker": "MarketMaker",
        "arbitrage": "ArbitrageHunter",
        "grid": "GridRunner",
        "sniper": "SniperBot",
    }

    def __init__(self, config: dict) -> None:
        portfolio = config.get("portfolio", {}) or {}
        self.global_budget_eur = Decimal(str(portfolio.get("global_live_budget_eur", "50")))
        self.max_total_open_orders = max(1, int(portfolio.get("max_total_open_orders", 4)))
        self._allocations: dict[str, StrategyAllocation] = {}

        for key, raw in (config.get("strategies", {}) or {}).items():
            name = self._NAME_MAP.get(key, key)
            cfg = raw or {}
            symbol = str(cfg.get("symbol", "")).upper().strip()
            symbols = frozenset({symbol}) if symbol else frozenset()
            self._allocations[name] = StrategyAllocation(
                allocation_eur=Decimal(str(cfg.get("allocation_eur", "0"))),
                max_order_eur=Decimal(str(cfg.get("max_order_eur", "10"))),
                max_open_orders=max(1, int(cfg.get("max_open_orders", 1))),
                symbols=symbols,
                exclusive_symbol=bool(cfg.get("exclusive_symbol", True)),
                live_capable=bool(cfg.get("live_capable", False)),
            )

    @staticmethod
    def _notional(order: Order, fallback_price: Decimal) -> Decimal:
        price = Decimal(str(order.price)) if order.price is not None else fallback_price
        return Decimal(str(order.quantity)) * price

    def allocation_for(self, strategy: str) -> StrategyAllocation | None:
        return self._allocations.get(strategy)

    def evaluate(
        self,
        order: Order,
        active_orders: Iterable[Order],
        *,
        observed_price: Decimal,
    ) -> AllocationDecision:
        allocation = self._allocations.get(order.strategy)
        if allocation is None:
            return AllocationDecision(False, "strategy allocation is not configured")
        if not allocation.live_capable:
            return AllocationDecision(False, "strategy is not approved for live execution")
        if allocation.allocation_eur <= 0:
            return AllocationDecision(False, "strategy allocation is zero")
        if allocation.symbols and order.symbol.upper() not in allocation.symbols:
            return AllocationDecision(False, "symbol is outside strategy allocation")

        active = [o for o in active_orders if o.order_id != order.order_id and o.is_active]
        if len(active) >= self.max_total_open_orders:
            return AllocationDecision(False, "global open-order limit reached")

        own = [o for o in active if o.strategy == order.strategy]
        if len(own) >= allocation.max_open_orders:
            return AllocationDecision(False, "strategy open-order limit reached")

        new_notional = self._notional(order, observed_price)
        if new_notional <= 0:
            return AllocationDecision(False, "order notional must be positive")
        if new_notional > allocation.max_order_eur:
            return AllocationDecision(False, "strategy per-order allocation exceeded")

        own_notional = sum(
            (self._notional(o, observed_price) for o in own),
            Decimal("0"),
        )
        if own_notional + new_notional > allocation.allocation_eur:
            return AllocationDecision(False, "strategy allocation exceeded")

        total_notional = sum(
            (self._notional(o, observed_price) for o in active),
            Decimal("0"),
        )
        if total_notional + new_notional > self.global_budget_eur:
            return AllocationDecision(False, "global live budget exceeded")

        if allocation.exclusive_symbol:
            for other in active:
                if (
                    other.strategy != order.strategy
                    and other.symbol.upper() == order.symbol.upper()
                ):
                    return AllocationDecision(False, "symbol is already owned by another strategy")

        return AllocationDecision(True)
