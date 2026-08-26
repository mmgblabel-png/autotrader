# Durable Quote-Proposal Ledger Design

**Status:** implementation design for a disabled-by-default service.  This document describes a quote-and-reservation capability only.  It does not add wallet custody, MetaMask automation, ERC-20 approval, transaction signing, calldata creation, broadcasting, or receipt polling.

## Selected boundaries

The first adapter will target the **Uniswap Trading API `POST /v1/quote`** on Base Mainnet (`8453`).  Its API key remains server-side in `UNISWAP_API_KEY`; it is never returned by an API route, written to logs, committed to Git, or exposed to Hostinger.  The adapter will request only a quote and will never call `/swap`, `/order`, approval, signing, or broadcast endpoints.  Only the strict Base USDC → WETH input direction will be accepted because the durable daily exposure is denominated in USDC.  WETH → USDC is retained in the offline policy allowlist but is not admitted by this first ledger route, since it would require an independent, durable USDC valuation source.

> Uniswap documents `/quote` as a quote-and-transaction-building API and assigns nonce management, broadcasting, gas payment, and error handling to the integrating application.  This implementation deliberately stops before all of those capabilities.[1]

The future API route is protected by `AUTOTRADER_QUOTE_PROPOSAL_TOKEN` and disabled unless `MAINNET_QUOTE_PROPOSALS_ENABLED=true`.  It also requires the existing `MainnetExecutionPolicy` to pass its fail-closed readiness checks.  With the currently deployed values—execution disabled, emergency stop active, and every cap zero—the route must reject before a provider HTTP call or database connection is attempted.

## Exact-number model

All token and fee quantities use exact PostgreSQL `NUMERIC` fields.  On-chain token quantities are stored as integer base units (`NUMERIC(78,0)`) and USDC risk values use `NUMERIC(38,6)`.  Python uses `Decimal`; neither floating-point values nor client-provided USDC valuations are admitted.  One USDC is exactly `1_000_000` Base USDC units.

| Record | Purpose | Safety property |
|---|---|---|
| `policy_versions` | Immutable snapshot/hash of each policy applied to a proposal. | Makes each reservation auditable against its exact limits. |
| `quote_proposals` | Sanitised, quote-only provider result and expiry. | Stores no API key, calldata, signature, permit payload, or transaction object. |
| `daily_risk_state` | One locked risk row for a Base/UTC-day pair. | Serialises capacity decisions between concurrent requests. |
| `exposure_reservations` | Temporary or consumed USDC daily-exposure allocation. | Prevents concurrent quote proposals exceeding the daily cap. |
| `chain_transactions`, `transaction_receipts`, `fills` | Durable future reconciliation tables. | Schema only in this phase; current code never inserts execution records. |
| `ledger_entries`, `risk_events` | Append-only operational/audit records. | Supports later reconciliation without overwriting the proposal evidence. |

## Atomic reservation algorithm

The external quote request occurs before the database transaction so a slow upstream response never holds a risk lock.  The proposal is then written inside a `SERIALIZABLE` PostgreSQL transaction.  A database function inserts and row-locks the relevant `daily_risk_state` row, expires stale active reservations, checks realised loss and the sum of reserved plus consumed exposure, creates the reservation, and increments the locked daily counter.  Any violation raises an error and rolls back the proposal and reservation together.

Daily exposure is the sum of `reserved_exposure_usdc` and `consumed_exposure_usdc`.  A reservation remains counted until it expires, is explicitly released, or is later consumed by a separately audited transaction workflow.  The first implementation has no consume/release/execution route; therefore it cannot broadcast or change an on-chain balance.

The existing policy still controls chain, pair, per-trade cap, daily cap, daily realised-loss stop, slippage cap, maximum fee, and quote TTL.  A zero or unset cap rejects the request.  This is a **fail-closed loss-cap control**, not a guarantee that trading can be profitable or lossless.

## Future execution separation

The quote response will expose only quote metadata: input/output amounts, minimum output, routing classification, expiry, policy version, and whether a future approval review may be required.  It will not expose Uniswap permit data, transaction targets, data, or values.  A future browser-only signing design would need its own code review, independent router/transaction validation, user-visible amount/asset/target disclosure, explicit current-conversation approval, and wallet-extension confirmation.  That work is outside this change.

## References

[1] [Uniswap Swapping API Integration Guide](https://developers.uniswap.org/docs/trading/swapping-api/integration-guide)
[2] [Uniswap Get a Quote API Reference](https://developers.uniswap.org/docs/api-reference/aggregator_quote)
