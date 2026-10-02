"""Shared portfolio allocation guard for concurrent strategies.

This module does not send exchange requests.  It only decides whether a
strategy intent may proceed to the execution adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from autotrader.core.order_manager import Order, OrderSide


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
        "grid_eth": "GridRunnerETH",
        "sniper": "SniperBot",
    }

    def __init__(self, config: dict) -> None:
        portfolio = config.get("portfolio", {}) or {}
        self.configured_global_budget_eur = Decimal(
            str(portfolio.get("global_live_budget_eur", "50"))
        )
        self.global_budget_eur = self.configured_global_budget_eur
        self.configured_max_total_open_orders = max(
            1, int(portfolio.get("max_total_open_orders", 4))
        )
        self.max_total_open_orders = self.configured_max_total_open_orders
        self._allocations: dict[str, StrategyAllocation] = {}
        self._base_allocations: dict[str, StrategyAllocation] = {}

        autonomous_markets = (
            (config.get("autonomous_execution", {}) or {}).get("strategy_markets", {}) or {}
        )
        for key, raw in (config.get("strategies", {}) or {}).items():
            name = self._NAME_MAP.get(key, key)
            cfg = raw or {}
            symbol = str(cfg.get("symbol", "")).upper().strip()
            allowed = [
                str(x).upper().strip()
                for x in (autonomous_markets.get(key) or [])
                if str(x).strip()
            ]
            if symbol and symbol not in allowed:
                allowed.append(symbol)
            symbols = frozenset(allowed or ([symbol] if symbol else []))
            allocation = StrategyAllocation(
                allocation_eur=Decimal(str(cfg.get("allocation_eur", "0"))),
                max_order_eur=Decimal(str(cfg.get("max_order_eur", "10"))),
                max_open_orders=max(1, int(cfg.get("max_open_orders", 1))),
                symbols=symbols,
                exclusive_symbol=bool(cfg.get("exclusive_symbol", True)),
                live_capable=bool(cfg.get("live_capable", False)),
            )
            self._allocations[name] = allocation
            self._base_allocations[name] = allocation

    def apply_growth_policy(self, policy: dict) -> dict[str, object]:
        """Apply a NAV-derived portfolio envelope without widening eligibility."""
        budget = Decimal(
            str(max(0.0, float(policy.get("effective_live_budget_eur", 0.0))))
        )
        max_order = Decimal(
            str(max(0.0, float(policy.get("effective_max_order_eur", 0.0))))
        )
        max_open_orders = max(1, int(policy.get("max_open_orders", 1)))
        live_bases = {
            name: allocation
            for name, allocation in self._base_allocations.items()
            if allocation.live_capable and allocation.allocation_eur > 0
        }
        weight_total = sum(
            (allocation.allocation_eur for allocation in live_bases.values()),
            Decimal("0"),
        )
        updated: dict[str, StrategyAllocation] = {}
        for name, base in self._base_allocations.items():
            if (
                not base.live_capable
                or base.allocation_eur <= 0
                or weight_total <= 0
                or budget <= 0
            ):
                effective_allocation = (
                    Decimal("0") if base.live_capable else base.allocation_eur
                )
                effective_order = (
                    Decimal("0") if base.live_capable else base.max_order_eur
                )
            else:
                share = base.allocation_eur / weight_total
                effective_allocation = budget * share
                effective_order = min(max_order, effective_allocation)
            updated[name] = StrategyAllocation(
                allocation_eur=effective_allocation,
                max_order_eur=effective_order,
                max_open_orders=base.max_open_orders,
                symbols=base.symbols,
                exclusive_symbol=base.exclusive_symbol,
                live_capable=base.live_capable,
            )
        self._allocations = updated
        self.global_budget_eur = budget
        self.max_total_open_orders = max_open_orders
        return self.status()

    def status(self) -> dict[str, object]:
        return {
            "configured_global_budget_eur": float(self.configured_global_budget_eur),
            "effective_global_budget_eur": float(self.global_budget_eur),
            "configured_max_total_open_orders": self.configured_max_total_open_orders,
            "effective_max_total_open_orders": self.max_total_open_orders,
            "allocations": {
                name: {
                    "allocation_eur": float(allocation.allocation_eur),
                    "max_order_eur": float(allocation.max_order_eur),
                    "max_open_orders": allocation.max_open_orders,
                    "live_capable": allocation.live_capable,
                }
                for name, allocation in sorted(self._allocations.items())
            },
        }

    @staticmethod
    def _notional(order: Order, fallback_price: Decimal | None = None) -> Decimal | None:
        """Value an order only with its own price, except for the new candidate."""
        if order.price is not None:
            price = Decimal(str(order.price))
        elif fallback_price is not None:
            price = fallback_price
        else:
            return None
        notional = Decimal(str(order.quantity)) * price
        return notional if notional.is_finite() and notional > 0 else None

    def allocation_for(self, strategy: str) -> StrategyAllocation | None:
        return self._allocations.get(strategy)

    def max_entry_notional(
        self,
        order: Order,
        active_orders: Iterable[Order],
    ) -> Decimal:
        """Return remaining BUY capacity under strategy and portfolio caps.

        This is used to resize an otherwise valid entry instead of rejecting it
        when a small rounding/price difference would exceed an allocation cap.
        Unknown active notionals fail closed by returning zero capacity.
        """
        allocation = self._allocations.get(order.strategy)
        if allocation is None or not allocation.live_capable or allocation.allocation_eur <= 0:
            return Decimal("0")

        active = [o for o in active_orders if o.order_id != order.order_id and o.is_active]
        own = [o for o in active if o.strategy == order.strategy]
        own_values = [self._notional(o) for o in own]
        active_values = [self._notional(o) for o in active]
        if any(value is None for value in own_values) or any(value is None for value in active_values):
            return Decimal("0")

        own_notional = sum((value for value in own_values if value is not None), Decimal("0"))
        total_notional = sum((value for value in active_values if value is not None), Decimal("0"))
        return max(
            Decimal("0"),
            min(
                allocation.max_order_eur,
                allocation.allocation_eur - own_notional,
                self.global_budget_eur - total_notional,
            ),
        )

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
        if (
            allocation.symbols
            and "*" not in allocation.symbols
            and order.symbol.upper() not in allocation.symbols
        ):
            return AllocationDecision(False, "symbol is outside strategy allocation")

        active = [o for o in active_orders if o.order_id != order.order_id and o.is_active]
        risk_reducing = order.side is OrderSide.SELL
        if not risk_reducing and len(active) >= self.max_total_open_orders:
            return AllocationDecision(False, "global open-order limit reached")

        own = [o for o in active if o.strategy == order.strategy]
        if len(own) >= allocation.max_open_orders:
            return AllocationDecision(False, "strategy open-order limit reached")

        new_notional = self._notional(order, observed_price)
        if new_notional is None:
            return AllocationDecision(False, "order notional must be positive")

        # Existing inventory exits reduce risk and must not be trapped behind
        # entry budget caps. Exchange rules, ownership and the execution gateway
        # still validate the actual order before it can be sent.
        if not risk_reducing:
            if new_notional > allocation.max_order_eur:
                return AllocationDecision(False, "strategy per-order allocation exceeded")

            own_values = [self._notional(o) for o in own]
            if any(value is None for value in own_values):
                return AllocationDecision(False, "active strategy order notional is unknown")
            own_notional = sum((value for value in own_values if value is not None), Decimal("0"))
            if own_notional + new_notional > allocation.allocation_eur:
                return AllocationDecision(False, "strategy allocation exceeded")

            active_values = [self._notional(o) for o in active]
            if any(value is None for value in active_values):
                return AllocationDecision(False, "active portfolio order notional is unknown")
            total_notional = sum((value for value in active_values if value is not None), Decimal("0"))
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
