"""PostgreSQL persistence for quote proposals and atomic daily-exposure reservations.

No method in this module signs, broadcasts, creates calldata, calls an RPC node,
or writes a transaction/receipt/fill.  The transaction/receipt schema is reserved
for a future separately audited reconciler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from typing import Final
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import psycopg
from psycopg.errors import SerializationFailure
from psycopg.rows import dict_row

from autotrader.blockchain.mainnet_policy import MainnetExecutionPolicy
from autotrader.quotes.uniswap import UniswapQuote

USDC_BASE_UNITS: Final[Decimal] = Decimal("1000000")
WEI_PER_ETH: Final[Decimal] = Decimal("1000000000000000000")
MAX_SERIALIZABLE_RETRIES: Final[int] = 3


class LedgerUnavailable(RuntimeError):
    """The durable ledger has not been configured or cannot be reached."""


class LedgerPolicyViolation(ValueError):
    """The durable database rejected a proposal or capacity reservation."""


@dataclass(frozen=True)
class QuoteProposalRecord:
    """Non-executable proposal data returned by the durable ledger."""

    proposal_id: UUID
    reservation_id: UUID
    idempotency_key: UUID
    policy_version_id: UUID
    risk_date: date
    amount_in_usdc: Decimal
    amount_in_base_units: int
    quoted_amount_out_base_units: int
    min_amount_out_base_units: int
    estimated_network_fee_wei: int
    slippage_bps: int
    requires_token_approval: bool
    quoted_at: datetime
    expires_at: datetime
    status: str
    idempotent: bool


class PostgresQuoteLedger:
    """Repository that delegates atomic exposure enforcement to PostgreSQL."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url if database_url is not None else os.getenv("DATABASE_URL")

    @property
    def configured(self) -> bool:
        """Whether this process has a database URL; no connection is opened here."""
        return bool(self._database_url and self._database_url.strip())

    def find_by_idempotency_key(self, idempotency_key: UUID) -> QuoteProposalRecord | None:
        """Return an existing proposal before contacting an upstream quote provider."""
        if not self.configured:
            raise LedgerUnavailable("Durable quote ledger is not configured.")
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT qp.*, er.id AS reservation_id, er.risk_date
                          FROM quote_proposals qp
                          JOIN exposure_reservations er ON er.proposal_id = qp.id
                         WHERE qp.idempotency_key = %s
                        """,
                        (idempotency_key,),
                    )
                    row = cursor.fetchone()
        except psycopg.Error as exc:
            raise LedgerUnavailable("Durable quote ledger is unavailable.") from exc
        return _record_from_row(row, idempotent=True) if row else None

    def create_proposal_and_reserve(
        self,
        *,
        idempotency_key: UUID,
        policy: MainnetExecutionPolicy,
        swapper_address: str,
        amount_in_usdc: Decimal,
        quote: UniswapQuote,
        quoted_at: datetime,
        expires_at: datetime,
    ) -> QuoteProposalRecord:
        """Persist a quote and reserve daily USDC capacity atomically.

        The caller must already have performed in-process policy validation.  The
        stored procedure repeats the relevant checks while row-locking the UTC-day
        risk state; no process-local counter is trusted for capacity decisions.
        """
        if not self.configured:
            raise LedgerUnavailable("Durable quote ledger is not configured.")
        if quoted_at.tzinfo is None or expires_at.tzinfo is None:
            raise LedgerPolicyViolation("Quote timestamps must be timezone-aware.")
        quoted_at = quoted_at.astimezone(timezone.utc)
        expires_at = expires_at.astimezone(timezone.utc)
        amount_base_units = _usdc_to_base_units(amount_in_usdc)
        if amount_base_units != quote.amount_in_base_units:
            raise LedgerPolicyViolation("Provider input amount does not match exact USDC amount.")

        policy_id, policy_hash, configuration = _policy_snapshot(policy)
        proposal_id = uuid4()
        reservation_id = uuid4()
        max_fee_wei = _eth_to_wei(policy.max_network_fee_eth)
        metadata = dict(quote.provider_metadata)
        metadata["provider_request_id"] = quote.provider_request_id
        metadata["provider_quote_id"] = quote.provider_quote_id

        for attempt in range(MAX_SERIALIZABLE_RETRIES):
            try:
                with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                    with connection.transaction():
                        with connection.cursor() as cursor:
                            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                            cursor.execute(
                                """
                                INSERT INTO policy_versions (
                                    id, policy_hash, chain_id, execution_enabled, emergency_stop,
                                    max_trade_usdc, max_daily_usdc, max_daily_loss_usdc,
                                    max_slippage_bps, max_network_fee_wei, configuration
                                ) VALUES (
                                    %(id)s, %(policy_hash)s, 8453, %(execution_enabled)s,
                                    %(emergency_stop)s, %(max_trade_usdc)s, %(max_daily_usdc)s,
                                    %(max_daily_loss_usdc)s, %(max_slippage_bps)s,
                                    %(max_network_fee_wei)s, %(configuration)s::jsonb
                                ) ON CONFLICT (policy_hash) DO NOTHING
                                """,
                                {
                                    "id": policy_id,
                                    "policy_hash": policy_hash,
                                    "execution_enabled": policy.execution_enabled,
                                    "emergency_stop": policy.emergency_stop,
                                    "max_trade_usdc": policy.max_trade_usdc,
                                    "max_daily_usdc": policy.max_daily_usdc,
                                    "max_daily_loss_usdc": policy.max_daily_loss_usdc,
                                    "max_slippage_bps": policy.max_slippage_bps,
                                    "max_network_fee_wei": max_fee_wei,
                                    "configuration": json.dumps(configuration, sort_keys=True),
                                },
                            )
                            cursor.execute(
                                """
                                SELECT * FROM autotrader_create_quote_proposal_and_reserve(
                                    %(proposal_id)s, %(reservation_id)s, %(idempotency_key)s,
                                    %(policy_version_id)s, 'uniswap', %(provider_request_id)s,
                                    %(routing)s, %(swapper_address)s, %(amount_in_base_units)s,
                                    %(amount_in_usdc)s, %(quoted_amount_out_base_units)s,
                                    %(min_amount_out_base_units)s, %(estimated_network_fee_wei)s,
                                    %(slippage_bps)s, %(requires_token_approval)s, %(quoted_at)s,
                                    %(expires_at)s, %(provider_metadata)s::jsonb,
                                    %(max_trade_usdc)s, %(max_daily_usdc)s,
                                    %(max_daily_loss_usdc)s, %(max_slippage_bps)s,
                                    %(max_network_fee_wei)s, %(now)s
                                )
                                """,
                                {
                                    "proposal_id": proposal_id,
                                    "reservation_id": reservation_id,
                                    "idempotency_key": idempotency_key,
                                    "policy_version_id": policy_id,
                                    "provider_request_id": quote.provider_request_id,
                                    "routing": quote.routing,
                                    "swapper_address": swapper_address,
                                    "amount_in_base_units": amount_base_units,
                                    "amount_in_usdc": amount_in_usdc,
                                    "quoted_amount_out_base_units": quote.amount_out_base_units,
                                    "min_amount_out_base_units": quote.min_amount_out_base_units,
                                    "estimated_network_fee_wei": quote.estimated_network_fee_wei,
                                    "slippage_bps": _validated_quote_slippage_bps(quote, policy),
                                    "requires_token_approval": quote.requires_token_approval,
                                    "quoted_at": quoted_at,
                                    "expires_at": expires_at,
                                    "provider_metadata": json.dumps(metadata, sort_keys=True),
                                    "max_trade_usdc": policy.max_trade_usdc,
                                    "max_daily_usdc": policy.max_daily_usdc,
                                    "max_daily_loss_usdc": policy.max_daily_loss_usdc,
                                    "max_slippage_bps": policy.max_slippage_bps,
                                    "max_network_fee_wei": max_fee_wei,
                                    "now": datetime.now(timezone.utc),
                                },
                            )
                            result = cursor.fetchone()
                            if result is None:
                                raise LedgerUnavailable("Ledger reservation returned no result.")
                            if result["idempotent"]:
                                cursor.execute(
                                    """
                                    SELECT qp.*, er.id AS reservation_id, er.risk_date
                                      FROM quote_proposals qp
                                      JOIN exposure_reservations er ON er.proposal_id = qp.id
                                     WHERE qp.id = %s
                                    """,
                                    (result["proposal_id"],),
                                )
                                existing = cursor.fetchone()
                                if not existing:
                                    raise LedgerUnavailable("Ledger idempotency record is incomplete.")
                                return _record_from_row(existing, idempotent=True)
                            return QuoteProposalRecord(
                                proposal_id=result["proposal_id"],
                                reservation_id=result["reservation_id"],
                                idempotency_key=idempotency_key,
                                policy_version_id=policy_id,
                                risk_date=result["risk_date"],
                                amount_in_usdc=amount_in_usdc,
                                amount_in_base_units=amount_base_units,
                                quoted_amount_out_base_units=quote.amount_out_base_units,
                                min_amount_out_base_units=quote.min_amount_out_base_units,
                                estimated_network_fee_wei=quote.estimated_network_fee_wei,
                                slippage_bps=_validated_quote_slippage_bps(quote, policy),
                                requires_token_approval=quote.requires_token_approval,
                                quoted_at=quoted_at,
                                expires_at=expires_at,
                                status="RESERVED",
                                idempotent=False,
                            )
            except SerializationFailure:
                if attempt == MAX_SERIALIZABLE_RETRIES - 1:
                    raise LedgerUnavailable("Ledger was busy; retry the proposal request.")
                continue
            except psycopg.Error as exc:
                message = str(exc)
                if _is_policy_error(message):
                    raise LedgerPolicyViolation("Quote proposal was rejected by durable risk controls.") from exc
                raise LedgerUnavailable("Durable quote ledger is unavailable.") from exc
        raise LedgerUnavailable("Ledger reservation retry limit was exceeded.")


def _policy_snapshot(policy: MainnetExecutionPolicy) -> tuple[UUID, str, dict[str, object]]:
    configuration: dict[str, object] = {
        "chain_id": 8453,
        "execution_enabled": policy.execution_enabled,
        "emergency_stop": policy.emergency_stop,
        "max_trade_usdc": str(policy.max_trade_usdc),
        "max_daily_usdc": str(policy.max_daily_usdc),
        "max_daily_loss_usdc": str(policy.max_daily_loss_usdc),
        "max_slippage_bps": policy.max_slippage_bps,
        "max_network_fee_eth": str(policy.max_network_fee_eth),
        "allowed_pairs": sorted([list(pair) for pair in policy.allowed_pairs]),
        "allowed_router": policy.allowed_router,
    }
    canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    policy_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    policy_id = uuid5(NAMESPACE_URL, f"autotrader-policy:{policy_hash}")
    return policy_id, policy_hash, configuration


def _usdc_to_base_units(amount: Decimal) -> int:
    if not amount.is_finite() or amount <= 0:
        raise LedgerPolicyViolation("USDC amount must be positive and finite.")
    base_units = amount * USDC_BASE_UNITS
    if base_units != base_units.to_integral_value():
        raise LedgerPolicyViolation("USDC amount supports at most six decimal places.")
    return int(base_units)


def _eth_to_wei(amount: Decimal) -> int:
    if not amount.is_finite() or amount < 0:
        raise LedgerPolicyViolation("ETH fee cap must be non-negative and finite.")
    wei = amount * WEI_PER_ETH
    if wei != wei.to_integral_value():
        raise LedgerPolicyViolation("ETH fee cap has unsupported precision.")
    return int(wei)


def _validated_quote_slippage_bps(quote: UniswapQuote, policy: MainnetExecutionPolicy) -> int:
    """Confirm the persisted quote uses the same bounded bps value sent upstream."""
    value = quote.slippage_bps
    if not isinstance(value, int) or isinstance(value, bool):
        raise LedgerPolicyViolation("Quote has no validated slippage value.")
    if value < 0 or value > policy.max_slippage_bps:
        raise LedgerPolicyViolation("Quote slippage exceeds policy.")
    return value


def _record_from_row(row: dict[str, object], *, idempotent: bool) -> QuoteProposalRecord:
    return QuoteProposalRecord(
        proposal_id=row["id"],
        reservation_id=row["reservation_id"],
        idempotency_key=row["idempotency_key"],
        policy_version_id=row["policy_version_id"],
        risk_date=row["risk_date"],
        amount_in_usdc=Decimal(str(row["amount_in_usdc"])),
        amount_in_base_units=int(row["amount_in_base_units"]),
        quoted_amount_out_base_units=int(row["quoted_amount_out_base_units"]),
        min_amount_out_base_units=int(row["min_amount_out_base_units"]),
        estimated_network_fee_wei=int(row["estimated_network_fee_wei"]),
        slippage_bps=int(row["slippage_bps"]),
        requires_token_approval=bool(row["requires_token_approval"]),
        quoted_at=row["quoted_at"],
        expires_at=row["expires_at"],
        status=row["status"],
        idempotent=idempotent,
    )


def _is_policy_error(message: str) -> bool:
    return any(
        fragment in message
        for fragment in (
            "safety cap is unset",
            "Per-trade exposure cap exceeded",
            "Daily exposure cap exceeded",
            "Daily realised-loss stop is active",
            "Slippage cap exceeded",
            "Network-fee cap exceeded",
            "Quote TTL is invalid",
            "Only the sanitised Uniswap CLASSIC",
        )
    )
