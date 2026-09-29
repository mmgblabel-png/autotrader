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

    def observe(self) -> None:
        """Update local indicators without creating any order intent."""

    @abstractmethod
    def tick(self) -> None:
        """Called on every market-data update / loop iteration."""
