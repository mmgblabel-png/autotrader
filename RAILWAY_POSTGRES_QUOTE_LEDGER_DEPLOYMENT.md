# Railway PostgreSQL Quote-Ledger Deployment Guide

**Status:** Code-complete and locally validated; **not deployed**.  This guide intentionally keeps the existing production service in paper mode.  It does not authorise a provider account, a provider key, a database service, a wallet connection, a token approval, a signature, or a blockchain transaction.

> A durable ledger and a quote route provide auditability and capacity controls; they do **not** make crypto trading profitable or lossless.  The zero-value default caps deliberately block every proposal until a separate review is completed.

## What this change adds

| Component | File | Behavior | Execution capability |
|---|---|---|---|
| Versioned database schema | `migrations/001_durable_quote_ledger.sql` | Creates policy snapshots, quote proposals, row-locked daily risk state, exposure reservations, and future receipt/fill tables. | None. |
| Migration runner | `scripts/migrate.py` | Applies SQL files once by checksum under a database advisory lock. | None. |
| Quote-only provider adapter | `autotrader/quotes/uniswap.py` | Calls only Uniswap `POST /v1/quote`, using a server-only key. | None; `/swap`, `/order`, approvals, and RPC calls are absent. |
| Proposal service | `autotrader/ledger/quote_proposals.py` | Preflights policy, requests a sanitised USDC→WETH quote, then atomically reserves daily USDC exposure. | None. |
| Protected API | `POST /api/mainnet/quote-proposals` | Requires an idempotency UUID and a dedicated server token. | Returns quote metadata only—never permit data, calldata, signature data, or a transaction hash. |

The Uniswap quote integration follows the documented `x-api-key` authentication model and Base chain ID `8453`; Uniswap documents that signing, broadcasting, nonce management, gas payment, and error handling remain the integrating application’s responsibilities.[1] [2]

## Current safe deployment posture

Keep all of the values below unchanged in the existing Railway service.  With this posture, quote proposals are blocked **before** an outgoing provider request or database connection occurs.

| Variable | Required current value | Effect |
|---|---|---|
| `MAINNET_EXECUTION_ENABLED` | `false` or unset | Fails policy preflight. |
| `MAINNET_EMERGENCY_STOP` | `true` or unset | Fails policy preflight. |
| `MAINNET_MAX_TRADE_USDC` | `0` or unset | Fails closed. |
| `MAINNET_MAX_DAILY_USDC` | `0` or unset | Fails closed. |
| `MAINNET_MAX_DAILY_LOSS_USDC` | `0` or unset | Fails closed. |
| `MAINNET_MAX_SLIPPAGE_BPS` | `0` or unset | Fails closed. |
| `MAINNET_MAX_GAS_ETH` | `0` or unset | Fails closed. |
| `MAINNET_QUOTE_PROPOSALS_ENABLED` | `false` or unset | Disables the new route. |
| `UNISWAP_API_KEY` | **Unset** | Prevents authenticated quote calls. |
| `DATABASE_URL` | **Unset** | Prevents durable ledger access until PostgreSQL exists. |
| `AUTOTRADER_QUOTE_PROPOSAL_TOKEN` | **Unset** | Makes `POST /api/mainnet/quote-proposals` return HTTP 503. |

## Future infrastructure procedure — not performed by this change

The user chose PostgreSQL in the existing Railway project.  Provisioning it can create provider usage or charges, so it requires a separate explicit confirmation before it is done.

After that confirmation, the operator should create a Railway PostgreSQL service in the same project and expose its private `DATABASE_URL` only to the API service.  The URL must never be placed in client-side code, Hostinger JavaScript, Git, logs, or chat.  The `psycopg` driver is now an application dependency and `scripts/migrate.py` applies the migration with an advisory lock and checksum record.

Run the migration as a one-off release task in the API environment only:

```bash
python scripts/migrate.py
```

The first run reports `Applied migrations: 001_durable_quote_ledger.sql`; a repeated run reports that the schema is current.  A checksum mismatch is an intentional failure and must be investigated rather than overridden.

## Expected disabled-state verification after deployment

The following checks are non-financial and do not use a provider key or a wallet.  They are the only checks appropriate while the policy remains locked.

| Check | Expected result | What it proves |
|---|---|---|
| `GET /api/health` | `200`, `mode: paper` | Paper runtime remains active. |
| `GET /api/mainnet/safety` | `execution_enabled:false`, `emergency_stop:true`, caps `0` | Existing Mainnet safety locks remain active. |
| `GET /api/mainnet/quote-proposals/status` | `enabled:false`; provider and ledger configuration are false unless infrastructure is explicitly added | New subsystem is visible but non-executable. |
| `POST /api/mainnet/quote-proposals` without `X-AutoTrader-Quote-Token` | `503` | The authenticated provider cannot be used as a public proxy. |
| `POST /api/mainnet/quote-proposals` with a token but `MAINNET_QUOTE_PROPOSALS_ENABLED=false` | `503` | Explicit disabled-state gate works before provider/database access. |

## Atomic capacity rule

For a permitted future quote proposal, the service first applies the in-process policy preflight.  It then gets one **quote-only** provider response.  In a PostgreSQL `SERIALIZABLE` transaction, the stored procedure row-locks that UTC day’s `daily_risk_state`, expires stale reservations, checks realised loss and total capacity, writes the proposal and reservation, and increments reserved exposure together.

```text
reserved_exposure_usdc + consumed_exposure_usdc + requested_usdc
    must be less than or equal to max_daily_usdc
```

The database, not a Python memory counter, enforces the decision.  The migration was applied to an isolated PostgreSQL 16 database; a 6 USDC reservation succeeded and a following 5 USDC request was rejected under a 10 USDC daily cap.  The migration runner was also verified for clean first-run and checksum-tracked repeat-run behavior.  These are storage/control tests, **not** trade tests.

## Explicitly absent capabilities

The change has no implementation of a wallet signer, MetaMask control, token approval, Permit2 signature, executable Uniswap transaction call, blockchain RPC client, nonce manager, transaction broadcast, receipt worker, or fill reconciler.  It therefore cannot trade.  A future browser-only signing implementation would require a separate security review and a new explicit confirmation describing the exact asset pair, amount, target, limits, fees, and consequence.

## References

[1] [Uniswap Swapping API Integration Guide](https://developers.uniswap.org/docs/trading/swapping-api/integration-guide)

[2] [Uniswap Get a Quote API Reference](https://developers.uniswap.org/docs/api-reference/aggregator_quote)
