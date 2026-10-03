# AIHF Ecosystem Token

A testnet-first utility-token subsystem for the AI HedgeFund / AutoTrader project, now integrated with the **Sandbox Monetized Empire / AI HedgeFund HQ** product surface.

## Design goals

- Give holders access to research, premium dashboards, strategy tooling and future marketplace features.
- Extend those entitlements into a Sandbox HQ without treating a Sandbox NFT as authority for sensitive services.
- Keep the token, Sandbox operating budget and LAND ecosystem economically separate from the AutoTrader trading bankroll.
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

A non-yielding lock contract used for token-gated product access. Its permit path tolerates a valid permit being submitted first by a third party and then safely falls back to the resulting allowance.

### AIHFVestingWallet

An OpenZeppelin-based cliff vesting wallet for team/contributor grants. The launch policy uses a four-year linear schedule with a one-year cliff, so no team allocation is directly unlocked at launch.

| Tier | Active locked AIHF | Intended utility |
| --- | ---: | --- |
| Reader | 100 | research feed, delayed analytics, Sandbox Research Floor |
| Pro | 1,000 | premium dashboard, deeper research, alerts, Sandbox Pro Strategy Lab |
| Quant | 10,000 | advanced strategy lab, API/data entitlements, marketplace tooling, Sandbox Quant Vault |

An unlock request immediately stops the requested amount from counting toward access and then waits seven days before withdrawal. The vault has no administrator and no reward/yield mechanism.

## Sandbox Monetized Empire

The integrated experience target is **MMinc AI HedgeFund HQ** on Sandbox LAND **(92,115)** / Polygon LAND token **#130448**.

The native flow is:

`public lobby -> AIHF education -> wallet connect -> live vault entitlement -> Sandbox pass/perks -> premium web portal`

A native Sandbox pass is only an in-world presentation credential. Sensitive research, API and marketplace permissions always require a fresh wallet-authenticated AIHF vault entitlement.

The separate **MMinc Founder Key** may unlock founder rooms, lore, cosmetics and beta invitations, but never bypasses Reader/Pro/Quant requirements.

See:
- `docs/SANDBOX_MONETIZED_EMPIRE.md`
- `docs/SANDBOX_ACCESS_BRIDGE.md`
- `config/sandbox-hq-access.json`

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
6. Integrate wallet auth and entitlement reads.
7. Dry-run the Sandbox bridge before spending real Catalysts or issuing production passes.

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

Do not use AutoTrader live trading capital for token launch, LAND, Catalysts, Founder Key minting, marketing or liquidity.

See `docs/` for architecture, product/revenue model, tokenomics, security, operations, Sandbox HQ, launch/compliance and integration specifications. The canonical tier feature catalog is `config/access-catalog.json`.
