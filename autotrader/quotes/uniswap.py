"""Server-side, quote-only Uniswap Trading API adapter.

This module intentionally calls only ``POST /v1/quote``.  It does not call
``/swap``, ``/order``, approval endpoints, an RPC provider, or any wallet API.
It never receives a private key and never returns permit data or calldata.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from typing import Any, Final

import httpx

from autotrader.blockchain.mainnet_policy import BASE_MAINNET_CHAIN_ID, BASE_USDC, BASE_WETH

UNISWAP_QUOTE_URL: Final[str] = "https://trade-api.gateway.uniswap.org/v1/quote"
USDC_BASE_UNITS: Final[int] = 1_000_000


class QuoteProviderError(RuntimeError):
    """Base class for a quote-provider failure that is safe to expose generically."""


class QuoteProviderUnavailable(QuoteProviderError):
    """The provider integration is not configured or is temporarily unavailable."""


class QuoteProviderRejected(QuoteProviderError):
    """The provider rejected the sanitised quote request."""


class QuoteProviderProtocolError(QuoteProviderError):
    """The provider returned an incomplete or unsupported response."""


@dataclass(frozen=True)
class UniswapQuote:
    """Sanitised quote fields needed for a non-executing proposal reservation."""

    provider_request_id: str
    provider_quote_id: str | None
    routing: str
    token_in: str
    token_out: str
    amount_in_base_units: int
    amount_out_base_units: int
    min_amount_out_base_units: int
    estimated_network_fee_wei: int
    slippage_bps: int
    requires_token_approval: bool
    provider_metadata: dict[str, object]


class UniswapQuoteClient:
    """Small authenticated client for Uniswap's documented quote endpoint only."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = UNISWAP_QUOTE_URL,
        timeout_seconds: float = 8.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("UNISWAP_API_KEY")
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    @property
    def configured(self) -> bool:
        """Return whether an API key has been supplied without exposing it."""
        return bool(self._api_key and self._api_key.strip())

    async def get_exact_input_usdc_to_weth_quote(
        self,
        *,
        swapper_address: str,
        amount_in_base_units: int,
        slippage_bps: int,
    ) -> UniswapQuote:
        """Request a Base USDC→WETH quote and return only sanitised fields.

        The caller is responsible for policy gating before this method.  The API
        key remains in the HTTPS request header and is never persisted here.
        """
        if not self.configured:
            raise QuoteProviderUnavailable("Uniswap quote service is not configured.")
        if amount_in_base_units <= 0:
            raise QuoteProviderRejected("Input amount must be positive.")
        if not 0 <= slippage_bps <= 100:
            raise QuoteProviderRejected("Slippage must be between zero and 100 bps.")

        # The documented API accepts slippage as a percentage.  Bps are converted
        # from the stricter internal representation (e.g. 25 bps -> 0.25%).
        slippage_percent = Decimal(slippage_bps) / Decimal("100")
        payload: dict[str, object] = {
            "type": "EXACT_INPUT",
            "amount": str(amount_in_base_units),
            "tokenInChainId": BASE_MAINNET_CHAIN_ID,
            "tokenOutChainId": BASE_MAINNET_CHAIN_ID,
            "tokenIn": BASE_USDC,
            "tokenOut": BASE_WETH,
            "swapper": swapper_address,
            "recipient": swapper_address,
            "slippageTolerance": float(slippage_percent),
            # Restrict the first adapter to a conventional Uniswap V3 route.  It
            # therefore rejects UniswapX, bridge, wrap, and chained responses.
            "protocols": ["V3"],
            "routingPreference": "BEST_PRICE",
            # No permit payload is needed for a quote proposal.  This avoids
            # receiving an approval-signing artifact in this service.
            "permitAmount": "EXACT",
        }
        headers = {
            "x-api-key": self._api_key.strip(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-permit2-disabled": "true",
        }

        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    self._base_url, headers=headers, json=payload, timeout=self._timeout_seconds
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(self._base_url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise QuoteProviderUnavailable("Uniswap quote request timed out.") from exc
        except httpx.HTTPError as exc:
            raise QuoteProviderUnavailable("Uniswap quote service is unavailable.") from exc

        if response.status_code in {400, 404, 422}:
            raise QuoteProviderRejected("Uniswap did not return a quote for this request.")
        if response.status_code in {401, 403}:
            # Never distinguish malformed vs invalid credentials to API clients.
            raise QuoteProviderUnavailable("Uniswap quote service authentication failed.")
        if response.status_code in {429, 500, 502, 503, 504}:
            raise QuoteProviderUnavailable("Uniswap quote service is temporarily unavailable.")
        if response.status_code < 200 or response.status_code >= 300:
            raise QuoteProviderUnavailable("Uniswap quote service returned an unexpected response.")

        try:
            body = response.json()
        except ValueError as exc:
            raise QuoteProviderProtocolError("Uniswap returned a non-JSON quote response.") from exc
        return self._parse_quote(
            body,
            expected_swapper=swapper_address,
            expected_amount_in_base_units=amount_in_base_units,
            expected_slippage_bps=slippage_bps,
        )

    @staticmethod
    def _parse_quote(
        body: object,
        *,
        expected_swapper: str,
        expected_amount_in_base_units: int,
        expected_slippage_bps: int,
    ) -> UniswapQuote:
        if not isinstance(body, dict):
            raise QuoteProviderProtocolError("Uniswap quote response must be an object.")
        routing = body.get("routing")
        if routing != "CLASSIC":
            raise QuoteProviderProtocolError("Only CLASSIC Uniswap quotes are supported.")
        request_id = body.get("requestId")
        quote = body.get("quote")
        if not isinstance(request_id, str) or not request_id.strip() or not isinstance(quote, dict):
            raise QuoteProviderProtocolError("Uniswap quote response is missing required identifiers.")
        if quote.get("txFailureReasons"):
            raise QuoteProviderRejected("Uniswap simulation rejected the requested quote.")

        input_data = quote.get("input")
        output_data = quote.get("output")
        if not isinstance(input_data, dict) or not isinstance(output_data, dict):
            raise QuoteProviderProtocolError("Uniswap quote response is missing token amounts.")

        token_in = _normalise_address(input_data.get("token"), "input token")
        token_out = _normalise_address(output_data.get("token"), "output token")
        if token_in != BASE_USDC or token_out != BASE_WETH:
            raise QuoteProviderProtocolError("Uniswap returned a quote for an unexpected token pair.")

        response_amount_in = _positive_integer(input_data.get("amount"), "input amount")
        if response_amount_in != expected_amount_in_base_units:
            raise QuoteProviderProtocolError("Uniswap returned an input amount different from the request.")
        amount_out = _positive_integer(output_data.get("amount"), "output amount")
        minimum_out = _positive_integer(output_data.get("minimumAmount"), "minimum output amount")
        if minimum_out > amount_out:
            raise QuoteProviderProtocolError("Uniswap minimum output exceeds quoted output.")
        estimated_fee = _positive_integer(quote.get("gasFee"), "estimated gas fee")

        quoted_swapper = quote.get("swapper")
        if quoted_swapper is not None and _normalise_address(quoted_swapper, "swapper") != expected_swapper:
            raise QuoteProviderProtocolError("Uniswap returned a quote for an unexpected wallet address.")

        approval_flag = body.get("isTokenApprovalApplicable", True)
        if not isinstance(approval_flag, bool):
            raise QuoteProviderProtocolError("Uniswap approval flag has an invalid type.")
        quote_id = quote.get("quoteId")
        if quote_id is not None and not isinstance(quote_id, str):
            raise QuoteProviderProtocolError("Uniswap quote ID has an invalid type.")

        # Deliberately retain only non-executable audit metadata.  Permit data,
        # transaction data, route calldata, fee/collector data, and raw payloads
        # are intentionally excluded.
        metadata: dict[str, object] = {"provider_quote_id": quote_id}
        for name in ("blockNumber", "priceImpact", "gasUseEstimate"):
            value = quote.get(name)
            if isinstance(value, (str, int, float)):
                metadata[name] = value

        return UniswapQuote(
            provider_request_id=request_id,
            provider_quote_id=quote_id,
            routing="CLASSIC",
            token_in=token_in,
            token_out=token_out,
            amount_in_base_units=response_amount_in,
            amount_out_base_units=amount_out,
            min_amount_out_base_units=minimum_out,
            estimated_network_fee_wei=estimated_fee,
            slippage_bps=expected_slippage_bps,
            requires_token_approval=approval_flag,
            provider_metadata=metadata,
        )


def _normalise_address(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise QuoteProviderProtocolError(f"Uniswap {label} is missing or invalid.")
    address = value.lower()
    if len(address) != 42 or not address.startswith("0x"):
        raise QuoteProviderProtocolError(f"Uniswap {label} is missing or invalid.")
    try:
        int(address[2:], 16)
    except ValueError as exc:
        raise QuoteProviderProtocolError(f"Uniswap {label} is missing or invalid.") from exc
    return address


def _positive_integer(value: object, label: str) -> int:
    parsed = _nonnegative_integer(value, label)
    if parsed <= 0:
        raise QuoteProviderProtocolError(f"Uniswap {label} must be positive.")
    return parsed


def _nonnegative_integer(value: object, label: str) -> int:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise QuoteProviderProtocolError(f"Uniswap {label} is missing or invalid.")
    try:
        parsed = int(value)
    except (ValueError, TypeError) as exc:
        raise QuoteProviderProtocolError(f"Uniswap {label} is missing or invalid.") from exc
    if parsed < 0 or str(parsed) != str(value).strip():
        # Reject decimal/scientific JSON strings rather than silently rounding.
        raise QuoteProviderProtocolError(f"Uniswap {label} must be an integer base-unit string.")
    return parsed
