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
        self.global_budget_eur = Decimal(str(portfolio.get("global_live_budget_eur", "50")))
        self.bootstrap_budget_eur = self.global_budget_eur
        self.dynamic_nav_scaling = bool(portfolio.get("dynamic_nav_scaling", True))
        self.max_total_open_orders = max(1, int(portfolio.get("max_total_open_orders", 4)))
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

    def sync_verified_fund_budget(
        self,
        *,
        nav_eur: float,
        max_single_trade_pct: float,
        max_gross_exposure_pct: float,
    ) -> dict[str, str]:
        """Scale live allocation caps from verified NAV and effective fund limits."""
        if not self.dynamic_nav_scaling:
            return {
                "scaled": "false",
                "reason": "dynamic_nav_scaling_disabled",
                "global_budget_eur": str(self.global_budget_eur),
            }
        nav = Decimal(str(max(0.0, float(nav_eur))))
        single_pct = Decimal(str(max(0.0, float(max_single_trade_pct))))
        gross_pct = Decimal(str(max(0.0, float(max_gross_exposure_pct))))
        if nav <= 0 or single_pct <= 0 or gross_pct <= 0:
            return {
                "scaled": "false",
                "reason": "invalid_verified_nav_or_limits",
                "global_budget_eur": str(self.global_budget_eur),
            }

        deployable = nav * gross_pct / Decimal("100")
        single_cap = nav * single_pct / Decimal("100")
        live_base_total = sum(
            (
                row.allocation_eur
                for row in self._base_allocations.values()
                if row.live_capable and row.allocation_eur > 0
            ),
            Decimal("0"),
        )
        if live_base_total <= 0:
            return {
                "scaled": "false",
                "reason": "no_live_allocations",
                "global_budget_eur": str(self.global_budget_eur),
            }

        updated: dict[str, StrategyAllocation] = {}
        for name, base in self._base_allocations.items():
            if not base.live_capable or base.allocation_eur <= 0:
                updated[name] = base
                continue
            share = base.allocation_eur / live_base_total
            allocation_eur = deployable * share
            order_ratio = (
                min(Decimal("1"), base.max_order_eur / base.allocation_eur)
                if base.allocation_eur > 0
                else Decimal("0")
            )
            max_order_eur = min(single_cap, allocation_eur * order_ratio)
            updated[name] = StrategyAllocation(
                allocation_eur=allocation_eur,
                max_order_eur=max_order_eur,
                max_open_orders=base.max_open_orders,
                symbols=base.symbols,
                exclusive_symbol=base.exclusive_symbol,
                live_capable=base.live_capable,
            )

        self.global_budget_eur = deployable
        self._allocations = updated
        return {
            "scaled": "true",
            "reason": "verified_nav",
            "global_budget_eur": str(self.global_budget_eur),
            "single_trade_cap_eur": str(single_cap),
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
