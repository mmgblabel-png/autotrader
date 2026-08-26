"""Policy-gated quote proposal orchestration.

The service stops after an authenticated quote is validated and durably reserved.
It has no wallet, approval, signing, calldata, broadcast, RPC, receipt, or fill
capability.  A proposal is not an instruction to execute a trade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
from typing import Final
from uuid import UUID, uuid4

from autotrader.blockchain.mainnet_policy import (
    BASE_MAINNET_CHAIN_ID,
    BASE_USDC,
    BASE_WETH,
    MAX_PROPOSAL_TTL_SECONDS,
    UNISWAP_V3_SWAP_ROUTER_02,
    MainnetExecutionPolicy,
    PolicyViolation,
    TradeIntent,
)
from autotrader.ledger.postgres import (
    LedgerPolicyViolation,
    LedgerUnavailable,
    PostgresQuoteLedger,
    QuoteProposalRecord,
)
from autotrader.quotes.uniswap import (
    USDC_BASE_UNITS,
    QuoteProviderError,
    UniswapQuoteClient,
)

WETH_BASE_UNITS: Final[Decimal] = Decimal("1000000000000000000")
WEI_PER_ETH: Final[Decimal] = Decimal("1000000000000000000")
_DEFAULT_QUOTE_TTL_SECONDS: Final[int] = 30
_MIN_QUOTE_TTL_SECONDS: Final[int] = 5


class QuoteProposalDisabled(RuntimeError):
    """The configuration intentionally blocks all quote proposals."""


class QuoteProposalValidationError(ValueError):
    """The public request does not meet strict quote-proposal input rules."""


@dataclass(frozen=True)
class QuoteProposalRequest:
    """Validated public request fields.  Amount is decimal USDC, not a float."""

    swapper_address: str
    amount_in_usdc: str
    slippage_bps: int


class QuoteProposalService:
    """Create a durable, non-executable Base USDC→WETH quote proposal."""

    def __init__(
        self,
        *,
        quote_client: UniswapQuoteClient | None = None,
        ledger: PostgresQuoteLedger | None = None,
    ) -> None:
        self._quote_client = quote_client or UniswapQuoteClient()
        self._ledger = ledger or PostgresQuoteLedger()

    @property
    def configured(self) -> bool:
        """Both the API key and PostgreSQL connection URL are required."""
        return self._quote_client.configured and self._ledger.configured

    async def create(
        self,
        *,
        request: QuoteProposalRequest,
        idempotency_key: UUID,
    ) -> QuoteProposalRecord:
        """Validate, quote, and reserve capacity without an execution path."""
        if not quote_proposals_enabled():
            raise QuoteProposalDisabled("Quote proposals are disabled by configuration.")

        policy = MainnetExecutionPolicy.from_environment()
        amount_in_usdc = parse_usdc_amount(request.amount_in_usdc)
        swapper_address = normalise_evm_address(request.swapper_address)

        # This blocks in the currently deployed zero-cap policy before a database
        # lookup or an outbound HTTPS request can occur.
        policy.validate_quote_request(
            chain_id=BASE_MAINNET_CHAIN_ID,
            token_in=BASE_USDC,
            token_out=BASE_WETH,
            router=UNISWAP_V3_SWAP_ROUTER_02,
            amount_in_usdc=amount_in_usdc,
            slippage_bps=request.slippage_bps,
        )

        existing = self._ledger.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        amount_in_base_units = int(amount_in_usdc * USDC_BASE_UNITS)
        quote = await self._quote_client.get_exact_input_usdc_to_weth_quote(
            swapper_address=swapper_address,
            amount_in_base_units=amount_in_base_units,
            slippage_bps=request.slippage_bps,
        )

        quoted_at = datetime.now(timezone.utc)
        expires_at = quoted_at + timedelta(seconds=quote_ttl_seconds())
        intent = TradeIntent(
            proposal_id=str(uuid4()),
            chain_id=BASE_MAINNET_CHAIN_ID,
            token_in=quote.token_in,
            token_out=quote.token_out,
            router=UNISWAP_V3_SWAP_ROUTER_02,
            amount_in_usdc=amount_in_usdc,
            min_amount_out=Decimal(quote.min_amount_out_base_units) / WETH_BASE_UNITS,
            quoted_at_epoch=int(quoted_at.timestamp()),
            expires_at_epoch=int(expires_at.timestamp()),
            slippage_bps=quote.slippage_bps,
            estimated_network_fee_eth=Decimal(quote.estimated_network_fee_wei) / WEI_PER_ETH,
        )
        # This checks the complete quote against the current in-memory policy.  The
        # database function repeats these checks with durable daily state in the
        # same serializable transaction as the reservation.
        policy.validate(intent, daily_used_usdc=Decimal("0"), daily_realized_loss_usdc=Decimal("0"))

        return self._ledger.create_proposal_and_reserve(
            idempotency_key=idempotency_key,
            policy=policy,
            swapper_address=swapper_address,
            amount_in_usdc=amount_in_usdc,
            quote=quote,
            quoted_at=quoted_at,
            expires_at=expires_at,
        )


def quote_proposals_enabled() -> bool:
    """Require an explicit, exact enablement flag; all other values are false."""
    return os.getenv("MAINNET_QUOTE_PROPOSALS_ENABLED", "false").strip().lower() == "true"


def quote_ttl_seconds() -> int:
    """Read a bounded proposal TTL; invalid values fall back to a short duration."""
    raw = os.getenv("MAINNET_QUOTE_TTL_SECONDS", str(_DEFAULT_QUOTE_TTL_SECONDS))
    try:
        value = int(raw)
    except (ValueError, TypeError):
        return _DEFAULT_QUOTE_TTL_SECONDS
    if _MIN_QUOTE_TTL_SECONDS <= value <= MAX_PROPOSAL_TTL_SECONDS:
        return value
    return _DEFAULT_QUOTE_TTL_SECONDS


def parse_usdc_amount(value: str) -> Decimal:
    """Parse one positive USDC amount with no loss of base-unit precision."""
    if not isinstance(value, str) or not value.strip():
        raise QuoteProposalValidationError("amount_in_usdc must be a non-empty decimal string.")
    try:
        amount = Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise QuoteProposalValidationError("amount_in_usdc must be a valid decimal string.") from exc
    if not amount.is_finite() or amount <= 0:
        raise QuoteProposalValidationError("amount_in_usdc must be positive and finite.")
    base_units = amount * USDC_BASE_UNITS
    if base_units != base_units.to_integral_value():
        raise QuoteProposalValidationError("amount_in_usdc supports at most six decimal places.")
    return amount


def normalise_evm_address(value: str) -> str:
    """Normalise only syntactically valid EVM addresses; no RPC request is made."""
    if not isinstance(value, str):
        raise QuoteProposalValidationError("swapper_address must be an EVM address.")
    address = value.lower().strip()
    if len(address) != 42 or not address.startswith("0x"):
        raise QuoteProposalValidationError("swapper_address must be a 20-byte EVM address.")
    try:
        int(address[2:], 16)
    except ValueError as exc:
        raise QuoteProposalValidationError("swapper_address must be a 20-byte EVM address.") from exc
    return address


__all__ = [
    "LedgerPolicyViolation",
    "LedgerUnavailable",
    "QuoteProposalDisabled",
    "QuoteProposalRequest",
    "QuoteProposalService",
    "QuoteProposalValidationError",
    "QuoteProviderError",
    "quote_proposals_enabled",
    "quote_ttl_seconds",
]
