"""Exchange connector stubs.

Real implementations should use ``ccxt`` or exchange-specific SDKs.
API credentials are read exclusively from environment variables – never
hard-coded.

Environment variables
---------------------
BINANCE_API_KEY / BINANCE_API_SECRET
KRAKEN_API_KEY  / KRAKEN_API_SECRET
COINBASE_API_KEY / COINBASE_API_SECRET
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class ConnectorBase(ABC):
    """Minimal interface every exchange connector must implement."""

    name: str = "base"

    def __init__(self) -> None:
        self._api_key: str = ""
        self._api_secret: str = ""

    @abstractmethod
    def connect(self) -> bool:
        """Return True when credentials are valid and connection is live."""

    @abstractmethod
    def get_mid_price(self, symbol: str) -> float:
        """Return the current mid-price for ``symbol``."""

    @abstractmethod
    def place_limit_order(self, symbol: str, side: str,
                          quantity: float, price: float) -> dict:
        """Place a limit order; return exchange order response dict."""

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Place a market order; return exchange order response dict."""

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an open order; return True on success."""

    @abstractmethod
    def get_balances(self) -> Dict[str, float]:
        """Return asset → free balance mapping."""


class BinanceConnector(ConnectorBase):
    """Binance spot connector stub."""

    name = "binance"

    def __init__(self) -> None:
        super().__init__()
        self._api_key = os.getenv("BINANCE_API_KEY", "")
        self._api_secret = os.getenv("BINANCE_API_SECRET", "")

    def connect(self) -> bool:
        # TODO: initialise ccxt.binance({"apiKey": ..., "secret": ...})
        if not self._api_key or not self._api_secret:
            raise EnvironmentError(
                "BINANCE_API_KEY and BINANCE_API_SECRET env vars must be set."
            )
        return True

    def get_mid_price(self, symbol: str) -> float:
        # TODO: exchange.fetch_ticker(symbol)["last"]
        return 0.0

    def place_limit_order(self, symbol: str, side: str,
                          quantity: float, price: float) -> dict:
        # TODO: exchange.create_order(symbol, "limit", side, quantity, price)
        return {"id": "stub", "status": "open"}

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        # TODO: exchange.create_order(symbol, "market", side, quantity)
        return {"id": "stub", "status": "closed"}

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        # TODO: exchange.cancel_order(order_id, symbol)
        return True

    def get_balances(self) -> Dict[str, float]:
        # TODO: exchange.fetch_balance()["free"]
        return {}


class KrakenConnector(ConnectorBase):
    """Kraken spot connector stub."""

    name = "kraken"

    def __init__(self) -> None:
        super().__init__()
        self._api_key = os.getenv("KRAKEN_API_KEY", "")
        self._api_secret = os.getenv("KRAKEN_API_SECRET", "")

    def connect(self) -> bool:
        if not self._api_key or not self._api_secret:
            raise EnvironmentError(
                "KRAKEN_API_KEY and KRAKEN_API_SECRET env vars must be set."
            )
        return True

    def get_mid_price(self, symbol: str) -> float:
        return 0.0

    def place_limit_order(self, symbol: str, side: str,
                          quantity: float, price: float) -> dict:
        return {"id": "stub", "status": "open"}

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        return {"id": "stub", "status": "closed"}

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True

    def get_balances(self) -> Dict[str, float]:
        return {}


class CoinbaseConnector(ConnectorBase):
    """Coinbase Advanced Trade connector stub."""

    name = "coinbase"

    def __init__(self) -> None:
        super().__init__()
        self._api_key = os.getenv("COINBASE_API_KEY", "")
        self._api_secret = os.getenv("COINBASE_API_SECRET", "")

    def connect(self) -> bool:
        if not self._api_key or not self._api_secret:
            raise EnvironmentError(
                "COINBASE_API_KEY and COINBASE_API_SECRET env vars must be set."
            )
        return True

    def get_mid_price(self, symbol: str) -> float:
        return 0.0

    def place_limit_order(self, symbol: str, side: str,
                          quantity: float, price: float) -> dict:
        return {"id": "stub", "status": "open"}

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        return {"id": "stub", "status": "closed"}

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True

    def get_balances(self) -> Dict[str, float]:
        return {}


# Registry: exchange name → connector class
CONNECTOR_REGISTRY: Dict[str, type] = {
    "binance": BinanceConnector,
    "kraken": KrakenConnector,
    "coinbase": CoinbaseConnector,
}


def get_connector(name: str) -> Optional[ConnectorBase]:
    """Return an unconnected connector instance for ``name``, or None."""
    cls = CONNECTOR_REGISTRY.get(name.lower())
    return cls() if cls else None
