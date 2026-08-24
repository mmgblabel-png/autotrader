"""USDCService – abstraction layer for USDC ERC-20 operations.

Real contract calls must be added here; stubs only for now.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from autotrader.core.logger import get_logger

log = get_logger("USDCService")

# ERC-20 USDC contract address on Ethereum mainnet (example)
USDC_CONTRACT_ADDRESS = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
USDC_DECIMALS = 6


class USDCServiceBase(ABC):

    @abstractmethod
    def get_balance(self, address: str) -> float:
        """Return USDC balance for ``address`` (human-readable, not raw units)."""

    @abstractmethod
    def deposit(self, amount_usdc: float, from_address: str) -> str:
        """Move USDC into the trading wallet; return tx hash."""

    @abstractmethod
    def withdraw(self, amount_usdc: float, to_address: str) -> str:
        """Move USDC out of the trading wallet; return tx hash."""


class StubUSDCService(USDCServiceBase):
    """
    Stand-in implementation.

    Replace the TODO sections with actual web3.py / ethers-style contract calls.
    Keep the private key and RPC URL in environment variables – never in code.
    """

    def __init__(self, wallet_address: str = "0x0000000000000000000000000000000000000000") -> None:
        self._wallet = wallet_address

    def get_balance(self, address: str) -> float:
        # TODO: call USDC_CONTRACT.functions.balanceOf(address) / 10**USDC_DECIMALS
        log.info("USDCService.get_balance(%s) – stub", address)
        return 0.0

    def deposit(self, amount_usdc: float, from_address: str) -> str:
        # TODO: construct and send ERC-20 transfer transaction
        log.info("USDCService.deposit(%.2f USDC) from %s – stub", amount_usdc, from_address)
        return "0x" + "0" * 64

    def withdraw(self, amount_usdc: float, to_address: str) -> str:
        # TODO: construct and send ERC-20 transfer transaction
        log.info("USDCService.withdraw(%.2f USDC) to %s – stub", amount_usdc, to_address)
        return "0x" + "0" * 64
