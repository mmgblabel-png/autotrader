# AutoTrader, AIHF and Sandbox integration

## Principle

Token access is read-only from the perspective of the trading engine. The trading system never buys AIHF, never uses AIHF as collateral, never counts AIHF treasury holdings as fund NAV and never changes risk because of token price.

The Sandbox HQ is a presentation, onboarding and community surface. It never becomes an authority for AutoTrader execution.

## Canonical access authority

The canonical service entitlement is the current result of `AIHFAccessVault.tierOf(wallet)` on the configured network.

A Sandbox NFT or pass can mirror an entitlement for in-world experiences, but it does not replace the live vault check for:
- premium research;
- API/data access;
- strategy marketplace creator permissions;
- any external dashboard feature.

## Recommended API surface

- `POST /api/ecosystem/auth/nonce` — create single-use wallet-login nonce.
- `POST /api/ecosystem/auth/verify` — verify signed login challenge.
- `GET /api/ecosystem/access` — return wallet, active locked balance, tier, block number and observation timestamp.
- `GET /api/ecosystem/catalog` — describe service entitlements per tier.
- `GET /api/ecosystem/sandbox/pass-eligibility` — return the current Sandbox pass tier that may be issued.
- `POST /api/ecosystem/sandbox/pass-claim` — idempotent request for the current entitlement epoch.
- `GET /api/ecosystem/sandbox/pass-status` — show issued tier, epoch and native Sandbox asset reference.
- premium research endpoints — authorize against the current session tier.

## Authentication flow

1. frontend requests one-time nonce;
2. wallet signs a domain-bound message;
3. backend verifies address/signature and consumes nonce;
4. backend reads `tierOf(wallet)` from the canonical vault through an allowlisted Polygon RPC;
5. API issues a short-lived session containing only the entitlement tier;
6. premium endpoints enforce the tier;
7. Sandbox pass eligibility is derived from the same tier;
8. RPC or entitlement failure never changes AutoTrader execution or risk controls.

## Sandbox HQ flow

`Sandbox LAND -> AI HedgeFund HQ -> wallet connect -> AIHF entitlement -> Sandbox presentation pass -> in-world room/perk -> external research/dashboard/marketplace`

The HQ uses native Sandbox NFT Sensor gating where possible. The intended native assets are:
- AIHF Reader Access Pass;
- AIHF Pro Access Pass;
- AIHF Quant Access Pass;
- MMinc Founder Key (independent scarce NFT).

Native pass URLs/IDs are recorded only after the assets are actually created and minted. See `config/sandbox-hq-access.json`.

## Security boundary for passes

Sandbox pass ownership can unlock only bounded in-world content and non-sensitive perks.

It cannot by itself authorize:
- premium research;
- real-time datasets;
- API keys;
- marketplace creator permissions;
- AutoTrader execution;
- any transfer of treasury or trading capital.

This prevents a stale or transferred Sandbox pass from becoming equivalent to a live AIHF lock.

## Failure behavior

- RPC unavailable: fail closed for newly requested premium access.
- Chain reorg: recompute using an explicit safe/finalized-block policy.
- Vault address mismatch: deny access.
- Wrong chain: deny access.
- Signature replay: consume nonce once and enforce expiry/domain binding.
- Token price unavailable: irrelevant; access depends on locked units only.
- Sandbox indexer unavailable: keep public HQ content available; do not issue or refresh native passes until state is consistent.
- Sandbox pass mismatch: deny the external premium feature and re-check the canonical vault.

## Product roadmap

Phase 0 — contracts, tests, security and legal architecture.
Phase 1 — Polygon Amoy deploy, wallet sign-in, entitlement read.
Phase 2 — Sandbox HQ shell, public onboarding and pass-bridge dry run.
Phase 3 — closed beta with valueless test tokens and minimum Sandbox pass inventory.
Phase 4 — security audit, legal entity and MiCA classification/whitepaper process as applicable.
Phase 5 — mainnet token + vault with multisig treasury and vesting.
Phase 6 — production Sandbox entitlement bridge and Founder Key integration.
Phase 7 — optional public distribution/liquidity only after explicit compliance and market-integrity gate.
Phase 8 — marketplace/payments only when the corresponding service actually exists.

The token is not required for AutoTrader itself to operate.
