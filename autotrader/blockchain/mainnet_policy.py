"""Fail-closed policy checks for *proposed* Base Mainnet swaps.

This module deliberately does not import a wallet SDK, an RPC client, or a DEX
SDK. It cannot request a MetaMask signature, issue an ERC-20 approval, or
broadcast a transaction. Its sole purpose is to reject unsafe proposed
transactions before a future, separately-audited browser-only signer is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from time import time
from typing import Final

BASE_MAINNET_CHAIN_ID: Final[int] = 8453
BASE_USDC: Final[str] = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
BASE_WETH: Final[str] = "0x4200000000000000000000000000000000000006"
UNISWAP_V3_SWAP_ROUTER_02: Final[str] = "0x2626664c2603336e57b271c5c0b26f421741e481"
MAX_PROPOSAL_TTL_SECONDS: Final[int] = 120


class PolicyViolation(ValueError):
    """Raised when a proposed trade does not meet the immutable policy."""


def _address(value: str) -> str:
    """Normalise an EVM address and reject malformed values without RPC calls."""
    if not isinstance(value, str):
        raise PolicyViolation("Address must be a string.")
    normalised = value.lower()
    if len(normalised) != 42 or not normalised.startswith("0x"):
        raise PolicyViolation("Address must be a 20-byte 0x-prefixed EVM address.")
    try:
        int(normalised[2:], 16)
    except ValueError as exc:
        raise PolicyViolation("Address contains non-hexadecimal characters.") from exc
    return normalised


@dataclass(frozen=True)
class TradeIntent:
    """A quote-derived swap intent that is safe to inspect but never execute here."""

    proposal_id: str
    chain_id: int
    token_in: str
    token_out: str
    router: str
    amount_in_usdc: Decimal
    min_amount_out: Decimal
    quoted_at_epoch: int
    expires_at_epoch: int
    slippage_bps: int
    estimated_network_fee_eth: Decimal


@dataclass(frozen=True)
class MainnetExecutionPolicy:
    """A deliberately narrow policy for a future manual USDC/WETH swap flow.

    ``execution_enabled`` and both financial caps default to fail closed. Even if
    a caller creates an intent that passes policy, this module returns metadata
    only; actual signing must always be initiated by an explicit user action in
    MetaMask and is intentionally outside this package.
    """

    execution_enabled: bool = False
    emergency_stop: bool = True
    max_trade_usdc: Decimal = Decimal("0")
    max_daily_usdc: Decimal = Decimal("0")
    max_slippage_bps: int = 30
    max_network_fee_eth: Decimal = Decimal("0")
    allowed_pairs: frozenset[tuple[str, str]] = field(
        default_factory=lambda: frozenset(
            {(BASE_USDC, BASE_WETH), (BASE_WETH, BASE_USDC)}
        )
    )
    allowed_router: str = UNISWAP_V3_SWAP_ROUTER_02

    def validate(self, intent: TradeIntent, *, daily_used_usdc: Decimal = Decimal("0"), now_epoch: int | None = None) -> None:
        """Validate one proposal, raising :class:`PolicyViolation` on any fault."""
        now = int(time()) if now_epoch is None else now_epoch
        if not self.execution_enabled:
            raise PolicyViolation("Mainnet execution is disabled by policy.")
        if self.emergency_stop:
            raise PolicyViolation("Emergency stop is active.")
        if intent.chain_id != BASE_MAINNET_CHAIN_ID:
            raise PolicyViolation("Proposal chain must be Base Mainnet (8453).")
        if not intent.proposal_id or len(intent.proposal_id) < 16:
            raise PolicyViolation("Proposal ID must be a non-empty, high-entropy identifier.")
        token_in = _address(intent.token_in)
        token_out = _address(intent.token_out)
        router = _address(intent.router)
        if (token_in, token_out) not in self.allowed_pairs:
            raise PolicyViolation("Token pair is not allowlisted.")
        if router != _address(self.allowed_router):
            raise PolicyViolation("Router is not allowlisted.")
        if intent.amount_in_usdc <= 0:
            raise PolicyViolation("Input amount must be positive.")
        if self.max_trade_usdc <= 0:
            raise PolicyViolation("Per-trade cap is unset; execution is fail-closed.")
        if intent.amount_in_usdc > self.max_trade_usdc:
            raise PolicyViolation("Input amount exceeds the per-trade cap.")
        if self.max_daily_usdc <= 0:
            raise PolicyViolation("Daily cap is unset; execution is fail-closed.")
        if daily_used_usdc < 0 or daily_used_usdc + intent.amount_in_usdc > self.max_daily_usdc:
            raise PolicyViolation("Input amount exceeds the daily exposure cap.")
        if intent.min_amount_out <= 0:
            raise PolicyViolation("Minimum output must be positive.")
        if not 0 <= intent.slippage_bps <= self.max_slippage_bps:
            raise PolicyViolation("Slippage is outside the policy bound.")
        if self.max_network_fee_eth <= 0:
            raise PolicyViolation("Network-fee cap is unset; execution is fail-closed.")
        if intent.estimated_network_fee_eth < 0 or intent.estimated_network_fee_eth > self.max_network_fee_eth:
            raise PolicyViolation("Estimated network fee exceeds the policy cap.")
        if intent.quoted_at_epoch > now:
            raise PolicyViolation("Quote timestamp cannot be in the future.")
        if intent.expires_at_epoch <= now:
            raise PolicyViolation("Quote has expired.")
        if intent.expires_at_epoch - intent.quoted_at_epoch > MAX_PROPOSAL_TTL_SECONDS:
            raise PolicyViolation("Quote validity window exceeds the maximum proposal TTL.")

    def proposal_summary(self, intent: TradeIntent) -> dict[str, object]:
        """Return human-reviewable metadata only; never generate transaction calldata."""
        return {
            "proposal_id": intent.proposal_id,
            "chain_id": intent.chain_id,
            "token_in": _address(intent.token_in),
            "token_out": _address(intent.token_out),
            "router": _address(intent.router),
            "amount_in_usdc": str(intent.amount_in_usdc),
            "min_amount_out": str(intent.min_amount_out),
            "slippage_bps": intent.slippage_bps,
            "expires_at_epoch": intent.expires_at_epoch,
            "execution_capability": "not_implemented",
        }
