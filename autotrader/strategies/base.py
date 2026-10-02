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
        self._config["_dust_inventory_eur"] = qty * px
        self._config["_dust_inventory_ignored"] = qty > 0

    def clear_dust_inventory(self) -> None:
        self._config["_dust_base_inventory"] = 0.0
        self._config["_dust_inventory_eur"] = 0.0
        self._config["_dust_inventory_ignored"] = False

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
