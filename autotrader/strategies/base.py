"""Abstract base class every strategy must inherit from."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autotrader.core.order_manager import Order, OrderManager
    from autotrader.core.risk_manager import RiskManager
    from autotrader.core.profit_engine import ProfitEngine


class BaseStrategy(ABC):
    name: str = "base"

    def __init__(self,
                 order_manager: "OrderManager",
                 risk_manager: "RiskManager",
                 profit_engine: "ProfitEngine",
                 config: dict) -> None:
        self._om = order_manager
        self._rm = risk_manager
        self._pe = profit_engine
        self._config = config
        self._running = False
        self._enabled = bool(config.get("enabled", True))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self._enabled:
            self._running = False
            return
        self._running = True
        self.on_start()

    def stop(self) -> None:
        self._running = False
        self.on_stop()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Exchange minimum / dust helpers
    # ------------------------------------------------------------------

    def quote_to_eur_rate(self) -> float:
        symbol = str(self._config.get("symbol", "")).upper()
        if symbol.endswith("-EUR"):
            return 1.0
        try:
            rate = float(self._config.get("_quote_to_eur", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return rate if rate > 0 else 0.0

    def quote_notional_to_eur(self, amount_quote: float) -> float:
        rate = self.quote_to_eur_rate()
        return max(0.0, float(amount_quote or 0.0)) * rate if rate > 0 else 0.0

    def eur_to_quote_notional(self, amount_eur: float) -> float:
        rate = self.quote_to_eur_rate()
        return max(0.0, float(amount_eur or 0.0)) / rate if rate > 0 else 0.0

    def minimum_tradable_base(self, price: float | None = None) -> float:
        """Return the live minimum base quantity required for a valid order.

        Bitvavo enforces both a base-asset minimum and a quote-asset minimum.
        The latter changes with price, so using only minOrderInBaseAsset can
        incorrectly classify small residual inventory as sellable.
        """
        cfg = self._config
        min_base = max(0.0, float(cfg.get("_min_order_base", 0.0) or 0.0))
        min_quote = max(0.0, float(cfg.get("_min_order_quote", 0.0) or 0.0))
        px = max(
            0.0,
            float(
                price
                if price is not None
                else cfg.get("_current_price", cfg.get("_mid_price", 0.0))
                or 0.0
            ),
        )
        if min_quote > 0 and px > 0:
            min_base = max(min_base, min_quote / px)
        # Small precision buffer prevents connector ROUND_DOWN from moving an
        # amount that looked just-valid back below the exchange minimum.
        return min_base * 1.001 if min_base > 0 else 0.0

    def minimum_tradable_notional(self, price: float | None = None) -> float:
        """Return the exchange minimum order value in EUR."""
        px = max(
            0.0,
            float(
                price
                if price is not None
                else self._config.get("_current_price", self._config.get("_mid_price", 0.0))
                or 0.0
            ),
        )
        explicit_quote = max(
            0.0, float(self._config.get("_min_order_quote", 0.0) or 0.0)
        )
        base_minimum = self.minimum_tradable_base(px)
        quote_notional = max(explicit_quote, base_minimum * px if px > 0 else 0.0)
        return self.quote_notional_to_eur(quote_notional)

    def bounded_entry_notional(
        self,
        requested_eur: float,
        *,
        price: float,
        symbol: str,
    ) -> float:
        """Shrink a BUY request to current hard-risk headroom.

        A result of zero means no valid entry can be placed without violating
        risk or exchange minimums. This helper never expands the requested size.
        """
        requested = max(0.0, float(requested_eur or 0.0))
        px = max(0.0, float(price or 0.0))
        if requested <= 0 or px <= 0:
            return 0.0

        permitted = requested
        if hasattr(self._rm, "max_entry_notional"):
            permitted = min(
                permitted,
                max(
                    0.0,
                    float(self._rm.max_entry_notional(self.name, symbol=symbol)),
                ),
            )

        minimum = self.minimum_tradable_notional(px)
        if minimum > 0 and permitted + 1e-9 < minimum:
            return 0.0
        return max(0.0, permitted)

    def inventory_is_dust(self, quantity: float, price: float | None = None) -> bool:
        quantity = max(0.0, float(quantity or 0.0))
        if quantity <= 0:
            return False
        minimum = self.minimum_tradable_base(price)
        return minimum > 0 and quantity < minimum

    def mark_dust_inventory(self, quantity: float, price: float | None = None) -> None:
        px = max(
            0.0,
            float(
                price
                if price is not None
                else self._config.get("_current_price", self._config.get("_mid_price", 0.0))
                or 0.0
            ),
        )
        qty = max(0.0, float(quantity or 0.0))
        self._config["_dust_base_inventory"] = qty
        self._config["_dust_inventory_eur"] = self.quote_notional_to_eur(qty * px)
        self._config["_dust_inventory_ignored"] = qty > 0

    def clear_dust_inventory(self) -> None:
        self._config["_dust_base_inventory"] = 0.0
        self._config["_dust_inventory_eur"] = 0.0
        self._config["_dust_inventory_ignored"] = False

    def autonomous_entry_decision(self) -> tuple[bool, str]:
        """Combine independent entry gates without mutating their ownership.

        The autonomous router owns _autonomous_entry_allowed. Historical
        evidence owns _evidence_entry_blocked. Risk kill-switches may make
        the autonomous gate false, but the evidence overlay never rewrites it.
        """
        evidence_blocked = bool(
            self._config.get("_evidence_entry_blocked", False)
        )
        router_allowed = bool(
            self._config.get("_autonomous_entry_allowed", True)
        )
        recovery_allowed = bool(
            self._config.get("_evidence_recovery_allowed", False)
        )
        if evidence_blocked:
            if recovery_allowed and router_allowed:
                return True, "live_evidence_recovery_canary"
            return False, str(
                self._config.get("_evidence_entry_reason") or "live_evidence_gate"
            )
        if not router_allowed:
            return False, str(
                self._config.get("_autonomous_entry_reason") or "entry_not_selected"
            )
        return True, ""

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        """Override for custom start-up logic."""

    def on_stop(self) -> None:
        """Override for custom shutdown logic."""

    def on_fill(self, order: "Order", fill: dict) -> None:
        """Receive a confirmed exchange fill owned by this strategy."""

    def on_order_failure(self, order: "Order", category: str, reason: str) -> None:
        """Receive a rejected/failed live order without retrying immediately."""

    def on_market_switch(self, old_market: str, new_market: str) -> None:
        """Clear market-specific live snapshots before a strategy changes symbol."""
        for key, value in {
            "_current_price": 0.0,
            "_mid_price": 0.0,
            "_available_base": 0.0,
            "_available_quote": 0.0,
            "_quote_to_eur": 0.0,
            "_bot_base_inventory": 0.0,
            "_bot_average_entry_price": 0.0,
            "_min_profit_exit_price": 0.0,
            "_exchange_open_order_count": 0,
            "_min_order_base": 0.0,
            "_min_order_quote": 0.0,
            "_quantity_decimals": 18,
            "_market_rules_symbol": "",
            "_dust_base_inventory": 0.0,
            "_dust_inventory_eur": 0.0,
            "_dust_inventory_ignored": False,
            "_protection_entry_price": 0.0,
            "_protection_peak_price": 0.0,
            "_protection_partial_taken": False,
            "_protection_pending_action": "",
            "_protective_exit_requested": False,
            "_live_balance_snapshot_ready": False,
            "_exchange_open_orders_snapshot_ready": False,
        }.items():
            self._config[key] = value
        self._config["_prices"] = {}
        self._config["_market_switch_from"] = old_market
        self._config["_market_switch_to"] = new_market
        self._config["_market_switch_pending"] = True

    @abstractmethod
    def tick(self) -> None:
        """Called on every market-data update / loop iteration."""
