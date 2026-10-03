# AIHF launch runbook

Every phase is fail-closed. Passing an earlier phase does not authorize a later phase.

## Phase 0 — repository package

Exit criteria:
- contracts compile;
- unit/security tests pass;
- fixed supply proven;
- no privileged mint/upgrade/blacklist/tax path;
- access vault conservation/cooldown tests pass;
- vesting cliff test passes;
- documentation and risk boundaries reviewed.

## Phase 1 — Polygon Amoy

Deploy only with a disposable testnet signer and test POL.

Exit criteria:
- token/vault/vesting addresses recorded;
- source verified on explorer;
- all constructor parameters reproduced;
- token transfers tested;
- approve + lock tested;
- permit + lock tested;
- unlock cooldown tested;
- access tiers read by an integration client;
- event indexing survives restart/replay;
- no mainnet funds or AutoTrader secrets present.

## Phase 2 — closed product beta

Use valueless test tokens only.

Exit criteria:
- wallet authentication uses signed nonces;
- replay/domain/expiry protection tested;
- entitlement cache fails closed;
- Reader/Pro/Quant feature gates match catalog;
- rate limits enforced;
- premium endpoints do not touch trading execution;
- operational logs exclude wallet secrets and signatures after verification.

## Phase 3 — security and legal

Exit criteria:
- independent contract audit/review;
- fixes re-audited where material;
- Safe treasury created and dry-run;
- signer recovery process documented;
- team/contributor vesting wallets finalized;
- legal person/issuer roles fixed;
- MiCA classification reviewed;
- whitepaper/notification process completed when required;
- terms/privacy/risk/marketing review complete;
- trademark/name/ticker screening complete.

## Phase 4 — mainnet deployment

Use a frozen, tagged commit only.

Exit criteria:
- exact source/bytecode verified;
- chain ID checked;
- Safe receives supply;
- team allocation moved immediately into vesting;
- distribution wallets publicly documented;
- no hidden mint/admin;
- incident monitoring enabled;
- no DEX liquidity yet unless Phase 5 is independently approved.

## Phase 5 — public distribution and optional liquidity

Exit criteria:
- public-offer/trading legal gate passed;
- marketing matches notified whitepaper where applicable;
- conflicts and treasury wallets disclosed;
- liquidity budget is separate from AutoTrader;
- market-integrity policy prohibits wash trading, fake volume and undisclosed manipulation;
- no listing/liquidity/price guarantee;
- treasury actions require multisig threshold.

## Phase 6 — marketplace/governance

Exit criteria:
- marketplace service actually operational;
- creator licence and security policies published;
- payment/CASP implications reviewed;
- governance remains non-binding unless separately approved;
- abusive/spam/sybil controls tested.

## Emergency rule

A contract or legal defect discovered before public launch halts progression. Because the token is deliberately non-upgradeable, a material contract flaw requires a new audited deployment rather than an administrator silently changing code.
