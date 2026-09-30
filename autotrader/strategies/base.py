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
            "_live_balance_snapshot_ready": False,
            "_exchange_open_orders_snapshot_ready": False,
        }.items():
            self._config[key] = value
        self._config["_prices"] = {}
        self._config["_market_switch_from"] = old_market
        self._config["_market_switch_to"] = new_market

    @abstractmethod
    def tick(self) -> None:
        """Called on every market-data update / loop iteration."""
