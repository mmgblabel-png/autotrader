"""WalletService – abstraction layer for EVM-compatible wallet operations.

Real RPC calls and private-key management must be added here.
This module intentionally contains only stubs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from autotrader.core.logger import get_logger

log = get_logger("WalletService")


class WalletServiceBase(ABC):
    """Interface every wallet implementation must satisfy."""

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to the wallet / RPC node."""

    @abstractmethod
    def get_address(self) -> str:
        """Return the active EVM address."""

    @abstractmethod
    def get_eth_balance(self) -> float:
        """Return native token balance in ETH/MATIC/etc."""

    @abstractmethod
    def sign_transaction(self, tx: dict) -> dict:
        """Sign a raw transaction dict and return the signed version."""

    @abstractmethod
    def send_transaction(self, signed_tx: dict) -> str:
        """Broadcast a signed transaction; return the transaction hash."""


class StubWalletService(WalletServiceBase):
    """
    Stand-in implementation – replace with web3.py calls when ready.

    Environment variables expected (not read here – fill in on deployment):
        WALLET_PRIVATE_KEY   : hex private key (never commit!)
        RPC_URL              : e.g. https://mainnet.infura.io/v3/<API_KEY>
        CHAIN_ID             : e.g. 1 for Ethereum mainnet
    """

    def __init__(self, address: Optional[str] = None) -> None:
        self._address = address or "0x0000000000000000000000000000000000000000"
        self._connected = False

    def connect(self) -> bool:
        # TODO: initialise web3.py provider with RPC_URL env var
        log.info("WalletService.connect() – stub (replace with web3 provider)")
        self._connected = True
        return True

    def get_address(self) -> str:
        return self._address

    def get_eth_balance(self) -> float:
        # TODO: web3.eth.get_balance(self._address)
        log.info("WalletService.get_eth_balance() – stub")
        return 0.0

    def sign_transaction(self, tx: dict) -> dict:
        # TODO: web3.eth.account.sign_transaction(tx, private_key)
        log.info("WalletService.sign_transaction() – stub, tx=%s", tx)
        return {"signed": True, "tx": tx}

    def send_transaction(self, signed_tx: dict) -> str:
        # TODO: web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        log.info("WalletService.send_transaction() – stub")
        return "0x" + "0" * 64   # placeholder tx hash
