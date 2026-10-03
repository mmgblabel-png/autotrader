# Security model

## Contract security

The design minimizes custom attack surface:

- OpenZeppelin Contracts 5.6.1.
- Fixed-supply token; no post-deployment mint.
- No proxy or upgrade administrator.
- No blacklist or confiscation.
- No fee/tax logic.
- Access vault uses SafeERC20 and ReentrancyGuard.
- Unlock request has a cooldown and pending tokens stop granting access immediately.
- Vault has no privileged administrator or treasury sweep.
- No yield, lending, oracle, AMM or external price dependency in the contracts.

## Treasury security

Mainnet treasury must use a Safe multisig, not a single EOA. A practical initial policy is 2-of-3 or 3-of-5 independent signers with hardware-backed keys and separated recovery material.

The AutoTrader agent must never receive an unrestricted treasury signer key. Future automated treasury proposals should require human approval or a tightly bounded allowance/module.

## Key management

- Never commit private keys.
- Testnet deployer keys must contain no mainnet assets.
- Mainnet deployment should use hardware-backed signing or a reviewed multisig procedure.
- Separate deployer, treasury and operational identities.
- Rotate compromised operational credentials immediately.

## Pre-mainnet security gate

Required:
1. clean CI build/tests from a frozen commit;
2. static analysis and manual review;
3. external audit of custom contracts and deployment configuration;
4. Amoy soak test;
5. independent verification of deployed bytecode/source;
6. multisig and vesting dry run;
7. incident-response drill;
8. legal/compliance sign-off.

## Threats explicitly addressed

- infinite mint/admin rug: removed by architecture;
- proxy takeover: no proxy;
- transfer-tax honeypot: no tax logic;
- flash access: unlock cooldown plus active-balance reduction;
- reentrancy during vault token movement: guarded;
- approval UX: EIP-2612 supported;
- single-key treasury compromise: mainnet multisig policy;
- AutoTrader fund contamination: AIHF may not be treated as fund NAV/collateral.

## Residual risks

Smart-contract bugs, wallet compromise, phishing, chain/RPC failures, regulatory reclassification, token illiquidity, market volatility and service discontinuation remain possible. An audit reduces risk but cannot eliminate it.
