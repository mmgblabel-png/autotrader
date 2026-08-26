"""Regression tests for the disabled durable quote-proposal subsystem.

These tests use mock transports and fake repositories only.  They do not contact
Uniswap, Railway PostgreSQL, an RPC endpoint, or a wallet.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from autotrader.blockchain.mainnet_policy import (
    BASE_MAINNET_CHAIN_ID,
    BASE_USDC,
    BASE_WETH,
    UNISWAP_V3_SWAP_ROUTER_02,
    MainnetExecutionPolicy,
    PolicyViolation,
)
from autotrader.ledger.postgres import QuoteProposalRecord
from autotrader.ledger.quote_proposals import (
    QuoteProposalDisabled,
    QuoteProposalRequest,
    QuoteProposalService,
    QuoteProposalValidationError,
    parse_usdc_amount,
)
from autotrader.quotes.uniswap import (
    QuoteProviderUnavailable,
    UniswapQuote,
    UniswapQuoteClient,
)


def _quote_response(*, amount: str = "5000000") -> dict[str, object]:
    return {
        "requestId": "request-123",
        "routing": "CLASSIC",
        "isTokenApprovalApplicable": True,
        "quote": {
            "quoteId": "quote-123",
            "swapper": "0x1111111111111111111111111111111111111111",
            "input": {"token": BASE_USDC, "amount": amount},
            "output": {
                "token": BASE_WETH,
                "amount": "2500000000000000",
                "minimumAmount": "2400000000000000",
            },
            "gasFee": "10000000000000",
            "gasUseEstimate": "200000",
            "blockNumber": "123",
        },
    }


def test_uniswap_client_requires_server_side_key():
    client = UniswapQuoteClient(api_key="")
    with pytest.raises(QuoteProviderUnavailable, match="not configured"):
        asyncio.run(
            client.get_exact_input_usdc_to_weth_quote(
                swapper_address="0x1111111111111111111111111111111111111111",
                amount_in_base_units=5_000_000,
                slippage_bps=25,
            )
        )


def test_uniswap_client_uses_quote_endpoint_only_and_sanitises_response():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-api-key")
        seen["payload"] = request.content.decode("utf-8")
        return httpx.Response(200, json=_quote_response())

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = UniswapQuoteClient(api_key="server-only-test-key", http_client=mock_client)
    quote = asyncio.run(
        client.get_exact_input_usdc_to_weth_quote(
            swapper_address="0x1111111111111111111111111111111111111111",
            amount_in_base_units=5_000_000,
            slippage_bps=25,
        )
    )
    asyncio.run(mock_client.aclose())

    assert seen["url"] == "https://trade-api.gateway.uniswap.org/v1/quote"
    assert seen["api_key"] == "server-only-test-key"
    assert '"tokenIn":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"' in seen["payload"]
    assert quote.amount_out_base_units == 2_500_000_000_000_000
    assert quote.min_amount_out_base_units == 2_400_000_000_000_000
    assert quote.estimated_network_fee_wei == 10_000_000_000_000
    assert quote.slippage_bps == 25
    assert quote.provider_metadata == {
        "provider_quote_id": "quote-123",
        "blockNumber": "123",
        "gasUseEstimate": "200000",
    }


def test_uniswap_client_rejects_zero_network_fee_estimate():
    response = _quote_response()
    response["quote"]["gasFee"] = "0"
    with pytest.raises(Exception, match="gas fee must be positive"):
        UniswapQuoteClient._parse_quote(
            response,
            expected_swapper="0x1111111111111111111111111111111111111111",
            expected_amount_in_base_units=5_000_000,
            expected_slippage_bps=25,
        )


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "1.0000001", "not-a-number"])
def test_usdc_amount_parser_rejects_unsafe_or_inexact_values(value: str):
    with pytest.raises(QuoteProposalValidationError):
        parse_usdc_amount(value)


def test_usdc_amount_parser_preserves_exact_six_decimal_units():
    assert parse_usdc_amount("1.123456") == Decimal("1.123456")


def test_policy_quote_preflight_defaults_fail_closed():
    with pytest.raises(PolicyViolation, match="disabled"):
        MainnetExecutionPolicy().validate_quote_request(
            chain_id=BASE_MAINNET_CHAIN_ID,
            token_in=BASE_USDC,
            token_out=BASE_WETH,
            router=UNISWAP_V3_SWAP_ROUTER_02,
            amount_in_usdc=Decimal("5"),
            slippage_bps=25,
        )


class _UnexpectedClient:
    configured = True

    async def get_exact_input_usdc_to_weth_quote(self, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("provider call occurred while proposals were disabled")


class _UnexpectedLedger:
    configured = True

    def find_by_idempotency_key(self, key):  # pragma: no cover - must not run
        raise AssertionError("ledger call occurred while proposals were disabled")


def test_service_blocks_before_provider_and_ledger_when_disabled(monkeypatch):
    monkeypatch.delenv("MAINNET_QUOTE_PROPOSALS_ENABLED", raising=False)
    service = QuoteProposalService(quote_client=_UnexpectedClient(), ledger=_UnexpectedLedger())
    with pytest.raises(QuoteProposalDisabled):
        asyncio.run(
            service.create(
                request=QuoteProposalRequest(
                    swapper_address="0x1111111111111111111111111111111111111111",
                    amount_in_usdc="5",
                    slippage_bps=25,
                ),
                idempotency_key=uuid4(),
            )
        )


class _FakeQuoteClient:
    configured = True

    async def get_exact_input_usdc_to_weth_quote(self, **kwargs):
        return UniswapQuote(
            provider_request_id="request-123",
            provider_quote_id="quote-123",
            routing="CLASSIC",
            token_in=BASE_USDC,
            token_out=BASE_WETH,
            amount_in_base_units=5_000_000,
            amount_out_base_units=2_500_000_000_000_000,
            min_amount_out_base_units=2_400_000_000_000_000,
            estimated_network_fee_wei=10_000_000_000_000,
            slippage_bps=25,
            requires_token_approval=True,
            provider_metadata={"provider_quote_id": "quote-123"},
        )


class _FakeLedger:
    configured = True

    def __init__(self):
        self.created: dict[str, object] | None = None

    def find_by_idempotency_key(self, key):
        return None

    def create_proposal_and_reserve(self, **kwargs):
        self.created = kwargs
        now = datetime.now(timezone.utc)
        return QuoteProposalRecord(
            proposal_id=uuid4(),
            reservation_id=uuid4(),
            idempotency_key=kwargs["idempotency_key"],
            policy_version_id=uuid4(),
            risk_date=date.today(),
            amount_in_usdc=Decimal("5"),
            amount_in_base_units=5_000_000,
            quoted_amount_out_base_units=2_500_000_000_000_000,
            min_amount_out_base_units=2_400_000_000_000_000,
            estimated_network_fee_wei=10_000_000_000_000,
            slippage_bps=25,
            requires_token_approval=True,
            quoted_at=now,
            expires_at=now + timedelta(seconds=30),
            status="RESERVED",
            idempotent=False,
        )


def test_service_calls_ledger_only_after_full_policy_validation(monkeypatch):
    monkeypatch.setenv("MAINNET_QUOTE_PROPOSALS_ENABLED", "true")
    monkeypatch.setenv("MAINNET_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("MAINNET_EMERGENCY_STOP", "false")
    monkeypatch.setenv("MAINNET_MAX_TRADE_USDC", "10")
    monkeypatch.setenv("MAINNET_MAX_DAILY_USDC", "25")
    monkeypatch.setenv("MAINNET_MAX_DAILY_LOSS_USDC", "5")
    monkeypatch.setenv("MAINNET_MAX_SLIPPAGE_BPS", "25")
    monkeypatch.setenv("MAINNET_MAX_GAS_ETH", "0.001")
    ledger = _FakeLedger()
    service = QuoteProposalService(quote_client=_FakeQuoteClient(), ledger=ledger)

    result = asyncio.run(
        service.create(
            request=QuoteProposalRequest(
                swapper_address="0x1111111111111111111111111111111111111111",
                amount_in_usdc="5",
                slippage_bps=25,
            ),
            idempotency_key=uuid4(),
        )
    )

    assert result.status == "RESERVED"
    assert ledger.created is not None
    assert ledger.created["amount_in_usdc"] == Decimal("5")
    assert ledger.created["quote"].routing == "CLASSIC"


def test_migration_contains_atomic_reservation_and_no_execution_code():
    migration = Path(__file__).parents[1] / "migrations" / "001_durable_quote_ledger.sql"
    content = migration.read_text(encoding="utf-8")
    assert "autotrader_create_quote_proposal_and_reserve" in content
    assert "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE" not in content
    assert "FOR UPDATE" in content
    assert "eth_sendTransaction" not in content
    assert "calldata TEXT" not in content


def test_api_quote_route_is_protected_and_disabled(monkeypatch):
    monkeypatch.setenv("AUTOTRADER_QUOTE_PROPOSAL_TOKEN", "quote-secret")
    monkeypatch.delenv("MAINNET_QUOTE_PROPOSALS_ENABLED", raising=False)
    from autotrader.api.server import app

    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.post(
            "/api/mainnet/quote-proposals",
            headers={
                "X-AutoTrader-Quote-Token": "quote-secret",
                "Idempotency-Key": str(uuid4()),
            },
            json={
                "swapper_address": "0x1111111111111111111111111111111111111111",
                "amount_in_usdc": "5",
                "slippage_bps": 25,
            },
        )
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()
