"""Shared portfolio allocation guard for concurrent strategies.

This module does not send exchange requests. It only decides whether a
strategy intent may proceed to the execution adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
    """Fail-closed budget and conflict guard shared by all strategies.

    When portfolio.dynamic_with_verified_nav is enabled, the allocator
    scales its deployable budget from the latest verified portfolio NAV.
    It never spends the configured cash reserve and it never makes a
    non-live-capable strategy live.
    """

    _NAME_MAP = {
        "market_maker": "MarketMaker",
        "arbitrage": "ArbitrageHunter",
        "grid": "GridRunner",
        "grid_eth": "GridRunnerETH",
        "sniper": "SniperBot",
        "shadow_canary": "ShadowCanary",
    }

    def __init__(self, config: dict) -> None:
        portfolio = config.get("portfolio", {}) or {}
        configured_budget = Decimal(str(portfolio.get("global_live_budget_eur", "50")))
        self._configured_global_budget_eur = max(Decimal("0"), configured_budget)
        self._dynamic_with_verified_nav = bool(
            portfolio.get("dynamic_with_verified_nav", False)
        )
        self._initial_live_capital_eur = max(
            Decimal("0.01"),
            Decimal(
                str(
                    portfolio.get(
                        "initial_live_capital_eur",
                        self._configured_global_budget_eur or Decimal("50"),
                    )
                )
            ),
        )
        self._max_deployable_pct = max(
            Decimal("0"),
            min(Decimal("100"), Decimal(str(portfolio.get("max_deployable_pct", "100")))),
        )
        self._min_cash_reserve_pct = max(
            Decimal("0"),
            min(Decimal("99.99"), Decimal(str(portfolio.get("min_cash_reserve_pct", "0")))),
        )
        self._max_deployable_pct = min(
            self._max_deployable_pct,
            Decimal("100") - self._min_cash_reserve_pct,
        )
        self._verified_nav_eur: Decimal | None = (
            self._initial_live_capital_eur if self._dynamic_with_verified_nav else None
        )
        self.max_total_open_orders = max(1, int(portfolio.get("max_total_open_orders", 4)))
        self._allocations: dict[str, StrategyAllocation] = {}

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
            self._allocations[name] = StrategyAllocation(
                allocation_eur=Decimal(str(cfg.get("allocation_eur", "0"))),
                max_order_eur=Decimal(str(cfg.get("max_order_eur", "10"))),
                max_open_orders=max(1, int(cfg.get("max_open_orders", 1))),
                symbols=symbols,
                exclusive_symbol=bool(cfg.get("exclusive_symbol", True)),
                live_capable=bool(cfg.get("live_capable", False)),
            )

    @property
    def global_budget_eur(self) -> Decimal:
        if not self._dynamic_with_verified_nav:
            return self._configured_global_budget_eur
        nav = self._verified_nav_eur or self._initial_live_capital_eur
        return max(
            Decimal("0"),
            nav * self._max_deployable_pct / Decimal("100"),
        )

    def set_verified_nav(self, nav_eur: float | Decimal) -> bool:
        """Update dynamic budgets from a positive verified NAV snapshot."""
        if not self._dynamic_with_verified_nav:
            return False
        try:
            nav = Decimal(str(nav_eur))
        except (InvalidOperation, TypeError, ValueError):
            return False
        if not nav.is_finite() or nav <= 0:
            return False
        self._verified_nav_eur = nav
        return True

    def capital_status(self) -> dict[str, object]:
        nav = self._verified_nav_eur or self._initial_live_capital_eur
        budget = self.global_budget_eur
        return {
            "dynamic_with_verified_nav": self._dynamic_with_verified_nav,
            "managed_nav_eur": float(nav),
            "deployable_budget_eur": float(budget),
            "cash_reserve_eur": float(max(Decimal("0"), nav - budget)),
            "max_deployable_pct": float(self._max_deployable_pct),
            "min_cash_reserve_pct": float(self._min_cash_reserve_pct),
        }

    def _effective_allocation(self, strategy: str) -> StrategyAllocation | None:
        base = self._allocations.get(strategy)
        if base is None or not self._dynamic_with_verified_nav or not base.live_capable:
            return base

        live_bases = [
            row.allocation_eur
            for row in self._allocations.values()
            if row.live_capable and row.allocation_eur > 0
        ]
        total_base = sum(live_bases, Decimal("0"))
        if total_base <= 0 or base.allocation_eur <= 0:
            return StrategyAllocation(
                allocation_eur=Decimal("0"),
                max_order_eur=Decimal("0"),
                max_open_orders=base.max_open_orders,
                symbols=base.symbols,
                exclusive_symbol=base.exclusive_symbol,
                live_capable=base.live_capable,
            )

        allocation = self.global_budget_eur * base.allocation_eur / total_base
        nav = self._verified_nav_eur or self._initial_live_capital_eur
        # FundRiskEngine already applies the hard NAV-relative position cap.
        # Do not shrink the strategy max-order a second time when live NAV is
        # below the configured seed capital; that can push otherwise legal
        # small-account orders below the venue minimum. Keep the configured
        # max-order as the floor for allocator sizing, while still allowing it
        # to scale up with NAV growth. The final order remains bounded by the
        # proportional allocation and the fund risk gate.
        scale = max(Decimal("1"), nav / self._initial_live_capital_eur)
        dynamic_max_order = min(allocation, max(Decimal("0"), base.max_order_eur * scale))
        return StrategyAllocation(
            allocation_eur=allocation,
            max_order_eur=dynamic_max_order,
            max_open_orders=base.max_open_orders,
            symbols=base.symbols,
            exclusive_symbol=base.exclusive_symbol,
            live_capable=base.live_capable,
        )

    @staticmethod
    def _notional(order: Order, fallback_price: Decimal | None = None) -> Decimal | None:
        """Value an order only with its own price, except for the new candidate."""
        if order.price is not None:
            price = Decimal(str(order.price))
        elif fallback_price is not None:
            price = fallback_price
        else:
            return None
        quote_to_eur = Decimal(str(getattr(order, "quote_to_eur", 1.0) or 0.0))
        if not quote_to_eur.is_finite() or quote_to_eur <= 0:
            return None
        notional = Decimal(str(order.quantity)) * price * quote_to_eur
        return notional if notional.is_finite() and notional > 0 else None

    def allocation_for(self, strategy: str) -> StrategyAllocation | None:
        return self._effective_allocation(strategy)

    def max_entry_notional(
        self,
        order: Order,
        active_orders: Iterable[Order],
    ) -> Decimal:
        """Return remaining BUY capacity under strategy and portfolio caps."""
        allocation = self.allocation_for(order.strategy)
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
        allocation = self.allocation_for(order.strategy)
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
