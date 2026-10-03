# AutoTrader product integration

## Principle

Token access is read-only from the perspective of the trading engine. The trading system never buys AIHF, never uses AIHF as collateral, never counts AIHF treasury holdings as fund NAV and never changes risk because of token price.

## Recommended API surface

- `POST /api/ecosystem/auth/nonce` — create single-use wallet-login nonce.
- `POST /api/ecosystem/auth/verify` — verify signed login challenge.
- `GET /api/ecosystem/access` — return wallet, active locked balance, tier, block number and observation timestamp.
- `GET /api/ecosystem/catalog` — describe service entitlements per tier.
- premium research endpoints — authorize against session tier.

## Authentication flow

1. frontend requests one-time nonce;
2. wallet signs a domain-bound message;
3. backend verifies address/signature and consumes nonce;
4. backend reads `tierOf(wallet)` from the canonical vault through an allowlisted Polygon RPC;
5. API issues a short-lived session containing only the entitlement tier;
6. premium endpoints enforce the tier;
7. RPC or entitlement failure never changes AutoTrader execution or risk controls.

## Failure behavior

- RPC unavailable: fail closed for newly requested premium access.
- Chain reorg: recompute using an explicit finalized/safe-block policy.
- Vault address mismatch: deny access.
- Wrong chain: deny access.
- Signature replay: consume nonce once and enforce expiry/domain binding.
- Token price unavailable: irrelevant; access depends on locked units only.

## Product roadmap

Phase 0 — contracts, tests, security and legal architecture.
Phase 1 — Polygon Amoy deploy, wallet sign-in, entitlement read.
Phase 2 — closed beta with valueless test tokens.
Phase 3 — security audit, legal entity and MiCA classification/whitepaper process as applicable.
Phase 4 — mainnet token + vault with multisig treasury and vesting.
Phase 5 — optional public distribution/liquidity only after explicit compliance and market-integrity gate.
Phase 6 — marketplace/payments only when the corresponding service actually exists.

The token is not required for AutoTrader itself to operate.
