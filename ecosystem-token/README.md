# AIHF Ecosystem Token

A testnet-first utility-token subsystem for the AI HedgeFund / AutoTrader project.

## Design goals

- Give holders access to research, premium dashboards, strategy tooling and future marketplace features.
- Keep the token economically separate from the AutoTrader trading bankroll.
- Never represent equity, a profit share, a claim on fund assets, guaranteed yield or a promise of price appreciation.
- Minimize smart-contract trust: fixed supply, no post-deployment minting, no upgrade proxy, no blacklist, no transfer tax and no owner backdoor.
- Use Polygon Amoy first. Mainnet is intentionally absent from `hardhat.config.ts`, preventing accidental mainnet deployment from this version.

## Working identity

- Name: **AI HedgeFund Access Token**
- Symbol: **AIHF**
- Standard: ERC-20 + EIP-2612 permit
- Network target: Polygon PoS after testnet, audit and legal/compliance gates
- Supply: **100,000,000 AIHF fixed forever**
- Decimals: 18
- Economic rights: none
- Yield/revenue share: none
- AutoTrader trading-capital claim: none

The name and ticker are working engineering identifiers and have not been trademark-cleared.

## Contracts

### AIHFAccessToken

Minimal OpenZeppelin-based ERC-20. The entire fixed supply is created once in the constructor and delivered to the configured treasury address. There is no mint function or administrator after deployment.

### AIHFAccessVault

A non-yielding lock contract used for token-gated product access.

| Tier | Active locked AIHF | Intended utility |
| --- | ---: | --- |
| Reader | 100 | research feed, delayed analytics |
| Pro | 1,000 | premium dashboard, deeper research, alerts |
| Quant | 10,000 | advanced strategy lab, API/data entitlements, marketplace tooling |

An unlock request immediately stops the requested amount from counting toward access and then waits seven days before withdrawal. The vault has no administrator and no reward/yield mechanism.

## Local validation

Requires Node.js 22.10+.

```bash
cd ecosystem-token
npm install
npm run check
```

## Polygon Amoy deployment

1. Create a dedicated disposable testnet deployer wallet.
2. Fund it only with test POL.
3. Use a public treasury address for testnet. For mainnet, treasury must be a Safe multisig.
4. Configure variables from `.env.example`.
5. Run `npm run deploy:amoy`.

## Mainnet hard gate

Do not deploy this version to Polygon mainnet or create public liquidity until all of these are complete:

- independent smart-contract review/audit;
- testnet soak and event/indexer validation;
- Safe multisig treasury;
- enforceable team/insider vesting;
- legal-entity and token-classification review;
- MiCA whitepaper/notification assessment;
- public terms, privacy and risk disclosures;
- liquidity and market-integrity policy;
- incident-response runbook;
- final mainnet deployment commit frozen and reproducible.

See `docs/` for architecture, tokenomics, security, launch/compliance and integration specifications.
